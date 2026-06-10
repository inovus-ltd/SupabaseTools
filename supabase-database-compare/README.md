# Supabase Database Compare

Compare two Supabase projects side by side: **table schemas**, **Edge Functions**, **table data**, **estimated last-write times**, and **data sync predictions**.

Use this before syncing a stale snapshot, validating a clone, or checking whether staging matches production.

## 100% non-destructive

This tool is **read-only**. It cannot modify, delete, or deploy anything.

- All database inspection uses the Management API **`database/query/read-only`** endpoint — write SQL is not available to this tool
- Edge Function inspection uses **GET** requests only (list metadata and download source for comparison)
- Reports are saved **locally** on your machine; nothing is written back to Supabase

You can run `compare` against production without risk of changing data, schema, or functions.

## Prerequisites

- Python 3.8+ (or the standalone executable from a release)
- `requests` — `pip install requests`
- **Supabase Personal Access Token** — [dashboard/account/tokens](https://supabase.com/dashboard/account/tokens)
- **Two project reference IDs** — the alphanumeric IDs in each project's dashboard URL

## Quick Start

```cmd
supabase-database-compare compare --source-ref sourceref --target-ref targetref --token sbp_xxxxxxxxxxxx
```

By default this saves an HTML report and **opens it in your browser** with an overall similarity score (green → red) and sync predictions.

With environment variables (see [Environment Variables](../README.md#-environment-variables)):

```powershell
$env:SUPABASE_ACCESS_TOKEN = "sbp_xxxxxxxxxxxx"
$env:SUPABASE_SOURCE_PROJECT_REF = "sourceref"
$env:SUPABASE_TARGET_PROJECT_REF = "targetref"
supabase-database-compare compare
```

**Typical next step:** if sync looks safe, run [`supabase-database-sync plan`](../supabase-database-sync/README.md) then `sync`.

## When to use this tool

| Scenario | What compare tells you |
|----------|------------------------|
| **Stale snapshot** | Target was restored from backup; source kept receiving writes. Compare shows which tables drifted and whether source is newer. |
| **After cloning** | Dashboard restore copied schema + data at a point in time. Compare finds drift vs the live source and missing Edge Functions. |
| **Staging vs production** | Schema mismatches, row count differences, and function deploy drift before a release. |
| **Pre-sync check** | Sync prediction icons and confidence scores — run before `supabase-database-sync`. |

## Commands

### `list` — Inventory one project

Lists tables (in selected schemas) and Edge Functions.

```cmd
supabase-database-compare list --project-ref abcdefghijklmnop --token sbp_xxxxxxxxxxxx
supabase-database-compare list --project-ref abcdefghijklmnop --schemas public auth
```

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `--project-ref` | Yes* | `SUPABASE_PROJECT_REF` | Project reference ID |
| `--token` | Yes* | `SUPABASE_ACCESS_TOKEN` | Personal Access Token |
| `--schemas` | No | `public` | Schemas to include |

### `compare` — Compare two projects

```cmd
supabase-database-compare compare --source-ref sourceref --target-ref targetref --token sbp_xxx
supabase-database-compare compare --format json --no-open
supabase-database-compare compare --skip-data
supabase-database-compare compare --tables users orders --deep --max-rows 5000
```

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `--source-ref` | Yes* | `SUPABASE_SOURCE_PROJECT_REF` | Source (reference / live) project |
| `--target-ref` | Yes* | `SUPABASE_TARGET_PROJECT_REF` | Target (snapshot / clone) project |
| `--token` | Yes* | `SUPABASE_ACCESS_TOKEN` | Personal Access Token |
| `--schemas` | No | `public` | Schemas to include |
| `--tables` | No | all shared tables | Limit data comparison to named tables |
| `--skip-data` | No | false | Schema + Edge Functions only (faster) |
| `--skip-edge-functions` | No | false | Skip Edge Function comparison |
| `--deep` | No | false | Row-level data diff (see below) |
| `--max-rows` | No | `1000` | Max rows per table in `--deep` mode |
| `--output` | No | auto | Report file path (`.json` or `.html`) |
| `--format` | No | `html` | `html` (default), `text`, or `json` |
| `--quiet` | No | false | Suppress progress bar |
| `--no-open` | No | false | Don't auto-open HTML in browser |

\* Required unless the corresponding environment variable is set.

## What gets compared

### Table schemas

- Tables only in source / only in target / in both
- For shared tables: column-level differences — columns only on source, only on target, or changed (type / nullable / default)
- Primary key columns per table (stored in JSON for the sync tool)

### Edge Functions

- Slugs only on source / only in target / on both
- For shared slugs: metadata (`name`, `verify_jwt`, `entrypoint_path`, etc.) and SHA-256 hash of deployed source files

Does **not** compare Edge Function secrets. The HTML report notes: use `supabase-functions-backup restore` for function sync.

### Table data (tiered)

**Default (summary):** row counts and MD5 checksum per shared table. Fast and suitable for most drift checks.

**`--deep`:** fetches up to `--max-rows` rows per table and reports rows only in source, only in target, and changed rows (by primary key). Tables larger than `--max-rows` are skipped unless you name them explicitly with `--tables`.

```cmd
supabase-database-compare compare --source-ref sourceref --target-ref targetref --tables chat_messages --deep
```

### Last-write estimate

Postgres does not store a true "last written" time per table. This tool reports a **best-effort estimate**:

1. `MAX(updated_at)` (or `modified_at`, `last_modified`, `created_at` if present)
2. If no timestamp column: `pg_stat_user_tables` counters (inserts/updates/deletes since stats reset — **not** an absolute last-write time)
3. If neither is available: `unavailable`

When source `last_write` is newer than target, that strongly suggests a **snapshot refresh** pattern — the usual case for `supabase-database-sync`.

## Sync prediction

The HTML report includes a **Data Sync Prediction** hero card with an overall verdict and confidence percentage. Per-table icons appear on data and last-write rows.

### Overall verdicts

| Verdict | Meaning |
|---------|---------|
| **Sync Recommended** | Schemas match; source is newer — typical snapshot refresh |
| **Partial Sync Possible** | Some tables syncable, some blocked |
| **Sync Not Recommended** | Schema mismatch or no syncable tables |
| **Already In Sync** | Data already matches |

### Per-table icons

| Icon | Confidence | Meaning |
|------|------------|---------|
| ✓ green | 90%+ | Sync should work — source newer than target (snapshot pattern) |
| ✓ lime | 75% | Schema matches, data differs, timestamps unclear |
| ✓ green | 95% | Data already matches (noop sync) |
| ⚠ yellow | 40–55% | Caution — no PK (risky), or target has newer writes |
| ✗ red | 0% | Cannot sync — schema differs or table missing on one side |

Hover the icon for the reason text (e.g. "Source newer than target — snapshot pattern").

### Assessment logic (summary)

| Condition | Syncable | Confidence |
|-----------|----------|------------|
| Table only on source or target | No | 0% |
| Schema differs | No | 0% |
| Schema identical, no PK | Yes (risky) | 40% |
| Schema identical, data matches | Yes (noop) | 95% |
| Schema identical, source newer | Yes | 90% |
| Schema identical, target newer | Yes | 55% |
| Schema identical, data differs, timestamps unknown | Yes | 75% |

Use [`supabase-database-sync`](../supabase-database-sync/README.md) to run `plan` then `sync`. Pass the JSON report with `--from-report` to pre-filter syncable tables.

## Output

### HTML report (default)

Saves to:

```
~/Documents/SupabaseTools/compare_<source>_vs_<target>_<timestamp>.html
```

On Windows: `C:\Users\<you>\Documents\SupabaseTools\...`

Opens automatically in your browser unless `--no-open` is set.

**Report sections:**

- **Similarity score** (0–100) with rating: Identical → Mostly Similar → Partially Similar → Mostly Different → Not Similar
- **Data Sync Prediction** — overall verdict + confidence
- **Table Schemas** — column-level diffs, color-coded rows
- **Edge Functions** — slug/metadata/source hash comparison
- **Table Data** — row counts, checksums, sync icons
- **Last Write** — per-table estimates with sync icons

Use `--no-open` in CI or when you only need the file path.

### JSON report

```cmd
supabase-database-compare compare --format json --output report.json
```

JSON includes `primary_keys`, `sync_assessment`, and full comparison data. Consumed by:

```cmd
supabase-database-sync plan --from-report report.json
supabase-database-sync sync --from-report report.json --dry-run
```

If `--from-report` is a filename only (no path), the sync tool also looks in `~/Documents/SupabaseTools/`.

### Text report

```cmd
supabase-database-compare compare --format text
```

Prints a console summary and saves JSON alongside.

### Progress

While comparing, a progress bar shows the current step. Use `--quiet` to disable.

## Recommended workflow with sync

```
1. supabase-database-compare compare     → HTML + sync predictions
2. supabase-database-sync plan           → CLI preview (no writes)
3. supabase-database-sync sync --dry-run → preview writes, no confirmation
4. supabase-database-sync sync           → execute (requires YES SYNC)
```

For a cautious first run, sync one table:

```cmd
supabase-database-sync sync --tables connection_requests --dry-run
supabase-database-sync sync --tables connection_requests
```

## Environment variables

| Variable | Equivalent flag | Description |
|----------|----------------|-------------|
| `SUPABASE_ACCESS_TOKEN` | `--token` | Personal Access Token |
| `SUPABASE_PROJECT_REF` | `--project-ref` | Project ref (`list`) |
| `SUPABASE_SOURCE_PROJECT_REF` | `--source-ref` | Source project ref (`compare`) |
| `SUPABASE_TARGET_PROJECT_REF` | `--target-ref` | Target project ref (`compare`) |

Full setup guide: [Environment Variables](../README.md#-environment-variables)

## Limitations

- Uses read-only Management API SQL — large tables may be slow or hit rate limits (~120 requests/min per project)
- Data checksums are best-effort; tables without primary keys use weaker ordering
- Last-write times are estimates, not authoritative
- Sync prediction is advisory — always run `plan` before `sync`
- Cross-account comparison works if your PAT has access to both projects
- Does not compare Storage, Auth, secrets, or RLS policies
