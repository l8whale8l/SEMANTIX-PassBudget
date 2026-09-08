"""Convert raw NASA GMAT ContactLocator reports into the EVD-ORB expected event table.

The raw reports are evidence artifacts and are never edited. This converter is the only
path from them to the expected table, so that no expected number exists as a hand-copied
literal anywhere in the repository.

It reads both report formats GMAT produced for the same event solution:

  * the `SiteViewMaxElevationReport`, which carries AOS, LOS, duration, maximum elevation
    and the time of maximum elevation;
  * the legacy report, which is the only one that states a zero-contact observer explicitly.

The two are cross-checked against each other. A disagreement means the reporting layer is
untrustworthy and the converter refuses to emit a table rather than choosing a winner.

Usage:
    python scripts/orbit/gmat_to_expected.py <raw_dir> <fixture_id> <out.json>
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import re
import sys
from datetime import UTC, datetime

GMAT_EPOCH = re.compile(r"\d{2} \w{3} \d{4} \d{2}:\d{2}:\d{2}\.\d{3}")
MAXELEV_ROW = re.compile(
    rf"^\s*(?P<observer>\S+)\s+"
    rf"(?P<start>{GMAT_EPOCH.pattern})\s+"
    rf"(?P<stop>{GMAT_EPOCH.pattern})\s+"
    rf"(?P<duration>[-\d.]+)\s+"
    rf"(?P<max_el>[-\d.]+)\s+"
    rf"(?P<max_el_time>{GMAT_EPOCH.pattern})\s*$"
)
LEGACY_OBSERVER = re.compile(r"^Observer:\s*(\S+)\s*$")
LEGACY_ROW = re.compile(
    rf"^\s*(?P<start>{GMAT_EPOCH.pattern})\s+(?P<stop>{GMAT_EPOCH.pattern})\s+"
    rf"(?P<duration>[-\d.]+)\s*$"
)
LEGACY_NO_EVENTS = re.compile(r"^There are no contact events")


def parse_epoch(text: str) -> datetime:
    """GMAT's `03 Sep 2026 12:09:00.000` to an aware UTC datetime."""
    return datetime.strptime(text, "%d %b %Y %H:%M:%S.%f").replace(tzinfo=UTC)


def iso_us(moment: datetime) -> str:
    """Canonical `...Z` form with exactly six fractional digits, matching domain/time.py."""
    return moment.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


