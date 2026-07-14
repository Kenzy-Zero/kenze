# BACKLOG — feature roadmap (from external feedback, 2026-07-14)

Single source of truth for every feedback item. Nothing gets silently dropped:
each item is either shipped, a BIG BET, or explicitly WON'T-FIX with a reason.
Source: 4 stacked external critiques of the tool (siftq v0.2.0).

**2026-07-14 — RENAMED siftq -> `kenze` (one name for everything: pip / command / import)
and SHIPPED the whole v0.3–v0.6 plan in a single release, `kenze 0.3.0`.** All items
below marked [x] are built + tested (synthetic data + the real 54.6M-row / 2.5GB DU parquet)
+ ruff-clean + twine-check PASSED + tarball confidentiality-grep = 0 client tells.

**Release loop per wave:** build → dogfood on real data → bump version → `twine upload` (via `.pypirc`)
→ verify clean-venv install → tick the item here.

---

## v0.3 — "Credibility" — SHIPPED
- [x] **psutil → CORE dependency** (never-OOM sizing ships by default now)
- [x] **atomic writes** (temp file + rename; Ctrl+C leaves no partial output — verified)
- [x] **`rename`** columns (DuckDB `SELECT * RENAME`)
- [x] **`cast` / `--types`** schema overrides (verified: zip keeps its leading zero)
- [x] **`stats`** (DuckDB SUMMARIZE — min/max/nulls/approx-unique)
- [x] **`--memory-limit`** flag (pin the RAM budget)

## v0.4 — "Joins + Cloud + Safety" — SHIPPED
- [x] **`join`** (inner/left/right/full, USING key)
- [x] **cloud paths** S3 / GCS / Azure via httpfs — VERIFIED: `kenze profile s3://memob-business/...parquet`
      read a 54.6M-row parquet's schema+count in 5.7s using env keys (explicit secret from AWS_* env vars)
- [x] **`.gz`** streaming in/out (COMPRESSION on write, native on read)
- [x] **null handling** — `fillna` (COALESCE per column)
- [x] **pre-flight disk-space check** (upfront error instead of a mid-run crash; `--no-disk-check` to skip)
- [x] **progress indicator** (DuckDB native progress bar — verified on the 54.6M-row file)
- [x] **pivot / reshape** — dedicated `kenze pivot --on col --values col --agg sum --group cols` (verified)

## v0.5 — "Trust + Enterprise" — SHIPPED
- [x] **`eject` → SQL / Python** (recipe → raw DuckDB SQL or a Python snippet)
- [x] **`mask`** PII (`--method hash|redact|null`)
- [x] **`validate --schema`** (type + not-null checks; exit 1 on failure)
- [x] **`--skip-bad-lines`** (read_csv ignore_errors — verified drops the malformed row)
- [x] **stdin / stdout piping** (`-`; broken-pipe handled cleanly)
- [x] **native Python API** (`import kenze; kenze.sift(...)`, `kenze.sql(...)`, `kenze.profile(...)`)
- [x] **recipe templating** (`${VAR}` / `{{ VAR }}` via `--set` or env)
- [x] **hive partition output** (`kenze partition --by col` → `col=value/` via PARTITION_BY)
- [x] **`check`** — pre-flight file-integrity scan (readable rows + malformed count)
- [x] **`--log run.json`** (run manifest = inputs, rows, timing, steps)

## v0.6 — "Killer" — SHIPPED
- [x] **`diff`** two datasets (`--on key` → added / removed / changed; optional change file)
- [x] **window functions** — via the `sql` escape hatch (`kenze sql "... OVER (...)"` — verified
      running-total + lag() + rank(); this is the designed answer, no dedicated verb needed)
- [x] **`peek`** — zero-dep preview (rows + types + null counts). *Scrollable Textual TUI = a future
      optional `[tui]` extra by choice, to keep core one-dependency.*

