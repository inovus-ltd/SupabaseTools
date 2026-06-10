# AGENT.md — SupabaseTools

This file is intended for AI agents. It describes the repository structure, available tools, their CLI interfaces, inputs/outputs, error modes, and how to invoke them correctly.

---

## Repository Overview

**SupabaseTools** is a collection of Python CLI scripts for managing Supabase projects programmatically. Each tool lives in its own subdirectory with its own README.

```
SupabaseTools/
  supabase-functions-backup/
    supabase-functions-backup.py    # Edge Functions backup & restore tool
    README.md
  supabase-storage-copy/
    supabase-storage-copy.py        # Storage bucket backup & restore tool
    README.md
  supabase-secrets-manager/
    supabase-secrets-manager.py     # Edge Function secrets list/set/delete/push tool
    README.md
  supabase-auth-copy/
    supabase-auth-copy.py           # Auth config + Third-Party Auth provider backup/restore
    README.md
  README.md                         # Root overview
  AGENT.md                          # This file
  .gitignore
```

**Runtime requirements:**
- Python 3.8+
- `requests` library (`pip install requests`)
- All scripts are run directly: `python <script>.py <command> [options]`

---

## Authentication Concepts

| Credential | Flag | Env Var | Scope | Where to find |
|------------|------|---------|-------|---------------|
| Personal Access Token (PAT) | `--token` | `SUPABASE_ACCESS_TOKEN` | Account-level. Works across all projects. Used for Management API calls. | `https://supabase.com/dashboard/account/tokens` |
| Service Role Key | `--service-key` | `SUPABASE_SERVICE_ROLE_KEY` | Project-level. Bypasses RLS. Required for Storage file operations. | `https://supabase.com/dashboard/project/<ref>/settings/api` |
| Project Reference ID | `--project-ref` | `SUPABASE_PROJECT_REF` | Alphanumeric ID in the dashboard URL: `supabase.com/dashboard/project/<ref>` | Dashboard URL or Project Settings → General |

**Important:** When copying storage between projects, the `--service-key` must be the **target** project's service role key during restore, not the source project's.

---

## Tool 1: `supabase-functions-backup`

**Script:** `supabase-functions-backup/supabase-functions-backup.py`

Backs up and restores Supabase Edge Functions (metadata + source files) using the Management API only. Does **not** require a service role key.

### Commands

#### `list` — List Edge Functions on a project

```
python supabase-functions-backup.py list --project-ref <ref> --token <pat>
```

**Output:** Prints each function slug, name, version, status, JWT verification setting.

---

#### `backup` — Download all Edge Functions to disk

```
python supabase-functions-backup.py backup --project-ref <ref> --token <pat> [--dir <path>]
```

| Flag | Required | Default | Description |
|------|----------|---------|-------------|
| `--project-ref` | Yes* | `SUPABASE_PROJECT_REF` | Source project ref |
| `--token` | Yes* | `SUPABASE_ACCESS_TOKEN` | PAT |
| `--dir` | No | `edge_functions_backup_<project-ref>` | Directory to write backup into |

**Output directory layout:**
```
edge_functions_backup_<ref>/
  manifest.json               # project_ref, backup_time, function list
  <slug>/
    metadata.json             # name, verify_jwt, entrypoint_path, import_map_path, version, status
    source/
      index.ts                # source files as returned by the API (multipart)
      utils/helper.ts         # additional files if present
```

**Printed on success:**
```
  Backup complete. N function(s) saved.
  Manifest: <absolute path to manifest.json>

  To restore these functions:
    Same project:      python supabase-functions-backup.py restore --project-ref <ref>
    Different project: python supabase-functions-backup.py restore --project-ref <target-ref> --dir <backup-dir>
```

---

#### `restore` — Deploy functions from a backup to a project

```
python supabase-functions-backup.py restore --project-ref <ref> --token <pat> [--dir <path>] [--slugs <slug> ...] [--dry-run]
```

| Flag | Required | Default | Description |
|------|----------|---------|-------------|
| `--project-ref` | Yes* | `SUPABASE_PROJECT_REF` | Target project ref |
| `--token` | Yes* | `SUPABASE_ACCESS_TOKEN` | PAT |
| `--dir` | No | `edge_functions_backup_<project-ref>` | Directory to read backup from |
| `--slugs` | No | all functions | Space-separated list of slugs to restore |
| `--dry-run` | No | false | Preview without deploying |

