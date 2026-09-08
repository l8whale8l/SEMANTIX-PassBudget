# SEMANTIX PassBudget — Frontend (M6 MVP, F0–F3)

React + TypeScript UI for the PassBudget downlink-budget workbench. The verified Python backend is
the single source of truth for every calculation; this app only edits inputs, calls the real API,
and displays and compares results. It performs **no** budget/scheduling math of its own
(ADR-0005).

## What works today (F0–F3)

You can, against the real backend:

1. Load the synthetic **PB-GOLDEN-ORB-01** preset (synthetic reference orbit + two synthetic ground
   stations + three synthetic model outputs — an assumption-based estimate, not KMU performance).
2. Edit the analysis window, orbit (two-body **or** TLE), ground-station coordinates / minimum
   elevation / preference, and per-station link assumptions — in **friendly units** (degrees,
   metres, Mbps, percent) with an *advanced (exact)* panel for the raw integer/rational values.
   Activate/deactivate stations without losing the inactive drafts.
3. Switch between **QUEUE_AWARE** and **NETWORK_ONLY**. NETWORK_ONLY runs exclude payload/policy/
   storage inputs (per the domain contract) while preserving your drafts, and the execution strategy
   is shown fixed to EXACT there — the screen never differs from what is sent.
4. Build a **model-output cart** (F2): paste text (measured as raw UTF-8 bytes) or pick a file
   (measured by size only — contents are never read or uploaded), then edit each output's service
   class, mission priority, queue sequence, segmentation (ATOMIC/FIXED_CHUNK), and sizes. Re-run to
   see planned completion / partial transfer / deferral, per-output reason codes, and allocation
   totals.
5. Run with an explicit **execution strategy** (`EXACT_GLOBAL` / `BOUNDED_APPROXIMATE` — no
   automatic approximation fallback), and read the budget summary, pass table + detail, and
   assumption/limit warnings. A kept result always shows *its own* submitted conditions.
6. See a **"input changed — recompute needed"** stale marker when inputs diverge from the last
   result, with the prior run id preserved. Out-of-order/superseded responses never overwrite a
   newer result; an error keeps the last good result visible with its own context.

7. **Save and load scenarios on the server** (F3): "Save" creates a scenario → publishes → snapshots
   it; the browser keeps only the scenario id in `localStorage` (never the content). "Load" fetches
   the saved content back from the server (`GET /api/v1/scenario-revisions/{id}/content`, added in
   F3) and restores the fields; re-running reproduces the result deterministically. Editing a loaded
   scenario saves a new revision; "Clone" makes an independent copy and leaves the original published
   revision untouched.
8. **Compare two runs** (F3): pick a baseline and a candidate from this session's run history and get
   the real `POST /api/v1/comparisons` deltas; incomparable metrics hide their delta and show the
   reason, and a differing optimization grade (EXACT vs APPROXIMATE) is flagged.
9. **Export** (F3): view the plain-text report (`GET /api/v1/runs/{id}/report`, with the orbit-
   dependency line now correct) and download it or the result JSON.

Not built yet: daily aggregation (F4), globe/timeline (F5), release hardening (F6). The preset and
its outputs are still seeded from a bundled copy of the public fixture (the preset-list body,
FE-GAP-02 scenario listing, is not yet available); the model-output catalog is a this-session draft
catalog. **Scenario persistence** on the default **SQLite tier survives a backend restart:** the
catalog (scenarios/revisions/snapshots) is stored in the same local database file as run results
(schema v2, `SqliteCatalogRepository`), so a saved scenario re-loads and re-runs to the identical
result-content hash after the process is stopped and started. The **in-memory tier** (used by the
isolated E2E default) stays volatile — a restart there clears the catalog, and the UI then explains
a saved bookmark's 404 as a possible restart and offers to remove the stale pointer. The PostgreSQL
catalog is not implemented yet (a future work package; the same port and tests apply).

## Prerequisites

- **Node.js 22.13+** (verified on v22.13.1) with the toolchain pinned in `package-lock.json`.
  Install with `npm ci` for an exact, lockfile-based install.
