# 🔄 Supabase Edge Functions Backup & Restore

A Python CLI tool that backs up all Edge Functions from a Supabase project and can restore them to the same or a different project. Useful for migrating between environments, disaster recovery, or cloning a project's serverless layer.

## ⚙️ How It Works

The tool talks to the [Supabase Management API](https://supabase.com/docs/reference/api) — the same API that powers the CLI and Dashboard. For each Edge Function it:

1. **🗄️ Backup** — Downloads the function metadata (name, slug, JWT verification setting, entrypoint, import map) and the compiled source bundle (eszip format), saving everything into a structured local directory.
2. **📤 Restore** — Reads the backup directory and uses the `/functions/deploy` endpoint to push each function to the target project. If a function already exists it gets updated; if not it gets created.

## ✅ Prerequisites

- 🐍 **Python 3.8+**
- 🌐 **`requests` library** — `pip install requests`
- 🔑 **Supabase Personal Access Token (PAT)** — see [🔑 How to Get Your Token](../README.md#-how-to-get-your-token) in the root README
- 🆔 **Supabase Project Reference ID** — the alphanumeric string in your project dashboard URL:
  `https://supabase.com/dashboard/project/abcdefghijklmnop` → ref is `abcdefghijklmnop`
  Also visible under *Project Settings → General*.

## 🚀 Quick Start

If your credentials are set as environment variables (see [🌍 Environment Variables](#-environment-variables)), a backup is just:

```cmd
python supabase-functions-backup.py backup --project-ref abcdefghijklmnop
```

Or passing the token explicitly:

```cmd
python supabase-functions-backup.py backup --project-ref abcdefghijklmnop --token sbp_xxxxxxxxxxxxxxxxxxxx
```

**Example output:**

```
 Backing up Edge Functions for project: abcdefghijklmnop
   Destination: C:\Projects\supabase-functions-backup\edge_functions_backup_abcdefghijklmnop

  Found 3 function(s):

  -> chat-simulation (v5)
     metadata saved  (413 bytes)
     source saved    (18,577 bytes)
  -> metrics-proxy (v8)
     metadata saved  (509 bytes)
     source saved    (7,039 bytes)
  -> assign-proctor (v4)
     metadata saved  (497 bytes)
     source saved    (7,496,348 bytes)

  Backup complete. 3 function(s) saved.
  Manifest: C:\Projects\supabase-functions-backup\edge_functions_backup_abcdefghijklmnop\manifest.json
```

## 📋 Commands & Parameters

### `backup` — Download all Edge Functions to disk

```cmd
python supabase-functions-backup.py backup [options]
```

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `--project-ref` | ✅ Yes* | `SUPABASE_PROJECT_REF` env var | Your Supabase project reference ID |
| `--token` | ✅ Yes* | `SUPABASE_ACCESS_TOKEN` env var | Your Supabase Personal Access Token |
| `--dir` | No | `edge_functions_backup_<project-ref>` | Path to the directory to save the backup into. Defaults to a folder named after your project ref so each project gets its own isolated backup. Created automatically if it doesn't exist. Accepts relative or absolute paths. |

```cmd
REM Relative path
python supabase-functions-backup.py backup --project-ref abcdefghijklmnop --token sbp_xxxxxxxxxxxxxxxxxxxx --dir .\my-backup

REM Absolute path
python supabase-functions-backup.py backup --project-ref abcdefghijklmnop --token sbp_xxxxxxxxxxxxxxxxxxxx --dir C:\Backups\supabase
```

---

### `restore` — Deploy functions from a backup to a project

```cmd
python supabase-functions-backup.py restore [options]
```

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `--project-ref` | ✅ Yes* | `SUPABASE_PROJECT_REF` env var | Target project to restore functions into |
| `--token` | ✅ Yes* | `SUPABASE_ACCESS_TOKEN` env var | Your Supabase Personal Access Token |
| `--dir` | No | `edge_functions_backup_<project-ref>` | Path to the directory containing the backup to restore from. Defaults to the same project-scoped folder that `backup` writes to, so `restore` will automatically read from the right place. Accepts relative or absolute paths. |
| `--slugs` | No | *(all functions)* | Space-separated list of function slugs to restore — omit to restore everything |
| `--dry-run` | No | `false` | Preview what would be deployed without making any changes |

**Restoring to the same project** (default `--dir` works automatically):

```cmd
python supabase-functions-backup.py restore --project-ref abcdefghijklmnop
```

**Restoring to a DIFFERENT project** — you must use `--dir` to point at the source project's backup folder, since the default folder is named after the *target* project ref, not the source:

```cmd
python supabase-functions-backup.py restore --project-ref newprojectref --dir edge_functions_backup_abcdefghijklmnop
```

> 💡 If you forget `--dir`, the script will print the available backup folders and their source project refs to help you find the right one.

```cmd
REM Restore only specific functions
python supabase-functions-backup.py restore --project-ref newprojectref --dir edge_functions_backup_abcdefghijklmnop --slugs send-email process-webhook

REM Preview without deploying anything
python supabase-functions-backup.py restore --project-ref newprojectref --dir edge_functions_backup_abcdefghijklmnop --dry-run
```

---

### `list` — List all Edge Functions on a project

```cmd
python supabase-functions-backup.py list [options]
```

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `--project-ref` | ✅ Yes* | `SUPABASE_PROJECT_REF` env var | Project to list functions from |
| `--token` | ✅ Yes* | `SUPABASE_ACCESS_TOKEN` env var | Your Supabase Personal Access Token |

```cmd
python supabase-functions-backup.py list --project-ref abcdefghijklmnop --token sbp_xxxxxxxxxxxxxxxxxxxx
```

> \* Required unless the corresponding environment variable is set — see [🌍 Environment Variables](#-environment-variables) below.

## 🌍 Environment Variables

Set these to avoid passing `--token` and `--project-ref` on every command:

| Variable | Description |
|----------|-------------|
| `SUPABASE_ACCESS_TOKEN` | Your Personal Access Token (`sbp_...`) |
| `SUPABASE_PROJECT_REF` | Your project reference ID |

```cmd
REM Command Prompt
set SUPABASE_ACCESS_TOKEN=sbp_your_token_here
set SUPABASE_PROJECT_REF=your-project-ref
```

```powershell
# PowerShell
$env:SUPABASE_ACCESS_TOKEN="sbp_your_token_here"
$env:SUPABASE_PROJECT_REF="your-project-ref"
```

Once set, commands simplify to:

```cmd
python supabase-functions-backup.py backup
python supabase-functions-backup.py list
```

## 🗂️ Backup Directory Structure

By default each project's backup is saved to its own folder named `edge_functions_backup_<project-ref>`, so running backup for multiple projects will never overwrite each other:

```
edge_functions_backup_abcdefghijklmnop/
  manifest.json              # Backup timestamp, source project, function list
  hello-world/
    metadata.json            # Full function config from the API
    source/
      index.ts               # Source files as returned by the API
  send-email/
    metadata.json
    source/
      index.ts
  process-webhook/
    metadata.json
    source/
      index.ts
      utils/helper.ts        # Additional files if present
```

The `manifest.json` records the source project ref, backup timestamp, and key settings for each function — this is what the `restore` command reads.

## 📦 What Gets Backed Up

For each function the tool saves:

| Field | Description |
|-------|-------------|
| `slug` | URL-safe identifier used to invoke the function |
| `name` | Human-readable display name |
| `verify_jwt` | Whether the function requires a valid JWT to invoke |
| `entrypoint_path` | Entry point file (usually `index.ts`) |
| `import_map_path` | Path to the import map, if configured |
| `version` | Deployment version number |
| `status` | Whether the function is `ACTIVE` or not |
| source bundle | The compiled `.eszip` artefact that Supabase actually runs |

## 🔁 Typical Workflows

**Clone functions to a staging environment:**

```cmd
python supabase-functions-backup.py backup --project-ref prod-ref --dir .\prod-backup
python supabase-functions-backup.py restore --project-ref staging-ref --dir .\prod-backup
```

**Nightly backup via Task Scheduler (Windows):**

```cmd
python supabase-functions-backup.py backup --project-ref %SUPABASE_PROJECT_REF% --dir C:\Backups\edge-functions
```

**Selective restore after an incident:**

```cmd
python supabase-functions-backup.py restore --project-ref prod-ref --dir .\last-known-good --slugs broken-function
```

## ⚠️ Important Notes

- 🔐 **Secrets are NOT backed up.** Edge Function secrets (set via `supabase secrets set`) are not accessible through the Management API. You'll need to set these manually on the target project after restoring.
- 📦 **The source bundle is a compiled artefact.** The API returns the eszip bundle, not your original TypeScript source files. Keep raw source in version control — this tool backs up the *deployed* state.
- 🚦 **Rate limiting is handled automatically.** The script adds a small delay between API calls and will back off and retry if it hits the 120 requests/minute limit.
- ♻️ **Restoring to the same project overwrites.** Functions with matching slugs will be updated to the backed-up version. The tool will warn you before proceeding.