**Key behaviour:**
- If `manifest.json` is not found in `--dir`, the script prints available backup folders and exits.
- When restoring to a **different** project, `--dir` must explicitly point at the source project's backup folder (e.g. `edge_functions_backup_sourceref`), because the default dir is named after the target ref.
- Functions are created if they don't exist on the target; updated (redeployed) if they do.
- `entrypoint_path` is normalised to just the filename (e.g. `index.ts`) before deployment.

---

### Edge Functions — What is and is NOT backed up

| Backed up | NOT backed up |
|-----------|---------------|
| Function metadata (name, slug, verify_jwt, entrypoint, import map) | Edge Function **secrets** (set via `supabase secrets set`) |
| Source files (TypeScript) as multipart from the API | |

---

## Tool 2: `supabase-storage-copy`

**Script:** `supabase-storage-copy/supabase-storage-copy.py`

Backs up and restores Supabase Storage buckets (config + all files) across projects. Requires both a PAT (Management API for bucket metadata) and a service role key (Storage API for file operations).

### Commands

#### `list` — List storage buckets on a project

```
python supabase-storage-copy.py list --project-ref <ref> --token <pat> --service-key <key> [--files]
```

| Flag | Required | Default | Description |
|------|----------|---------|-------------|
| `--project-ref` | Yes* | `SUPABASE_PROJECT_REF` | Project ref |
| `--token` | Yes* | `SUPABASE_ACCESS_TOKEN` | PAT |
| `--service-key` | Yes* | `SUPABASE_SERVICE_ROLE_KEY` | Service role key |
| `--files` | No | false | Also list all objects within each bucket |

**Output example:**
```
 Storage buckets on project: abcdefghijklmnop

  📦 activity-media  [public, max 100MB]

  Total: 1 bucket(s)
```

---

#### `backup` — Download buckets and all files to disk

```
python supabase-storage-copy.py backup --project-ref <ref> --token <pat> --service-key <key> [--dir <path>] [--buckets <id> ...]
```

| Flag | Required | Default | Description |
|------|----------|---------|-------------|
| `--project-ref` | Yes* | `SUPABASE_PROJECT_REF` | Source project ref |
| `--token` | Yes* | `SUPABASE_ACCESS_TOKEN` | PAT |
| `--service-key` | Yes* | `SUPABASE_SERVICE_ROLE_KEY` | Service role key for source project |
| `--dir` | No | `storage_backup_<project-ref>` | Directory to write backup into |
| `--buckets` | No | all buckets | Space-separated list of bucket IDs to back up |

**Output directory layout:**
```
storage_backup_<ref>/
  manifest.json               # backup_time, source project_ref, bucket list with object counts
  <bucket-id>/
    bucket.json               # id, public, file_size_limit, allowed_mime_types
    files/
      path/to/file.ext        # mirrors the bucket's folder structure exactly
```

**Printed on success:**
```
  Backup complete. N bucket(s) saved.
  Manifest: <absolute path>

  To restore these buckets:
    Same project:      python supabase-storage-copy.py restore --project-ref <ref> --service-key <key>
    Different project: python supabase-storage-copy.py restore --project-ref <target-ref> --service-key <key> --dir storage_backup_<ref>
```

---

#### `restore` — Upload buckets and files to a project

```
python supabase-storage-copy.py restore --project-ref <ref> --token <pat> --service-key <key> [--dir <path>] [--buckets <id> ...] [--mode skip|merge|overwrite] [--dry-run]
```

| Flag | Required | Default | Description |
|------|----------|---------|-------------|
| `--project-ref` | Yes* | `SUPABASE_PROJECT_REF` | **Target** project ref |
| `--token` | Yes* | `SUPABASE_ACCESS_TOKEN` | PAT |
| `--service-key` | Yes* | `SUPABASE_SERVICE_ROLE_KEY` | Service role key for **target** project |
| `--dir` | No | `storage_backup_<project-ref>` | Directory to read backup from |
| `--buckets` | No | all buckets | Space-separated list of bucket IDs to restore |
| `--mode` | No | `merge` | Conflict resolution mode (see below) |
| `--dry-run` | No | false | Preview without uploading |

