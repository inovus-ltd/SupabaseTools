# 🗄️ supabase-storage-copy

Backup and restore Supabase Storage buckets (config + all files) across projects using the Supabase Management and Storage APIs.

---

## 📋 Prerequisites

- 🐍 **Python 3.8+**
- 📦 **requests** library — `pip install requests`
- 🔑 **Supabase Personal Access Token (PAT)** — see [🔑 How to Get Your Token](../README.md#-how-to-get-your-token) in the root README
- 🆔 **Supabase Project Reference ID** — the alphanumeric string in your project dashboard URL:
  `https://supabase.com/dashboard/project/abcdefghijklmnop` → ref is `abcdefghijklmnop`
- 🗝️ **Supabase Service Role Key** — required to read/write storage objects. Find it at:
  `Project Settings → API → Project API Keys → service_role`
  > ⚠️ Keep this key secret — it bypasses Row Level Security.

---

## ⚡ Quick Start

```cmd
REM List all buckets on a project
python supabase-storage-copy.py list --project-ref abcdefghijklmnop --token sbp_xxxxxxxxxxxx --service-key eyJhbGci...

REM Backup all buckets to a local directory
python supabase-storage-copy.py backup --project-ref abcdefghijklmnop --token sbp_xxxxxxxxxxxx --service-key eyJhbGci...

REM Restore to a different project
python supabase-storage-copy.py restore --project-ref newprojectref --token sbp_xxxxxxxxxxxx --service-key eyJhbGci... --dir storage_backup_abcdefghijklmnop
```

---

## 🔧 Commands & Parameters

### `list` — List buckets

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `--project-ref` | Yes* | `SUPABASE_PROJECT_REF` | Project reference ID |
| `--token` | Yes* | `SUPABASE_ACCESS_TOKEN` | Personal Access Token |
| `--service-key` | Yes* | `SUPABASE_SERVICE_ROLE_KEY` | Service role key |
| `--files` | No | `false` | Also list all objects within each bucket |

*Can be set via environment variable instead.

```cmd
REM List buckets only
python supabase-storage-copy.py list --project-ref abcdefghijklmnop

REM List buckets and their file contents
python supabase-storage-copy.py list --project-ref abcdefghijklmnop --files
```

---

### `backup` — Download buckets and files

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `--project-ref` | Yes* | `SUPABASE_PROJECT_REF` | Project reference ID |
| `--token` | Yes* | `SUPABASE_ACCESS_TOKEN` | Personal Access Token |
| `--service-key` | Yes* | `SUPABASE_SERVICE_ROLE_KEY` | Service role key |
| `--dir` | No | `storage_backup_<project-ref>` | Directory to save backups into |
| `--buckets` | No | *(all buckets)* | Space-separated list of bucket IDs to back up |

```cmd
REM Backup all buckets (default dir)
python supabase-storage-copy.py backup --project-ref abcdefghijklmnop

REM Backup specific buckets only
python supabase-storage-copy.py backup --project-ref abcdefghijklmnop --buckets avatars documents

REM Backup to a custom directory
python supabase-storage-copy.py backup --project-ref abcdefghijklmnop --dir C:\Backups\my-project
```

---

### `restore` — Upload buckets and files to a project

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `--project-ref` | Yes* | `SUPABASE_PROJECT_REF` | Target project reference ID |
| `--token` | Yes* | `SUPABASE_ACCESS_TOKEN` | Personal Access Token |
| `--service-key` | Yes* | `SUPABASE_SERVICE_ROLE_KEY` | Service role key for the **target** project |
| `--dir` | No | `storage_backup_<project-ref>` | Directory containing the backup to restore from |
| `--buckets` | No | *(all buckets)* | Space-separated list of bucket IDs to restore |
| `--mode` | No | `merge` | How to handle existing buckets — see below |
| `--dry-run` | No | `false` | Preview what would be done without making changes |

#### Restore modes

| Mode | Behaviour |
|------|-----------|
| `skip` | Leave buckets that already exist on the target completely untouched |
| `merge` | Create the bucket if it doesn't exist; upload files without deleting anything *(default)* |
| `overwrite` | Update the bucket config and re-upload all files |

**Restoring to the same project** (default `--dir` works automatically):

```cmd
python supabase-storage-copy.py restore --project-ref abcdefghijklmnop --service-key eyJhbGci...
```

**Restoring to a DIFFERENT project** — use `--dir` to point at the source project's backup:

```cmd
python supabase-storage-copy.py restore --project-ref newprojectref --service-key eyJhbGci... --dir storage_backup_abcdefghijklmnop
```

```cmd
REM Restore specific buckets only
python supabase-storage-copy.py restore --project-ref newprojectref --service-key eyJhbGci... --dir storage_backup_abcdefghijklmnop --buckets avatars documents

REM Preview without uploading anything
python supabase-storage-copy.py restore --project-ref newprojectref --service-key eyJhbGci... --dir storage_backup_abcdefghijklmnop --dry-run

REM Overwrite existing buckets entirely
python supabase-storage-copy.py restore --project-ref newprojectref --service-key eyJhbGci... --dir storage_backup_abcdefghijklmnop --mode overwrite
```

> 💡 If you forget `--dir`, the script will print the available backup folders to help you find the right one.

---

## 🌍 Environment Variables

Set these to avoid passing credentials on every command:

| Variable | Equivalent flag | Description |
|----------|----------------|-------------|
| `SUPABASE_ACCESS_TOKEN` | `--token` | Personal Access Token |
| `SUPABASE_SERVICE_ROLE_KEY` | `--service-key` | Service role key |
| `SUPABASE_PROJECT_REF` | `--project-ref` | Project reference ID |

**Windows (PowerShell):**
```powershell
$env:SUPABASE_ACCESS_TOKEN="sbp_xxxxxxxxxxxx"
$env:SUPABASE_SERVICE_ROLE_KEY="eyJhbGci..."
$env:SUPABASE_PROJECT_REF="abcdefghijklmnop"
```

**Windows (Command Prompt):**
```cmd
set SUPABASE_ACCESS_TOKEN=sbp_xxxxxxxxxxxx
set SUPABASE_SERVICE_ROLE_KEY=eyJhbGci...
set SUPABASE_PROJECT_REF=abcdefghijklmnop
```

---

## 🗂️ Backup Directory Structure

Each project's backup is saved to its own folder:

```
storage_backup_abcdefghijklmnop/
  manifest.json              # Bucket list, settings, backup timestamp
  avatars/
    bucket.json              # Bucket config (public, size limits, etc.)
    files/
      user-123/avatar.png    # Files mirror the bucket's folder structure
      user-456/avatar.jpg
  documents/
    bucket.json
    files/
      reports/2025/q1.pdf
      reports/2025/q2.pdf
```

---

## 📦 What Gets Backed Up

| Item | Description |
|------|-------------|
| Bucket config | `id`, `public` flag, `file_size_limit`, `allowed_mime_types` |
| All objects | Every file in every bucket, preserving folder structure |
| Manifest | Bucket list, object counts, total sizes, backup timestamp |

> ⚠️ **What is NOT backed up:** Storage policies (RLS rules) are not included — these must be recreated manually or via migrations.

---

## 🔄 Typical Workflows

**Clone a project's storage to a new project:**
```cmd
REM 1. Back up source
python supabase-storage-copy.py backup --project-ref sourceref

REM 2. Restore to target
python supabase-storage-copy.py restore --project-ref targetref --service-key eyJhbGci... --dir storage_backup_sourceref
```

**Regular backup of a live project:**
```cmd
python supabase-storage-copy.py backup --project-ref abcdefghijklmnop
```

**Preview a restore before committing:**
```cmd
python supabase-storage-copy.py restore --project-ref targetref --service-key eyJhbGci... --dir storage_backup_sourceref --dry-run
```

---

## ⚠️ Important Notes

- 🗝️ The `--service-key` must be the key for the **target** project when restoring, not the source
- 📏 Large files will take time — the tool processes files sequentially with a small delay to avoid rate limits
- 🔒 Storage policies (RLS) are **not** copied — recreate them manually on the target project
- 🔁 `--mode overwrite` re-uploads all files but does **not** delete files that exist on the target but not in the backup
