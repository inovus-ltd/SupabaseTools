# Supabase Database Compare

Compare two Supabase projects side by side: **table schemas**, **Edge Functions**, **table data**, and **estimated last-write times**.

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
python supabase-database-compare.py compare --source-ref sourceref --target-ref targetref --token sbp_xxxxxxxxxxxx
```

By default this opens a beautiful HTML report in your browser with an overall similarity score (green → red).

With environment variables set (see [Environment Variables](../README.md#-environment-variables)):

```powershell
$env:SUPABASE_ACCESS_TOKEN = "sbp_xxxxxxxxxxxx"
$env:SUPABASE_SOURCE_PROJECT_REF = "sourceref"
$env:SUPABASE_TARGET_PROJECT_REF = "targetref"
supabase-database-compare compare
```

## Commands

### `list` — Inventory one project

Lists tables (in selected schemas) and Edge Functions.

```cmd
python supabase-database-compare.py list --project-ref abcdefghijklmnop --token sbp_xxxxxxxxxxxx
python supabase-database-compare.py list --project-ref abcdefghijklmnop --schemas public auth
```

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `--project-ref` | Yes* | `SUPABASE_PROJECT_REF` | Project reference ID |
| `--token` | Yes* | `SUPABASE_ACCESS_TOKEN` | Personal Access Token |
| `--schemas` | No | `public` | Schemas to include |

### `compare` — Compare two projects

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `--source-ref` | Yes* | `SUPABASE_SOURCE_PROJECT_REF` | Source project ref |
| `--target-ref` | Yes* | `SUPABASE_TARGET_PROJECT_REF` | Target project ref |
| `--token` | Yes* | `SUPABASE_ACCESS_TOKEN` | Personal Access Token |
| `--schemas` | No | `public` | Schemas to include |
| `--tables` | No | all shared tables | Limit data comparison to named tables |
| `--skip-data` | No | false | Schema + Edge Functions only |
| `--skip-edge-functions` | No | false | Skip Edge Function comparison |
| `--deep` | No | false | Row-level data diff (see below) |
| `--max-rows` | No | `1000` | Max rows per table in `--deep` mode |
| `--output` | No | auto (text/html) | Report file path (`.json` or `.html`) |
| `--format` | No | `html` | `html` (default), `text`, or `json` |
| `--quiet` | No | false | Suppress progress bar |
| `--no-open` | No | false | Don't auto-open HTML in browser |

\* Required unless the corresponding environment variable is set.

## What Gets Compared

### Tables (schema)

- Tables only in source / only in target / in both
- For shared tables: column-level differences — columns only on source, only on target, or changed (type/nullable/default)

### Edge Functions

- Slugs only on source / only on target / on both
- For shared slugs: metadata (`name`, `verify_jwt`, `entrypoint_path`, etc.) and SHA-256 hash of deployed source files

Does **not** compare Edge Function secrets.

### Table data (tiered)

**Default (summary):** row counts and MD5 checksum per shared table.

**`--deep`:** fetches up to `--max-rows` rows per table and reports rows only in source, only in target, and changed rows (by primary key). Tables larger than `--max-rows` are skipped unless you name them explicitly with `--tables`.

```cmd
python supabase-database-compare.py compare --source-ref sourceref --target-ref targetref --tables users orders --deep
```

### Last write estimate

Postgres does not store a true "last written" time per table. This tool reports a **best-effort estimate**:

1. `MAX(updated_at)` (or `modified_at`, `last_modified`, `created_at` if present)
2. If no timestamp column: `pg_stat_user_tables` counters (inserts/updates/deletes since stats reset — **not** an absolute last-write time)
3. If neither is available: `unavailable`

## Sync prediction

The HTML report includes a **Data Sync Prediction** section with an overall verdict:

| Verdict | Meaning |
|---------|---------|
| Sync Recommended | Schemas match; source is newer — typical snapshot refresh |
| Partial Sync Possible | Some tables syncable, some blocked |
| Sync Not Recommended | Schema mismatch or no syncable tables |
| Already In Sync | Data already matches |

Each table row shows a sync icon:

| Icon | Meaning |
|------|---------|
| ✓ green (90%+) | Sync should work — source newer than target |
| ✓ lime (75%) | Schema matches, data differs |
| ⚠ yellow | Caution — no PK, or target has newer writes |
| ✗ red | Cannot sync — schema differs or table missing |

Use [`supabase-database-sync`](../supabase-database-sync/README.md) to run `plan` then `sync`.

## Output

**HTML report (default):** saves to `~/Documents/SupabaseTools/compare_<source>_vs_<target>_<timestamp>.html` and **opens automatically in your browser**. Features:

- Overall **similarity score** (0–100) with rating: Identical → Mostly Similar → Partially Similar → Mostly Different → Not Similar
- Color-coded rows: **green** = match, **yellow** = partial difference, **red** = not similar
- Per-category meters for Table Schemas, Edge Functions, and Table Data
- Side-by-side Source vs Target with column-level schema diffs

Use `--no-open` to skip auto-opening the browser (e.g. in CI).

**Progress:** while comparing, a progress bar shows the current step. Use `--quiet` to disable.

**`--format text`:** console summary (also saves JSON alongside).

**`--format json`:** saves JSON and prints to stdout.

## Environment Variables

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
- Cross-account comparison works if your PAT has access to both projects