**Restore modes:**

| Mode | Behaviour |
|------|-----------|
| `skip` | If the bucket already exists on the target, skip it entirely |
| `merge` | Create bucket if missing; upload files without touching existing config *(default)* |
| `overwrite` | Update bucket config (public flag, allowed MIME types) via `PUT /bucket/{id}` on the Storage API, then upload all files |

**Key behaviour:**
- `--service-key` must be the **target** project's key, not the source's.
- When restoring cross-project, use `--dir` to point at the source backup folder.
- MIME types are detected from file extension. Full map covers images, video (including `.webm`), audio, documents, fonts. Unknown extensions fall back to `application/octet-stream`.
- `--mode overwrite` updates bucket `public` flag and `allowed_mime_types` only — `file_size_limit` is intentionally excluded from the update payload to avoid Storage API rejection.

---

### Storage — What is and is NOT backed up

| Backed up | NOT backed up |
|-----------|---------------|
| Bucket config (id, public flag, file_size_limit, allowed_mime_types) | Storage **RLS policies** — must be recreated manually or via migrations |
| All objects (files), preserving folder structure | |

---

---

## Tool 3: `supabase-secrets-manager`

**Script:** `supabase-secrets-manager/supabase-secrets-manager.py`

List, add, update, and delete Supabase Edge Function secrets via the Management API. Does **not** require a service role key.

**Critical constraint:** The API **never returns secret values** — only names. This tool cannot export existing secret values from a project.

### Commands

#### `list` — List all secret names on a project

```
python supabase-secrets-manager.py list --project-ref <ref> --token <pat>
```

**Output:** Prints each secret name alphabetically. Values are never shown.

---

#### `set` — Add or update secrets interactively

```
python supabase-secrets-manager.py set --project-ref <ref> --token <pat> [--names NAME1 NAME2 ...]
```

| Flag | Required | Default | Description |
|------|----------|---------|-------------|
| `--project-ref` | Yes* | `SUPABASE_PROJECT_REF` | Target project ref |
| `--token` | Yes* | `SUPABASE_ACCESS_TOKEN` | PAT |
| `--names` | No | *(prompted)* | Secret names to set — if omitted, prompts for both name and value in a loop |
| `--dry-run` | No | false | Preview without setting |

- Values are entered via hidden prompt (like a password). Existing secrets are overwritten.
- If `--names` provided: prompts only for values, one per name.
- If `--names` omitted: loops prompting for name then value until blank name entered.

---

#### `delete` — Delete secrets by name

```
python supabase-secrets-manager.py delete --project-ref <ref> --token <pat> --names NAME1 NAME2 ...
```

| Flag | Required | Default | Description |
|------|----------|---------|-------------|
| `--names` | Yes | — | One or more secret names to delete |
| `--dry-run` | No | false | Preview without deleting |

- Requires typing `YES` to confirm before deleting.

---

#### `push` — Push secrets from a .env file

```
python supabase-secrets-manager.py push --project-ref <ref> --token <pat> [--env-file PATH]
```

| Flag | Required | Default | Description |
|------|----------|---------|-------------|
| `--env-file` | No | `.env` | Path to the .env file to read secrets from |
| `--dry-run` | No | false | Preview without pushing |

- Parses `KEY=VALUE` lines; skips blank lines and `#` comments.
- Strips surrounding single or double quotes from values.
- All parsed secrets are upserted on the project.

---

### Secrets — What is and is NOT possible

| Possible | NOT possible |
|----------|--------------|
| List secret names | Read/export existing secret values |
| Set (create or overwrite) secrets by name+value | Copy secret values from one project to another automatically |
| Delete secrets by name | |
| Push secrets from a .env file | |

---

## Tool 4: `supabase-auth-copy`

**Script:** `supabase-auth-copy/supabase-auth-copy.py`

Backup and restore Supabase Auth configuration and Third-Party Auth provider integrations (e.g. Amazon Cognito User Pools) across projects. Does **not** require a service role key.

**Important:** Sensitive values (JWT secret, OAuth client secrets, SMTP password) are **stripped from backups** and never restored. They must be set manually on the target.

### Commands

#### `list` — Show auth config summary and providers

