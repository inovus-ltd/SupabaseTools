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

```bash
python supabase-functions-backup.py backup \
  --project-ref abcdefghijklmnop \
  --token sbp_xxxxxxxxxxxxxxxxxxxx
```

This creates an `edge_functions_backup/` directory with a manifest and one subdirectory per function.

## 📋 Commands & Parameters

### `backup` — Download all Edge Functions to disk

```bash
python supabase-functions-backup.py backup [options]
```

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `--project-ref` | ✅ Yes* | `SUPABASE_PROJECT_REF` env var | Your Supabase project reference ID |
| `--token` | ✅ Yes* | `SUPABASE_ACCESS_TOKEN` env var | Your Supabase Personal Access Token |
| `--dir` | No | `edge_functions_backup` | Directory to save the backup into |

```bash
python supabase-functions-backup.py backup \
  --project-ref abcdefghijklmnop \
  --token sbp_xxxxxxxxxxxxxxxxxxxx \
  --dir ./my-backup
```

---

### `restore` — Deploy functions from a backup to a project

```bash
python supabase-functions-backup.py restore [options]
```

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `--project-ref` | ✅ Yes* | `SUPABASE_PROJECT_REF` env var | Target project to restore functions into |
| `--token` | ✅ Yes* | `SUPABASE_ACCESS_TOKEN` env var | Your Supabase Personal Access Token |
| `--dir` | No | `edge_functions_backup` | Directory containing the backup to restore from |
| `--slugs` | No | *(all functions)* | Space-separated list of function slugs to restore — omit to restore everything |
| `--dry-run` | No | `false` | Preview what would be deployed without making any changes |

```bash
# Restore all functions to a different project
python supabase-functions-backup.py restore \
  --project-ref target-project-ref \
  --token sbp_xxxxxxxxxxxxxxxxxxxx

# Restore only specific functions
python supabase-functions-backup.py restore \
  --project-ref target-project-ref \
  --token sbp_xxxxxxxxxxxxxxxxxxxx \
  --slugs send-email process-webhook

# Preview without deploying anything
python supabase-functions-backup.py restore \
  --project-ref target-project-ref \
  --token sbp_xxxxxxxxxxxxxxxxxxxx \
  --dry-run
```

---

### `list` — List all Edge Functions on a project

```bash
python supabase-functions-backup.py list [options]
```

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `--project-ref` | ✅ Yes* | `SUPABASE_PROJECT_REF` env var | Project to list functions from |
| `--token` | ✅ Yes* | `SUPABASE_ACCESS_TOKEN` env var | Your Supabase Personal Access Token |

```bash
python supabase-functions-backup.py list \
  --project-ref abcdefghijklmnop \
  --token sbp_xxxxxxxxxxxxxxxxxxxx
```

> \* Required unless the corresponding environment variable is set — see [🌍 Environment Variables](#-environment-variables) below.

## 🌍 Environment Variables

Set these to avoid passing `--token` and `--project-ref` on every command:

| Variable | Description |
|----------|-------------|
| `SUPABASE_ACCESS_TOKEN` | Your Personal Access Token (`sbp_...`) |
| `SUPABASE_PROJECT_REF` | Your project reference ID |

```bash
# Windows (Command Prompt)
set SUPABASE_ACCESS_TOKEN=sbp_your_token_here
set SUPABASE_PROJECT_REF=your-project-ref

# Windows (PowerShell)
$env:SUPABASE_ACCESS_TOKEN="sbp_your_token_here"
$env:SUPABASE_PROJECT_REF="your-project-ref"

# macOS / Linux
export SUPABASE_ACCESS_TOKEN=sbp_your_token_here
export SUPABASE_PROJECT_REF=your-project-ref
```

Once set, commands simplify to:

```bash
python supabase-functions-backup.py backup
python supabase-functions-backup.py list
```

## 🗂️ Backup Directory Structure

```
edge_functions_backup/
  manifest.json              # Backup timestamp, source project, function list
  hello-world/
    metadata.json            # Full function config from the API
    function.eszip           # Compiled source bundle
  send-email/
    metadata.json
    function.eszip
  process-webhook/
    metadata.json
    function.eszip
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

```bash
python supabase-functions-backup.py backup --project-ref prod-ref --dir ./prod-backup
python supabase-functions-backup.py restore --project-ref staging-ref --dir ./prod-backup
```

**Nightly backup via cron (macOS/Linux):**

```bash
#!/bin/bash
DATE=$(date +%Y-%m-%d)
python supabase-functions-backup.py backup \
  --project-ref $SUPABASE_PROJECT_REF \
  --dir "/backups/edge-functions/$DATE"
```

**Selective restore after an incident:**

```bash
python supabase-functions-backup.py restore \
  --project-ref prod-ref \
  --dir ./last-known-good \
  --slugs broken-function
```

## ⚠️ Important Notes

- 🔐 **Secrets are NOT backed up.** Edge Function secrets (set via `supabase secrets set`) are not accessible through the Management API. You'll need to set these manually on the target project after restoring.
- 📦 **The source bundle is a compiled artefact.** The API returns the eszip bundle, not your original TypeScript source files. Keep raw source in version control — this tool backs up the *deployed* state.
- 🚦 **Rate limiting is handled automatically.** The script adds a small delay between API calls and will back off and retry if it hits the 120 requests/minute limit.
- ♻️ **Restoring to the same project overwrites.** Functions with matching slugs will be updated to the backed-up version. The tool will warn you before proceeding.
