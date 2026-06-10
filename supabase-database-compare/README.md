# Supabase Database Compare

Compare two Supabase projects side by side: **table schemas**, **Edge Functions**, **table data**, and **estimated last-write times**. Read-only — uses the Management API with your Personal Access Token (no database password required).

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
| `--output` | No | auto (text mode) | JSON report file path |
| `--format` | No | `text` | `text` or `json` |

\* Required unless the corresponding environment variable is set.

## What Gets Compared

### Tables (schema)

- Tables only in source / only in target / in both
- For shared tables: column name, type, nullable, and default differences

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

**Console (default):** human-readable summary with sections for tables, Edge Functions, data, and last-write estimates.

**JSON report:** saved automatically to `~/Documents/SupabaseTools/compare_<source>_vs_<target>_<timestamp>.json` when using text output. Override with `--output`.

**`--format json`:** prints the full report as JSON to stdout.

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