```
python supabase-auth-copy.py list --project-ref <ref> --token <pat>
```

**Output:** Key auth settings (site URL, JWT expiry, signup disabled, email config) and all third-party provider integrations.

---

#### `backup` — Save auth config and providers to disk

```
python supabase-auth-copy.py backup --project-ref <ref> --token <pat> [--dir <path>]
```

| Flag | Required | Default | Description |
|------|----------|---------|-------------|
| `--project-ref` | Yes* | `SUPABASE_PROJECT_REF` | Source project ref |
| `--token` | Yes* | `SUPABASE_ACCESS_TOKEN` | PAT |
| `--dir` | No | `auth_backup_<project-ref>` | Directory to write backup into |

**Output directory layout:**
```
auth_backup_<ref>/
  manifest.json           # project_ref, backup_time, provider count, stripped key names
  auth_config.json        # full auth config blob (sensitive keys removed)
  third_party_auth.json   # list of third-party provider configs
```

---

#### `restore` — Apply auth config and providers to a project

```
python supabase-auth-copy.py restore --project-ref <ref> --token <pat> [--dir <path>] [options]
```

| Flag | Required | Default | Description |
|------|----------|---------|-------------|
| `--project-ref` | Yes* | `SUPABASE_PROJECT_REF` | Target project ref |
| `--token` | Yes* | `SUPABASE_ACCESS_TOKEN` | PAT |
| `--dir` | No | `auth_backup_<project-ref>` | Directory to read backup from |
| `--skip-config` | No | false | Skip auth config — only restore providers |
| `--skip-providers` | No | false | Skip providers — only restore auth config |
| `--dry-run` | No | false | Preview without making any changes |

**Key behaviour:**
- Auth config is applied via PATCH — only keys present in backup are changed; others untouched.
- Providers already matching on the target (same type + pool ID + region) are skipped — no duplicates.
- When cross-project, use `--dir` to point at source backup folder.
- `site_url` is restored from backup — update it manually if the target project has a different domain.

---

### Auth — What is and is NOT backed up

| Backed up | NOT backed up |
|-----------|---------------|
| JWT expiry, site URL, redirect URLs | JWT secret (sensitive) |
| Email/password, session, rate limit settings | OAuth client secrets (sensitive) |
| MFA settings | SMTP password (sensitive) |
| OAuth provider enabled flags + client IDs | User data |
| Amazon Cognito User Pool integrations (pool ID + region) | RLS policies |

---

## Common Patterns for Agents

### Clone Edge Functions from project A to project B

```
python supabase-functions-backup.py backup --project-ref <source-ref> --token <pat>
python supabase-functions-backup.py restore --project-ref <target-ref> --token <pat> --dir edge_functions_backup_<source-ref>
```

### Clone Storage buckets from project A to project B

```
python supabase-storage-copy.py backup --project-ref <source-ref> --token <pat> --service-key <source-service-key>
python supabase-storage-copy.py restore --project-ref <target-ref> --token <pat> --service-key <target-service-key> --dir storage_backup_<source-ref> --mode overwrite
```

### Preview a restore without making changes

```
python supabase-functions-backup.py restore --project-ref <ref> --token <pat> --dry-run
python supabase-storage-copy.py restore --project-ref <ref> --token <pat> --service-key <key> --dry-run
```

### Clone Auth config and Third-Party Providers from project A to project B

```
python supabase-auth-copy.py backup --project-ref <source-ref> --token <pat>
python supabase-auth-copy.py restore --project-ref <target-ref> --token <pat> --dir auth_backup_<source-ref>
```

### Copy only Third-Party Auth providers (skip general auth config)

```
python supabase-auth-copy.py restore --project-ref <target-ref> --token <pat> --dir auth_backup_<source-ref> --skip-config
```

### Copy secrets to another project (via .env file)

```
REM Step 1: List secret names on the source project
python supabase-secrets-manager.py list --project-ref <source-ref> --token <pat>

REM Step 2: Push from a .env file to the target (if you have the values in a file)
python supabase-secrets-manager.py push --project-ref <target-ref> --token <pat> --env-file .env.production

REM OR: Set secrets interactively on the target using the names from step 1
python supabase-secrets-manager.py set --project-ref <target-ref> --token <pat> --names SECRET_A SECRET_B SECRET_C
```

