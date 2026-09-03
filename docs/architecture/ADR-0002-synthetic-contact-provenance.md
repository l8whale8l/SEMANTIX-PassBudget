# ADR-0002: Contact source provenance and orbit `NOT_APPLICABLE` in the physical schema

- Status: Accepted for P0 (schema revision `v0.2-delta`, Alembic revision `0002_contact_source_provenance`)
- Date: 2026-09-03
- Supersedes nothing. Extends `db/postgresql/schema_v0_1.sql` additively; revision `0001_schema_v0_1` is not rewritten.

## Context

The accepted physical schema v0.1 encodes two assumptions that are correct for orbit-derived
contacts and wrong for directly injected synthetic contacts:

1. `scenario_revision.orbit_revision_id uuid NOT NULL REFERENCES orbit_revision(revision_id)`.
   Every scenario revision must name an orbit revision.
2. `geometric_access.maximum_elevation_udeg bigint NOT NULL` and
   `geometric_access.maximum_elevation_at timestamptz NOT NULL`, with
   `geometric_peak_time_ck CHECK (true_aos <= maximum_elevation_at AND maximum_elevation_at < true_los)`.
   Every geometric access row must carry a peak elevation and its time.

`PB-GOLDEN-CORE-01` and every other `SYN-CONTACT-01` fixture inject the contact interval directly.
The governing contract for these fixtures is:

- `골든시나리오설계도.md` §12: "접촉 구간 출처는 궤도가 아닌 `SYN-CONTACT-01`"
- `골든시나리오설계도.md` §13 AC-03A: "`orbit_dependency=NOT_APPLICABLE`; 궤도 정확성 주장 금지"
- `P0_FUNCTIONAL_SPEC.md` §13: "orbit dependency는 `NOT_APPLICABLE`, 결과 등급은 `CONCEPT_ONLY`"
- `골든시나리오설계도.md` §23.3: "값이 적용되지 않는 경우는 UNKNOWN이 아니라 별도 `NOT_APPLICABLE`로 표현한다"

A synthetic contact has no propagator, no station geometry and therefore no maximum elevation.
Storing an invented orbit revision or an invented elevation would violate design principle 2 of the
P0 specification ("모르는 값은 0이나 임의 기본값으로 채우지 않는다") and would make
`orbit_dependency=NOT_APPLICABLE` a lie at the row level. Making the columns simply nullable would
lose the existing guarantee for real orbit contacts, which `골든시나리오설계도.md` §23.4 requires
("출력은 AOS, LOS, duration, maximum elevation과 그 시각이다").

This is the conflict recorded as `CONFLICT-DB-01` in `docs/specs/SPEC_CONFLICT_REGISTER.md`.

## Decision

Introduce an explicit, typed contact-source discriminator and make the orbit and elevation
contracts conditional on it, rather than unconditional or absent.

### New type

```sql
CREATE TYPE contact_source_kind AS ENUM ('ORBIT_DERIVED', 'SYNTHETIC_INJECTED');
```

### `scenario_revision`

- Add `contact_source contact_source_kind NOT NULL DEFAULT 'ORBIT_DERIVED'`.
- Add `synthetic_contact_provider_revision varchar(96)` — the immutable provider revision string
  (`SYN-CONTACT-01`) that produced the injected intervals.
- Drop `NOT NULL` from `orbit_revision_id`. The FK to `orbit_revision(revision_id)` is unchanged.
- Add `scenario_contact_source_ck`:
  - `ORBIT_DERIVED` requires `orbit_revision_id IS NOT NULL` and forbids
    `synthetic_contact_provider_revision`.
  - `SYNTHETIC_INJECTED` requires `orbit_revision_id IS NULL` and requires a non-empty
    `synthetic_contact_provider_revision`.
- Add `UNIQUE (id, contact_source)` so children can carry a validated composite FK.

The default keeps every pre-existing row and every future orbit scenario under the original,
unweakened contract: an orbit-derived scenario still cannot exist without an orbit revision.

### `scenario_station`

