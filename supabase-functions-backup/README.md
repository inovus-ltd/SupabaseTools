# Supabase Edge Functions Backup & Restore

A Python CLI tool that backs up all Edge Functions from a Supabase project and can restore them to the same or a different project. Useful for migrating between environments, disaster recovery, or cloning a project's serverless layer.

## How It Works

The tool talks to the [Supabase Management API](https://supabase.com/docs/reference/api) -- the same API that powers the CLI and Dashboard. For each Edge Function it:

1. **Backup**: Downloads the function metadata (name, slug, JWT verification setting, entrypoint, import map) and the compiled source bundle (eszip format), saving everything into a structured local directory.

2. **Restore**: Reads the backup directory and uses the `/functions/deploy` endpoint to push each function to the target project. If a function with the same slug already exists, it gets updated. If it doesn't exist, it gets created.

## Prerequisites

- Python 3.8+
- `requests` library (`pip install requests`)
- A **Supabase Personal Access Token (PAT)** — see [How to get your token](#how-to-get-your-token) below
- Your **Supabase Project Reference ID** — the short alphanumeric string in your project's dashboard URL, e.g. `https://supabase.com/dashboard/project/abcdefghijklmnop` → ref is `abcdefghijklmnop`. Also visible under *Project Settings → General*.

## How to Get Your Token

1. Log in to [supabase.com](https://supabase.com)
2. Click your avatar (top-right) → **Account**
3. Go to [Account → Access Tokens](https://supabase.com/dashboard/account/tokens)
4. Click **Generate new token**, give it a name (e.g. `backup-tool`), and copy the value

> ⚠️ The token is shown **only once**. Store it somewhere safe (e.g. a password manager or `.env` file).
>
> This is an **account-level** token — it has access to all projects in your Supabase account. Treat it like a password and never commit it to version control.

## Quick Start

### 1. Back up all functions from a project

```bash
python supabase-functions-backup.py backup \
  --project-ref abcdefghijklmnop \
  --token sbp_xxxxxxxxxxxxxxxxxxxx
```

Replace `abcdefghijklmnop` with your project ref and `sbp_xxxxxxxxxxxxxxxxxxxx` with your PAT (see [How to Get Your Token](#how-to-get-your-token)).

This creates an `edge_functions_backup/` directory containing a manifest and one subdirectory per function.

### 2. List functions (without downloading)

```bash
python supabase-functions-backup.py list \
  --project-ref your-project-ref \
  --token sbp_your_token_here
```

### 3. Restore to a different project

```bash
python supabase-functions-backup.py restore \
  --project-ref target-project-ref \
  --token sbp_your_token_here
```

### 4. Restore only specific functions

```bash
python supabase-functions-backup.py restore \
  --project-ref target-project-ref \
  --token sbp_your_token_here \
  --slugs send-email process-webhook
```

### 5. Dry run (preview without deploying)

```bash
python supabase-functions-backup.py restore \
  --project-ref target-project-ref \
  --dry-run
```

## Using Environment Variables

Instead of passing `--token` and `--project-ref` every time, you can set environment variables:

```bash
export SUPABASE_ACCESS_TOKEN=sbp_your_token_here
export SUPABASE_PROJECT_REF=your-project-ref

# Now just:
python supabase-functions-backup.py backup
python supabase-functions-backup.py list
```

## Backup Directory Structure

After a backup, the directory looks like this:

```
edge_functions_backup/
  manifest.json              # When the backup was taken, which project, list of functions
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

The `manifest.json` records the source project ref, backup timestamp, and key settings for each function. This is what the restore command reads to know what to deploy and how to configure it.

## Custom Backup Directory

Use `--dir` to control where backups are saved or read from:

```bash
# Save to a specific location
python supabase-functions-backup.py backup --dir ./backups/2025-03-11

# Restore from that location
python supabase-functions-backup.py restore \
  --project-ref target-ref \
  --dir ./backups/2025-03-11
```

## What Gets Backed Up

For each function, the tool saves:

- **slug** -- the URL-safe identifier used to invoke the function
- **name** -- the human-readable display name
- **verify_jwt** -- whether the function requires a valid JWT to invoke
- **entrypoint_path** -- which file is the entry point (usually `index.ts`)
- **import_map_path** -- path to the import map, if one is configured
- **version** -- the deployment version number
- **status** -- whether the function is ACTIVE or not
- **source bundle** -- the compiled eszip artefact that Supabase actually runs

## Important Notes

- **Secrets are NOT backed up.** Edge Function secrets (environment variables set via `supabase secrets set`) are stored separately and are not accessible through the Management API's function endpoints. You will need to set these manually on the target project after restoring.

- **The source bundle is a compiled artefact.** The Management API returns the eszip bundle, not your original TypeScript source files. If you need the raw source, keep it in version control (which you should be doing anyway). This tool is for backing up the *deployed* state.

- **Rate limiting is handled automatically.** The script adds a small delay between API calls and will back off and retry if it hits the 120 requests/minute limit.

- **Restoring to the same project overwrites.** If you restore to the project the backup came from, existing functions with matching slugs will be updated to the backed-up version. The tool will warn you about this.

## Typical Workflows

**Cloning functions to a staging environment:**

```bash
python supabase-functions-backup.py backup --project-ref prod-ref --dir ./prod-backup
python supabase-functions-backup.py restore --project-ref staging-ref --dir ./prod-backup
```

**Nightly backup via cron:**

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
