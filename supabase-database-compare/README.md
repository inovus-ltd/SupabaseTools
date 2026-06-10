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
| `--format` | No | `text` | `text`, `json`, or `html` |
| `--quiet` | No | false | Suppress progress bar |

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

## Output

**Console (default):** human-readable summary. SOURCE and TARGET project refs are labeled on every section. Tables with schema differences show **column-level detail** (not just table names).

**Progress:** while comparing, a progress bar shows the current step (schema columns per table, Edge Functions, data checksums, last-write estimates). Use `--quiet` to disable.

**JSON report:** saved automatically to `~/Documents/SupabaseTools/compare_<source>_vs_<target>_<timestamp>.json` when using `--format text`. Override with `--output`.

**HTML report (recommended for readability):**

```cmd
python supabase-database-compare.py compare --source-ref sourceref --target-ref targetref --format html
```

Saves a self-contained HTML file with color-coded **SOURCE** (blue) and **TARGET** (green) columns, summary cards, schema diff tables, and side-by-side data/last-write comparisons. Open in any browser.

**`--format json`:** prints the full report as JSON to stdout (progress still shown on stderr's terminal).

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
