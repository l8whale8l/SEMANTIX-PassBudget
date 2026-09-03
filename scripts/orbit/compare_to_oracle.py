"""Compare the product orbit engine against the independent GMAT expected table.

The expected table is read-only input. This script never writes to it, never rounds it, and
never widens a tolerance. If a delta exceeds a ceiling the run fails and says so; the fix is
in the engine or in the contract's amendment log, never here.

Usage:
    python scripts/orbit/compare_to_oracle.py <expected.json> <fixture_inputs.json> <out.json>
"""

from __future__ import annotations

import json
import pathlib
import statistics
import sys
from datetime import UTC, datetime

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "src"))

from semantix_passbudget.adapters.orbit.passes import (
    PassEvent,
    StationSite,
    find_passes,
    sgp4_position_source,
    two_body_position_source,
)
from semantix_passbudget.adapters.orbit.twobody import (
    circular_state_from_elements,
)

# Contract section 10.1. These are the gate. They are fixed in the contract and may not be
# widened here, or anywhere, after a delta has been seen.
CEILING_AOS_S = 1.000
CEILING_LOS_S = 1.000
CEILING_DURATION_S = 2.000
CEILING_MAX_ELEVATION_DEG = 0.050
CEILING_MAX_ELEVATION_TIME_S = 2.000