- The backend running locally. From the repository root, with the project's Python venv:

```bash
uvicorn semantix_passbudget.interfaces.api.app:app --host 127.0.0.1 --port 8000
```

For an **isolated** backend that never touches your real local database, force the in-memory tier:

```bash
PASSBUDGET_PERSISTENCE=memory uvicorn semantix_passbudget.interfaces.api.app:app --host 127.0.0.1 --port 8000
```

(SQLite is the backend default and is also fine; the in-memory tier just guarantees no on-disk user
DB is created or modified — use it for throwaway/E2E runs.)

## Run

```bash
cd frontend
npm install
npm run dev
```

Open the printed URL (default <http://localhost:5173>). The Vite dev server proxies `/api` and
`/health` to `http://127.0.0.1:8000` (same-origin; no CORS is enabled on the server, by design). To
point at a different backend origin, set `PASSBUDGET_API_ORIGIN` before `npm run dev`.

## Scripts

| Command | What it does |
|---|---|
| `npm run dev` | Vite dev server with the API proxy. |
| `npm run build` | Type-check (`tsc -b`) then production build to `dist/`. |
| `npm run preview` | Serve the built `dist/`. |
| `npm run typecheck` | Type-check only. |
| `npm run lint` | oxlint. |
| `npm test` | Vitest unit/contract suite (jsdom). |
| `npm run test:watch` | Vitest watch mode. |

Unit/contract tests use controlled mocks and the bundled fixture; the golden budget numbers are
regression oracles (see `src/shared/format/units.test.ts`, `src/features/scenario/draft.test.ts`).
The real-API golden run (526.56 MB / 7 contacts) is verified by driving this UI against a running
backend, not by mock alone.

## Toolchain choices (F0)

| Tool | Why |
|---|---|
| **Vite** + `@vitejs/plugin-react` | Standard React/TS dev server; built-in dev proxy for the same-origin backend. |
| **TypeScript** (strict) | Contract fidelity to the strict backend DTOs. Pinned to a 5.x line; see the known issue below. |
| **Vitest** + Testing Library + jsdom | Shares Vite's transform; fast unit/contract tests. |
| **oxlint** | Fast linter shipped by the Vite React-TS template; zero-config. |

No state-management library, design system, or Storybook is used — React built-ins cover F0–F1
(FRONTEND_IMPLEMENTATION_SPEC §6). Exact versions are pinned in `package-lock.json`.

## Precision & safety notes

- Byte counts, microseconds and micro-degrees are edited as **strings** and converted to exact
  integers on submit. A non-integer or out-of-safe-range value is **rejected**, never silently
  rounded (`src/shared/format/json.ts`, `units.ts`). Display rounding (e.g. `526.56 MB`) is kept
  separate from the exact byte comparison.
- `MB` means 1,000,000 bytes (decimal), never MiB. UTC microseconds are formatted without
  round-tripping through `Date` (which would drop sub-millisecond digits).
- Model-output text/files are **not** uploaded: F0–F1 sends no payload bodies. UI-only fields
  (friendly scenario name, per-station active flag) are never placed into the strict DTO.
- The bundled `PB-GOLDEN-ORB-01.json` is a public, TLE-free synthetic fixture. Do not add real
  private TLEs, credentials, or `.env` secrets to the bundle.

## Known environment issue — non-ASCII install path

On some Windows + Node builds, native-addon tools (esbuild/rollup, and even loading `typescript`)
crash with an access violation when the project path contains **non-ASCII characters** (this repo
lives under `다학제간 캡스톤`). If `npm run dev`/`build`/`test` exits with code `-1073741819`, run
the toolchain from an ASCII path, e.g. copy `frontend/` to `C:\pbwork` and run there, or use a
directory junction with `NODE_OPTIONS=--preserve-symlinks` for the pure-JS tools. Real Node on a
normal ASCII path is unaffected. The application code itself is path-agnostic; this only affects the
build/test tooling on this machine.