def read_maxelev(path: pathlib.Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        match = MAXELEV_ROW.match(line)
        if match is None:
            continue
        start = parse_epoch(match["start"])
        stop = parse_epoch(match["stop"])
        rows.append(
            {
                "station_key": match["observer"].replace("_", "-"),
                "aos_utc": iso_us(start),
                "los_utc": iso_us(stop),
                "duration_s": float(match["duration"]),
                "maximum_elevation_deg": float(match["max_el"]),
                "maximum_elevation_time_utc": iso_us(parse_epoch(match["max_el_time"])),
            }
        )
    return rows


def read_legacy(path: pathlib.Path) -> dict[str, list[tuple[str, str, float]]]:
    """Observer -> its intervals. An observer with no events maps to an empty list.

    The empty list is the point of reading this file at all: the maximum-elevation report
    simply omits a station that saw nothing, and 'omitted' and 'saw nothing' must not be the
    same thing in the expected table (contract section 8.6).
    """
    per_observer: dict[str, list[tuple[str, str, float]]] = {}
    current: str | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        observer = LEGACY_OBSERVER.match(line.strip())
        if observer is not None:
            current = observer.group(1).replace("_", "-")
            per_observer.setdefault(current, [])
            continue
        if current is None:
            continue
        if LEGACY_NO_EVENTS.match(line.strip()):
            per_observer[current] = []
            continue
        row = LEGACY_ROW.match(line)
        if row is not None:
            per_observer[current].append(
                (
                    iso_us(parse_epoch(row["start"])),
                    iso_us(parse_epoch(row["stop"])),
                    float(row["duration"]),
                )
            )
    return per_observer


def cross_check(
    maxelev: list[dict[str, object]], legacy: dict[str, list[tuple[str, str, float]]]
) -> None:
    """Two GMAT report writers reading one event solution must agree."""
    from_maxelev: dict[str, list[tuple[str, str, float]]] = {}
    for row in maxelev:
        from_maxelev.setdefault(str(row["station_key"]), []).append(
            (str(row["aos_utc"]), str(row["los_utc"]), float(row["duration_s"]))
        )
    for station in sorted(set(from_maxelev) | set(legacy)):
        left = sorted(from_maxelev.get(station, []))
        right = sorted(legacy.get(station, []))
        if len(left) != len(right):
            raise SystemExit(
                f"REPORT_DISAGREEMENT: {station} has {len(left)} events in the maximum-elevation "
                f"report and {len(right)} in the legacy report."
            )
        for (a_start, a_stop, a_dur), (b_start, b_stop, b_dur) in zip(left, right, strict=True):
            if a_start != b_start or a_stop != b_stop or abs(a_dur - b_dur) > 1e-6:
                raise SystemExit(
                    f"REPORT_DISAGREEMENT: {station} interval mismatch "
                    f"{a_start}/{a_stop}/{a_dur} vs {b_start}/{b_stop}/{b_dur}"
                )


def sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_window(raw: pathlib.Path, fixture_id: str, window: str) -> dict[str, object]:
    suffix = "" if window == "W1" else f"-{window}"
    maxelev_path = raw / f"{fixture_id}{suffix}-maxelev.report"
    legacy_path = raw / f"{fixture_id}{suffix}-legacy.report"
    maxelev = read_maxelev(maxelev_path)
    legacy = read_legacy(legacy_path)
    cross_check(maxelev, legacy)

    # Contract section 9: sort by (aos, los, station_key), never by discovery order.
    passes = sorted(maxelev, key=lambda r: (r["aos_utc"], r["los_utc"], r["station_key"]))
    for row in passes:
        aos = str(row["aos_utc"]).replace("-", "").replace(":", "").replace(".", "")[:22]
        row["stable_key"] = f"ORB-{fixture_id}-{row['station_key']}-{aos.rstrip('Z')}"

    stations = sorted(legacy)
    return {
        "window": window,
        "source_reports": {
            maxelev_path.name: sha256(maxelev_path),
            legacy_path.name: sha256(legacy_path),
        },
        "stations_reported": stations,
        "zero_contact_stations": [s for s in stations if not legacy[s]],
        "pass_count_by_station": {s: len(legacy[s]) for s in stations},
        "total_pass_count": len(passes),
        "passes": passes,
    }


def main() -> None:
    raw = pathlib.Path(sys.argv[1])
    fixture_id = sys.argv[2]
    out = pathlib.Path(sys.argv[3])

    document = {
        "evidence_id": fixture_id,
        "role": "INDEPENDENT_ORACLE_EXPECTED_TABLE",
        "oracle_tool": "NASA GMAT",
        "oracle_version": "R2026a",
        "generated_by": "scripts/orbit/gmat_to_expected.py",
        "generation_note": (
            "Every value here was parsed from the preserved raw GMAT reports. No expected value "
            "was typed by hand, and the raw reports were not edited. Regenerate with the command "
            "in the evidence README to reproduce this file byte for byte."
        ),
        "independence_note": (
            "This table is the oracle. It must never be regenerated from, adjusted towards, or "
            "reconciled with the product engine's output."
        ),
        "windows": [build_window(raw, fixture_id, w) for w in ("W1", "W2")],
    }

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(document, indent=2, sort_keys=False) + "\n", encoding="utf-8")

    total = sum(int(w["total_pass_count"]) for w in document["windows"])  # type: ignore[index]
    print(f"wrote {out}")
    print(f"windows: {len(document['windows'])}  total passes: {total}")
    for w in document["windows"]:  # type: ignore[union-attr]
        print(
            f"  {w['window']}: {w['total_pass_count']} passes, "  # type: ignore[index]
            f"zero-contact stations {w['zero_contact_stations']}"  # type: ignore[index]
        )


if __name__ == "__main__":
    main()