### Restore only specific items

```
REM Edge Functions — restore only named slugs
python supabase-functions-backup.py restore --project-ref <ref> --token <pat> --slugs send-email process-webhook

REM Storage — restore only named buckets
python supabase-storage-copy.py restore --project-ref <ref> --token <pat> --service-key <key> --buckets avatars documents
```

---

## Error Reference

| Error message | Cause | Fix |
|---------------|-------|-----|
| `manifest.json not found` | `--dir` points at wrong folder or backup doesn't exist | Pass `--dir edge_functions_backup_<source-ref>` explicitly |
| `HTTP 400: invalid_mime_type` | File extension not mapping to a MIME type accepted by the bucket | Use `--mode overwrite` to push source bucket's allowed_mime_types to target |
| `HTTP 400: Payload too large` | `file_size_limit` value sent in bucket update body | Already fixed — tool excludes `file_size_limit` from PUT payload |
| `HTTP 404: Cannot PUT /v1/projects/.../storage/buckets/...` | Attempted bucket update via Management API | Already fixed — tool uses Storage API for updates |
| `HTTP 401` on any call | Invalid or expired token / service key | Regenerate credentials from Supabase dashboard |
| `requests` ImportError | Dependency not installed | Run `pip install requests` |

---

## Environment Variables

All credentials can be passed via CLI flags or environment variables. Flags take precedence when both are provided.

| Variable | Equivalent flag | Scope | Notes |
|----------|----------------|-------|-------|
| `SUPABASE_ACCESS_TOKEN` | `--token` | Account-level PAT | Required by all tools |
| `SUPABASE_PROJECT_REF` | `--project-ref` | Single project ref | Required by all tools |
| `SUPABASE_SERVICE_ROLE_KEY` | `--service-key` | Project-level | Required only for `supabase-storage-copy` |

Full setup instructions (session vs persistent, all platforms): see root [README.md — Environment Variables](./README.md#-environment-variables).

### Windows — current session

```powershell
# PowerShell
$env:SUPABASE_ACCESS_TOKEN = "sbp_xxxxxxxxxxxx"
$env:SUPABASE_PROJECT_REF = "abcdefghijklmnop"
$env:SUPABASE_SERVICE_ROLE_KEY = "eyJhbGci..."
```

```cmd
REM Command Prompt
set SUPABASE_ACCESS_TOKEN=sbp_xxxxxxxxxxxx
set SUPABASE_PROJECT_REF=abcdefghijklmnop
set SUPABASE_SERVICE_ROLE_KEY=eyJhbGci...
```

Verify: PowerShell `echo $env:SUPABASE_ACCESS_TOKEN` · CMD `echo %SUPABASE_ACCESS_TOKEN%`

### Windows — persist across sessions

```powershell
# User-level (survives reboot; requires new terminal)
[System.Environment]::SetEnvironmentVariable("SUPABASE_ACCESS_TOKEN", "sbp_xxxxxxxxxxxx", "User")
[System.Environment]::SetEnvironmentVariable("SUPABASE_PROJECT_REF", "abcdefghijklmnop", "User")
```

Or add `$env:SUPABASE_ACCESS_TOKEN = "sbp_..."` to the PowerShell profile (`notepad $PROFILE`).

```cmd
REM setx — applies to new CMD windows only; ~1024 char limit
setx SUPABASE_ACCESS_TOKEN "sbp_xxxxxxxxxxxx"
setx SUPABASE_PROJECT_REF "abcdefghijklmnop"
```

### macOS / Linux — current session

```bash
export SUPABASE_ACCESS_TOKEN="sbp_xxxxxxxxxxxx"
export SUPABASE_PROJECT_REF="abcdefghijklmnop"
export SUPABASE_SERVICE_ROLE_KEY="eyJhbGci..."
```

Verify: `echo $SUPABASE_ACCESS_TOKEN`

### macOS / Linux — persist across sessions

Add `export` lines to `~/.bashrc`, `~/.bash_profile`, or `~/.zshrc`, then `source` the file.

### Reduced commands when env vars are set

```cmd
python supabase-functions-backup.py backup
python supabase-storage-copy.py backup
python supabase-auth-copy.py list
python supabase-secrets-manager.py list
```
