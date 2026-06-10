# Supabase Database Sync

Sync **table data** from a source Supabase project to a target project.

Built for the common case where your **target is a stale snapshot** (restored backup or clone) and the **source kept receiving writes**. Run [`supabase-database-compare`](../supabase-database-compare/README.md) first to inspect drift and read sync predictions.

---

## ⚠️ WARNING — This tool modifies the TARGET

| | Source | Target |
|---|--------|--------|
| **Access** | Read-only | **Read + write** |
| **API** | `database/query/read-only` | `database/query` |

- **Only the TARGET database is modified.** Source is never written to.
- **`mirror` mode is destructive** — deletes rows on target that are not in source.
- **Not a schema migration tool** — table schemas must already match.
- **Does not sync** Edge Functions, Storage, Auth, secrets, or RLS policies.

---

## Prerequisites

1. **Compare first** — `supabase-database-compare compare` and review sync predictions in the HTML report
2. **Identical schemas** — column names, types, nullable, and defaults must match on both sides
3. **Primary keys required** — every synced table must have a PK (both `upsert` and `mirror`)
4. **Personal Access Token** — [dashboard/account/tokens](https://supabase.com/dashboard/account/tokens)

## Quick Start

```powershell
$env:SUPABASE_ACCESS_TOKEN = "sbp_..."
$env:SUPABASE_SOURCE_PROJECT_REF = "sourceref"
$env:SUPABASE_TARGET_PROJECT_REF = "targetref"

supabase-database-compare compare
supabase-database-sync plan
supabase-database-sync sync --dry-run
supabase-database-sync sync
```

## Recommended workflow

```
compare  →  plan  →  sync --dry-run  →  sync
```

| Step | Command | Writes? | Confirmation? |
|------|---------|---------|-----------------|
| 1. Inspect | `supabase-database-compare compare` | No | — |
| 2. Preview | `supabase-database-sync plan` | No | — |
| 3. Dry run | `supabase-database-sync sync --dry-run` | No | — |
| 4. Execute | `supabase-database-sync sync` | **Yes (target)** | Target ref + `YES SYNC` |

Use a compare JSON report to skip tables marked not syncable:

```cmd
supabase-database-sync plan --from-report compare_sourceref_vs_targetref_20260101_120000.json
supabase-database-sync sync --from-report compare_sourceref_vs_targetref_20260101_120000.json
```

Reports live in `~/Documents/SupabaseTools/` by default. A filename without a path is resolved there automatically.

## Commands

### `plan` — Full dry-run preview

Alias for `sync --dry-run`. Runs the complete preview pipeline: validation, upsert counts, and mirror delete counts. **Never writes** and never asks for confirmation.

```cmd
supabase-database-sync plan --source-ref sourceref --target-ref targetref --token sbp_xxx
supabase-database-sync plan --mode mirror --tables users chat_messages
supabase-database-sync plan --from-report compare_sourceref_vs_targetref_20260101.json
```

### `sync` — Execute sync

```cmd
supabase-database-sync sync --source-ref sourceref --target-ref targetref --token sbp_xxx
supabase-database-sync sync --mode mirror --batch-size 100
supabase-database-sync sync --tables connection_requests --dry-run
```

### Parameters (both commands)

| Parameter | Default | Description |
|-----------|---------|-------------|
| `--source-ref` | `SUPABASE_SOURCE_PROJECT_REF` | Source project (read-only) |
| `--target-ref` | `SUPABASE_TARGET_PROJECT_REF` | Target project (**modified**) |
| `--token` | `SUPABASE_ACCESS_TOKEN` | Personal Access Token |
| `--schemas` | `public` | Schemas to include |
| `--tables` | all shared | Limit to named tables (`users` or `public.users`) |
| `--from-report` | — | Compare JSON — skip tables with `syncable: false` |
| `--mode` | `upsert` | `upsert` or `mirror` |
| `--batch-size` | `200` | Rows per INSERT batch |

**`sync` only:**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `--dry-run` | false | **Full dry-run:** validate, simulate upserts and mirror deletes, no writes, no confirmation |
| `--quiet` | false | Suppress progress bar |

`plan` always runs with `--dry-run` enabled (same code path as `sync --dry-run`).

## Sync modes

### `upsert` (default)

1. Read all rows from **source**
2. `INSERT ... ON CONFLICT (pk) DO UPDATE` into **target**
3. Rows that exist only on target are **left unchanged**

Use when you want to refresh data from source without removing target-only rows.

### `mirror`

1. Same upsert pass as above (parents before children, FK order)
2. Delete target rows whose primary key is **not** in source (children before parents)

Use when target should be an **exact data mirror** of source for each synced table.

```cmd
REM Safe preview first
supabase-database-sync sync --mode mirror --dry-run

REM Then execute — deletes are real
supabase-database-sync sync --mode mirror
```

## Confirmation (sync only)

After pre-flight validation, `sync` requires **both** confirmations (skipped with `--dry-run`):

```
Type the TARGET project ref to confirm: pmjewytsschcvhisiehz
Type YES SYNC to confirm: YES SYNC
```

Any mismatch aborts with **no changes**.

## Pre-sync validation

Before any write, each table is re-checked on both projects:

| Check | On failure |
|-------|------------|
| Table exists on source and target | Skipped with error |
| Schema identical (columns, types, nullable, default) | Skipped with error |
| Primary key exists | Skipped — sync blocked |
| `--from-report` and `syncable: false` | Skipped |

Tables that fail validation are listed and skipped; other tables continue.

## How sync works

1. **Discover** tables in selected schemas (default `public`)
2. **Topological sort** by foreign-key dependencies — parents upserted before children
3. **Per table (upsert pass):**
   - Batch-read all rows from source (`SELECT * ... LIMIT/OFFSET`)
   - Batch-upsert into target via `INSERT ... ON CONFLICT DO UPDATE`
4. **`mirror` only (delete pass):**
   - Reverse FK order (children before parents)
   - Delete target rows whose PK is not in source (batched for single-column PKs)
5. **Progress bar** and per-table summary: rows read, upserted, deleted, skipped, errors

## Example output

**`plan`:**

```
 Sync plan
   SOURCE (read-only): eccbosteyojazrabedly
   TARGET (will be modified): pmjewytsschcvhisiehz
   Mode: upsert
   Upsert: insert/update from source; extra target rows kept

  Tables to sync (8):

    OK  public.chat_messages — 1240 row(s) from source, PK: id
    OK  public.connection_requests — 42 row(s) from source, PK: id
    SKIP public.legacy_table — No primary key — sync blocked

  Summary: 7 table(s), ~3500 row(s) to upsert

  Run sync to apply (requires confirmation).
```

**`sync`:**

```
  Pre-flight validation:

    OK  public.chat_messages
    OK  public.connection_requests

  WARNING: This will MODIFY data on the TARGET project.
  TARGET: pmjewytsschcvhisiehz

  Type the TARGET project ref to confirm: pmjewytsschcvhisiehz
  Type YES SYNC to confirm: YES SYNC

  [##############################] 7/7 (100%) Sync complete

  Results:

    public.connection_requests: read 42, upserted 42, deleted 0
    public.chat_messages: read 1240, upserted 1240, deleted 0
```

## What is NOT synced

| Not synced | Use instead |
|------------|-------------|
| Edge Functions | `supabase-functions-backup` backup + restore |
| Storage buckets & files | `supabase-storage-copy` |
| Auth configuration | `supabase-auth-copy` |
| Edge Function secrets | `supabase-secrets-manager` |
| Schema / migrations | Supabase migrations or dashboard |
| RLS policies | Migrations or manual setup |

## Environment variables

| Variable | Flag |
|----------|------|
| `SUPABASE_ACCESS_TOKEN` | `--token` |
| `SUPABASE_SOURCE_PROJECT_REF` | `--source-ref` |
| `SUPABASE_TARGET_PROJECT_REF` | `--target-ref` |

Full setup guide: [Environment Variables](../README.md#-environment-variables)

## Limitations

- Large tables via Management API can be slow (rate limits, batching) — use `--batch-size` and `--tables` for incremental runs
- Tables without primary keys cannot sync — blocked at validation
- Circular FK dependencies may require manual `--tables` ordering
- Generated / identity columns may need manual handling if upsert conflicts arise
- Mirror mode with composite primary keys deletes orphans row-by-row (slower but correct)
- Compare + sync cover **table data only** — always run the other SupabaseTools for functions, storage, auth, and secrets after a clone

## Safety checklist

- [ ] Ran `supabase-database-compare compare` and reviewed sync predictions
- [ ] Ran `plan` and checked row counts
- [ ] Ran `sync --dry-run` before first real sync
- [ ] Confirmed **target** ref is the project you intend to modify
- [ ] Backed up or can re-restore target if using `mirror` mode
- [ ] Synced Edge Functions / storage / auth separately if needed