## Feedback round 2 (2026-07-14) -> SHIPPED in kenze 0.4.0
External review triaged take / throw / thank. Built the "take" + "take-later" items:
- [x] **Polars / Arrow / pandas bridges** — `kenze.to_polars() / to_arrow() / to_df()` (optional extras `[polars]/[arrow]/[pandas]/[all]`).
- [x] **`--dry-run`** — print compiled query + output schema, no execution.
- [x] **`--errors PATH`** — quarantine malformed CSV rows (line/column diagnostics), good rows keep flowing.
- [x] **`kenze init`** — scaffold a starter recipe, pre-filled from a file's columns (defuses "DSL friction").
- [x] **`--append`** — append to existing csv/json output.
- [x] **Delta Lake / Iceberg read** — `--source-format delta|iceberg` (proven on a real Delta table).
- [x] **Trusted Publishing workflow** — `.github/workflows/publish.yml` (tokenless signed releases; Ken configures the PyPI trusted publisher once).
- [thank] `--memory-limit` already answers the "shared-node memory pitfall"; `eject` already answers "no lock-in / graduation path"; the "Medium Data" (Pandas -> kenze -> PySpark) positioning is a marketing gift.
- [throw] DuckDB-CLI overlap (marketing, not code) · one-man-maintenance risk (not codeable) · recipe-DSL fear (recipes are optional) · visual DAG (scope-creep) · cluster/horizontal-scale (by design).
- [later-heavy] full Delta/Iceberg **upsert/write** + real state management = only if demand shows; NOT in lean core.

## Feedback round 3 (2026-07-14, `feedback.txt`) -> triaged, v0.5 planned (NOT built yet)
- [ ] ⭐ **recipe assertions** — `assert: row_count > 0`, `assert_unique: id` inside `.dq` (data-quality tests before commit; the headline / differentiator).
- [ ] **`unpivot` / `melt`** — symmetric partner to `pivot` (DuckDB UNPIVOT; cheap).
- [ ] **multi-file glob schema unification** — `sales_*.csv` type-mismatch crash -> DuckDB `union_by_name` (or a `--unify` flag).
- [ ] **`--threads N`** — power-user override (answers "loss of fine-grained control" cheaply).
- [ ] **enrich `--log`** with input+output schema (light lineage; NOT full OpenLineage).
- [later-heavy] **Delta/Iceberg WRITE/upsert** — 2nd review to ask; DuckDB write support immature -> optional extension only if demand proven.
- [thank / ALREADY HAVE] progress bar (DuckDB native, live) · dependency-lock-in (solved by `kenze sql` escape hatch) · credential vaulting (standard AWS chain is correct) · zero-copy Arrow / projection-pushdown / ASCII-streaming (real strengths -> use in marketing) · "Memory-Infra-Syntax trilemma" (great marketing line).
- [throw] single-node/cluster · disk-spill-slowness · "deceptive CSV" (by design; doc tip = convert CSV->parquet for repeated heavy ops) · full OpenLineage/Marquez · "ejection overhead" (eject IS the feature) · 0-stars/SPOF/no-LTS (time+marketing, not codeable) · per-operator thread allocation (DuckDB-internal).

## 🚀 BIG BETS (own track, later)
- [ ] **single binary** (PyInstaller / `curl | sh`) — slips past "pip is blocked on prod servers"
- [ ] **WASM browser playground** (drag file → live recipe, 100% local) — best viral growth loop

## ⛔ SKIP for core (breaks the lean / safe / no-SQL story)
- inline Python UDFs — eval/safety risk; possible far-future opt-in
- embeddings / `embed`, semantic `chunk` for RAG — adds heavy deps → separate extension if ever

## 🧱 WON'T FIX — by design (stated in the README "Where it stops")
- horizontal scale / multi-machine · disk-spill speed · heavy data-lineage · deterministic SLA timing.
  Partial mitigations shipped: `--memory-limit` (predictable), disk pre-check, `--log` manifest.

---

## Command surface (kenze 0.3.0) — 26 commands
`profile · peek · stats · check · validate · keep · drop · rename · cast · fillna · mask ·
filter · dedup · sample · head · clip · convert · join · diff · split · partition · pivot · sql · eject · run · recipe`

Deps: `duckdb`, `psutil` (both core). One-name identity: `pip install kenze` → `kenze` → `import kenze`.