- Add `contact_source contact_source_kind NOT NULL DEFAULT 'ORBIT_DERIVED'`.
- Add `FOREIGN KEY (scenario_revision_id, contact_source) REFERENCES scenario_revision(id, contact_source)`.
- Add `UNIQUE (id, contact_source)`.

The station row cannot disagree with its scenario revision; the database enforces it declaratively
rather than through an application invariant.

### `geometric_access`

- Add `contact_source contact_source_kind NOT NULL DEFAULT 'ORBIT_DERIVED'`.
- Add `FOREIGN KEY (scenario_station_id, contact_source) REFERENCES scenario_station(id, contact_source)`.
- Drop `NOT NULL` from `maximum_elevation_udeg` and `maximum_elevation_at`.
- Drop `geometric_peak_time_ck` and replace it with `geometric_elevation_source_ck`:
  - `ORBIT_DERIVED` requires both values present, `maximum_elevation_udeg BETWEEN 0 AND 90000000`,
    and `true_aos <= maximum_elevation_at AND maximum_elevation_at < true_los` — exactly the
    original v0.1 contract.
  - `SYNTHETIC_INJECTED` requires both values `NULL`.

Because the discriminator is carried by a composite FK chain
`geometric_access → scenario_station → scenario_revision`, an orbit-derived scenario cannot contain
an elevation-free access row and a synthetic scenario cannot contain an invented elevation. The
impossible combinations are rejected by the database, not merely by the service.

## Alternatives considered

| Alternative | Rejected because |
|---|---|
| Make the columns plainly nullable | Loses the AOS/LOS/max-elevation guarantee that §23.4 requires for real orbit contacts. Nothing would stop an orbit run from silently omitting the peak. |
| Insert a sentinel orbit revision and `maximum_elevation_udeg = 0` for synthetic rows | Fabricates data. `0 µdeg` is a *known* elevation under §23.3/§5.1; it is not `NOT_APPLICABLE`. Directly forbidden by the specification. |
| Keep synthetic runs out of PostgreSQL entirely | Blocks AC-P0-20 (persistence round trip) and Definition-of-Done item 2/3 forever, because every P0 fixture is synthetic. |
| A separate `synthetic_access` table parallel to `geometric_access` | Duplicates the result-root/`result_kind` contract of ADR-009 and forces every downstream reader (`modeled_contact`, metrics, comparison) to branch on two lineages for the same stage. |
| Enforce the rule only in the service layer | Contradicts ADR-015: this reduces to a row-local invariant, which ADR-015 says should be promoted to a database constraint. |

## Consequences

### Positive

- Synthetic injected contacts are storable without invented orbit or elevation values.
- `orbit_dependency = NOT_APPLICABLE` is representable as an explicit typed state, not as a null of
  unknown meaning.
- Orbit-derived rows keep the full v0.1 contract, enforced by CHECK rather than convention.
- Contact provenance (`SYN-CONTACT-01`) is a first-class column and enters the input snapshot hash
  through the resolved semantic input, so a synthetic run can never be mistaken for an orbit run.

### Negative

- Three tables gain a discriminator column and two composite unique keys.
- A future third contact source (for example an imported observed pass table) needs a new enum
  label and a new branch in `geometric_elevation_source_ck`.
- `downgrade` cannot be lossless once synthetic rows exist; see below.

## Migration and rollback

`0002_contact_source_provenance` applies `db/postgresql/schema_v0_2_contact_source.sql`. It is additive: no
existing column is dropped, no existing row is rewritten, and `0001` is untouched.

`downgrade` restores the v0.1 contract exactly. Restoring `NOT NULL` on the elevation columns and
on `orbit_revision_id` is only possible when no synthetic row exists, because the v0.1 schema has no
honest representation for those rows. The downgrade therefore counts the offending rows first and
aborts with an explicit message naming the tables and counts instead of inventing values or deleting
data. This is intended for disposable development databases; a populated deployment must migrate
data deliberately rather than roll the schema back.

## Revisit conditions

Revisit when a third contact source is introduced, or when `PB-GOLDEN-ORB-01` lands and the real
orbit path exercises `ORBIT_DERIVED` end to end. Neither changes the meaning of the two labels
defined here.