def parse_utc(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%S.%f%z").astimezone(UTC)


def run_product(inputs: dict, window: dict, fixture_id: str) -> tuple[PassEvent, ...]:
    sites = tuple(
        StationSite(
            station_key=s["station_key"],
            latitude_deg=float(s["latitude_deg"]),
            longitude_east_deg=float(s["longitude_deg_east"]),
            ellipsoidal_height_m=float(s["ellipsoidal_height_m"]),
            minimum_elevation_deg=float(s["minimum_elevation_deg"]),
        )
        for s in inputs["stations"]
    )
    return find_passes(
        build_position_source(inputs),
        sites,
        parse_utc(window["start_utc"]),
        parse_utc(window["end_utc"]),
        fixture_id,
    )


def build_position_source(inputs: dict):
    """Select the propagator the fixture declares. There is no default and no fallback."""
    kind = inputs["kind"]
    if kind == "GP_TLE":
        return sgp4_position_source(inputs["tle"]["line_1"], inputs["tle"]["line_2"])
    if kind == "VIRTUAL_CIRCULAR":
        profile = inputs["propagator"]["profile"]
        if profile != "TWO_BODY_V1":
            raise SystemExit(f"UNSUPPORTED_PROPAGATOR_PROFILE: {profile}")
        state = inputs["state"]
        mu = float(inputs["central_body"]["mu_m3_per_s2"])
        position, velocity = circular_state_from_elements(
            semi_major_axis_m=float(state["semi_major_axis_m"]),
            inclination_deg=float(state["inclination_deg"]),
            raan_deg=float(state["raan_deg"]),
            argument_of_perigee_deg=float(state["argument_of_perigee_deg"]),
            true_anomaly_deg=float(state["true_anomaly_deg"]),
            eccentricity=float(state["eccentricity"]),
            mu=mu,
        )
        epoch_s = (
            parse_utc(inputs["epoch_utc"]) - datetime(1970, 1, 1, tzinfo=UTC)
        ).total_seconds()
        return two_body_position_source(epoch_s, position, velocity, mu)
    raise SystemExit(f"UNSUPPORTED_FIXTURE_KIND: {kind}")


def compare_window(inputs: dict, expected_window: dict, window_bounds: dict, fixture_id: str):
    """Delta table for one window, plus the structural checks that precede it."""
    produced = run_product(inputs, window_bounds, fixture_id)

    # Determinism (contract section 9): a second run in the same state must be identical.
    repeat = run_product(inputs, window_bounds, fixture_id)
    deterministic = [(e.station_key, e.aos, e.los, e.maximum_elevation_deg) for e in produced] == [
        (e.station_key, e.aos, e.los, e.maximum_elevation_deg) for e in repeat
    ]

    declared_stations = [s["station_key"] for s in inputs["stations"]]
    product_by_station: dict[str, list[PassEvent]] = {s: [] for s in declared_stations}
    for event in produced:
        product_by_station[event.station_key].append(event)

    expected_by_station: dict[str, list[dict]] = {s: [] for s in declared_stations}
    for row in expected_window["passes"]:
        expected_by_station.setdefault(row["station_key"], []).append(row)

    # Structural agreement first. Contract section 9: a count mismatch stops the comparison
    # rather than producing a delta table from a guessed pairing.
    count_rows = []
    counts_agree = True
    for station in declared_stations:
        got = len(product_by_station.get(station, []))
        want = len(expected_by_station.get(station, []))
        if got != want:
            counts_agree = False
        count_rows.append(
            {
                "station_key": station,
                "expected_passes": want,
                "product_passes": got,
                "agree": got == want,
                "zero_contact": want == 0 and got == 0,
            }
        )

    if not counts_agree:
        return {
            "window": expected_window["window"],
            "status": "FAILED_PASS_COUNT_MISMATCH",
            "deterministic": deterministic,
            "pass_counts": count_rows,
            "note": (
                "Pass counts disagree, so no delta table was produced. Pairing passes across a "
                "count mismatch would hide a missing pass as a small timing delta."
            ),
            "passes": [],
        }

    rows = []
    for station in declared_stations:
        # Matched by (station, ordinal), never by nearest time (contract section 9).
        for ordinal, (want, got) in enumerate(
            zip(expected_by_station[station], product_by_station[station], strict=True)
        ):
            aos_want = parse_utc(want["aos_utc"])
            los_want = parse_utc(want["los_utc"])
            peak_want = parse_utc(want["maximum_elevation_time_utc"])

            # A clipped boundary is not a computed crossing; comparing it to itself is a
            # tautology and is excluded from the delta table (contract section 8.4).
            aos_delta = None if got.clipped_start else abs((got.aos - aos_want).total_seconds())
            los_delta = None if got.clipped_end else abs((got.los - los_want).total_seconds())

            rows.append(
                {
                    "station_key": station,
                    "ordinal": ordinal,
                    "stable_key": got.stable_key,
                    "clipped_start": got.clipped_start,
                    "clipped_end": got.clipped_end,
                    "aos_expected": want["aos_utc"],
                    "aos_product": got.aos.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z",
                    "aos_delta_s": aos_delta,
                    "los_expected": want["los_utc"],
                    "los_product": got.los.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z",
                    "los_delta_s": los_delta,
                    "duration_expected_s": want["duration_s"],
                    "duration_product_s": got.duration_s,
                    "duration_delta_s": abs(got.duration_s - float(want["duration_s"])),
                    "max_elevation_expected_deg": want["maximum_elevation_deg"],
                    "max_elevation_product_deg": got.maximum_elevation_deg,
                    "max_elevation_delta_deg": abs(
                        got.maximum_elevation_deg - float(want["maximum_elevation_deg"])
                    ),
                    "max_elevation_time_expected": want["maximum_elevation_time_utc"],
                    "max_elevation_time_product": (
                        got.maximum_elevation_time.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"
                    ),
                    "max_elevation_time_delta_s": abs(
                        (got.maximum_elevation_time - peak_want).total_seconds()
                    ),
                }
            )

    breaches = []
    for row in rows:
        for field, ceiling, label in (
            ("aos_delta_s", CEILING_AOS_S, "AOS"),
            ("los_delta_s", CEILING_LOS_S, "LOS"),
            ("duration_delta_s", CEILING_DURATION_S, "duration"),
            ("max_elevation_delta_deg", CEILING_MAX_ELEVATION_DEG, "max elevation"),
            ("max_elevation_time_delta_s", CEILING_MAX_ELEVATION_TIME_S, "max-elevation time"),
        ):
            value = row[field]
            if value is not None and value > ceiling:
                breaches.append(
                    {
                        "station_key": row["station_key"],
                        "ordinal": row["ordinal"],
                        "quantity": label,
                        "observed": value,
                        "ceiling": ceiling,
                    }
                )

    return {
        "window": expected_window["window"],
        "status": "PASS" if not breaches and deterministic else "FAIL",
        "deterministic": deterministic,
        "pass_counts": count_rows,
        "zero_contact_stations_expected": expected_window["zero_contact_stations"],
        "zero_contact_stations_product": [
            s for s in declared_stations if not product_by_station[s]
        ],
        "ceiling_breaches": breaches,
        "statistics": summarise(rows),
        "passes": rows,
    }


def summarise(rows: list[dict]) -> dict:
    def stats(field: str) -> dict:
        values = [r[field] for r in rows if r[field] is not None]
        if not values:
            return {"n": 0, "max": None, "mean": None}
        return {
            "n": len(values),
            "max": max(values),
            "mean": statistics.fmean(values),
        }

    return {
        "aos_delta_s": stats("aos_delta_s"),
        "los_delta_s": stats("los_delta_s"),
        "duration_delta_s": stats("duration_delta_s"),
        "max_elevation_delta_deg": stats("max_elevation_delta_deg"),
        "max_elevation_time_delta_s": stats("max_elevation_time_delta_s"),
    }


def main() -> None:
    expected = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
    inputs = json.loads(pathlib.Path(sys.argv[2]).read_text(encoding="utf-8"))
    out = pathlib.Path(sys.argv[3])

    fixture_id = expected["evidence_id"]
    bounds = {w["window"]: w for w in inputs["analysis_windows"]}

    windows = [
        compare_window(inputs, w, bounds[w["window"]], fixture_id) for w in expected["windows"]
    ]

    overall = "PASS" if all(w["status"] == "PASS" for w in windows) else "FAIL"

    # The worst delta anywhere, which is the number the release report must quote.
    def worst(field: str) -> float | None:
        values = [
            w["statistics"][field]["max"]
            for w in windows
            if w["statistics"][field]["max"] is not None
        ]
        return max(values) if values else None

    document = {
        "evidence_id": fixture_id,
        "comparison": "PRODUCT_ENGINE vs INDEPENDENT_ORACLE",
        "product_engine": "semantix_passbudget.adapters.orbit (python-sgp4 2.27, Vallado rev 2)",
        "oracle": f"{expected['oracle_tool']} {expected['oracle_version']} (SPICESGP4)",
        "independence": (
            "The oracle table was produced by NASA GMAT from the same frozen TLE and the same "
            "contract settings, with no knowledge of the product engine. The product engine did "
            "not contribute to any expected value, and no expected value or tolerance was "
            "adjusted after the deltas were known."
        ),
        "ceilings": {
            "aos_delta_s": CEILING_AOS_S,
            "los_delta_s": CEILING_LOS_S,
            "duration_delta_s": CEILING_DURATION_S,
            "max_elevation_delta_deg": CEILING_MAX_ELEVATION_DEG,
            "max_elevation_time_delta_s": CEILING_MAX_ELEVATION_TIME_S,
        },
        "overall_status": overall,
        "worst_observed": {
            "aos_delta_s": worst("aos_delta_s"),
            "los_delta_s": worst("los_delta_s"),
            "duration_delta_s": worst("duration_delta_s"),
            "max_elevation_delta_deg": worst("max_elevation_delta_deg"),
            "max_elevation_time_delta_s": worst("max_elevation_time_delta_s"),
        },
        "windows": windows,
    }

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")

    print(f"wrote {out}")
    print(f"OVERALL: {overall}")
    for key, value in document["worst_observed"].items():
        print(f"  worst {key:30s} = {value}")
    for w in windows:
        print(
            f"  {w['window']}: {w['status']}  deterministic={w['deterministic']}  "
            f"breaches={len(w.get('ceiling_breaches', []))}"
        )
    raise SystemExit(0 if overall == "PASS" else 1)


if __name__ == "__main__":
    main()
