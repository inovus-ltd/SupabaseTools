# Supabase Database Sync

Sync **table data** from a source Supabase project to a target project. For when your target is a stale snapshot and the source kept receiving writes.

**WARNING: This tool MODIFIES the TARGET database.** Source is read-only.

## Prerequisites

- Run [`supabase-database-compare`](../supabase-database-compare/README.md) first — check the HTML sync prediction
- Identical table schemas on both projects (column names, types)
- Primary keys on every table to sync
- Personal Access Token from [dashboard/account/tokens](https://supabase.com/dashboard/account/tokens)

Does **not** sync Edge Functions (use `supabase-functions-backup`), Storage, Auth, or secrets.

## Recommended workflow

```powershell
$env:SUPABASE_ACCESS_TOKEN = "sbp_..."
$env:SUPABASE_SOURCE_PROJECT_REF = "sourceref"
$env:SUPABASE_TARGET_PROJECT_REF = "targetref"

# 1. Compare (opens HTML with sync predictions)
supabase-database-compare compare

# 2. Preview what sync would do
supabase-database-sync plan

# 3. Execute with confirmation
supabase-database-sync sync
```

## Commands

### `plan` — Preview sync (no changes)

```cmd
supabase-database-sync plan --source-ref sourceref --target-ref targetref --token sbp_xxx
```

### `sync` — Execute sync

```cmd
supabase-database-sync sync --source-ref sourceref --target-ref targetref --token sbp_xxx
```

Requires typing the **target project ref** and **`YES SYNC`** to confirm.

| Parameter | Default | Description |
|-----------|---------|-------------|
| `--source-ref` | env | Source project (read-only) |
| `--target-ref` | env | Target project (modified) |
| `--token` | env | Personal Access Token |
| `--mode upsert` | upsert | Insert/update by PK; keep extra target rows |
| `--mode mirror` | | Upsert + delete target rows not in source |
| `--tables` | all syncable | Limit to named tables |
| `--from-report` | | Compare JSON report path — filter to syncable tables |
| `--batch-size` | 200 | Rows per INSERT batch |
| `--dry-run` | false | Preview without writing (`sync` only) |
| `--quiet` | false | Suppress progress bar |

## Sync modes

**`upsert` (default):** Copies all rows from source. Updates existing rows on target (by primary key). Leaves rows that exist only on target untouched.

**`mirror`:** Same as upsert, then deletes target rows whose primary key is not present in source. Makes target data an exact mirror of source for each synced table.

## What blocks sync

- Table missing on source or target
- Schema column mismatch
- No primary key
- Compare report marks table as not syncable (with `--from-report`)

## Environment variables

| Variable | Flag |
|----------|------|
| `SUPABASE_ACCESS_TOKEN` | `--token` |
| `SUPABASE_SOURCE_PROJECT_REF` | `--source-ref` |
| `SUPABASE_TARGET_PROJECT_REF` | `--target-ref` |
