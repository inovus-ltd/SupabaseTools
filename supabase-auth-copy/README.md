# 🔐 supabase-auth-copy

Backup and restore Supabase Auth configuration and Third-Party Auth provider integrations (e.g. Amazon Cognito) across projects using the Management API.

Covers two things in one tool:
- **Auth config** — JWT settings, email/password settings, session config, rate limits, URL config, MFA, OAuth providers, etc.
- **Third-Party Auth providers** — Amazon Cognito User Pool integrations (and any future providers Supabase adds)

> ⚠️ Sensitive secret values (JWT secret, OAuth client secrets, SMTP password, etc.) are **stripped from backups** and **never restored**. You must set these manually on the target project.

---

## 📋 Prerequisites

- 🐍 **Python 3.8+**
- 📦 **requests** library — `pip install requests`
- 🔑 **Supabase Personal Access Token (PAT)** — see [🔑 How to Get Your Token](../README.md#-how-to-get-your-token) in the root README
- 🆔 **Supabase Project Reference ID** — the alphanumeric string in your project dashboard URL:
  `https://supabase.com/dashboard/project/abcdefghijklmnop` → ref is `abcdefghijklmnop`

---

## ⚡ Quick Start

**Step 1 — List auth config and providers on the source project:**

```cmd
python supabase-auth-copy.py list --project-ref abcdefghijklmnop --token sbp_xxxxxxxxxxxx
```

```
  Auth configuration for project: abcdefghijklmnop

  ── Auth Config ──────────────────────────────────────────
    Site URL                       https://myapp.com
    JWT expiry (seconds)           3600
    Signup disabled                False
    Email confirmations            True
    Email auth enabled             True

  ── Third-Party Auth Providers ───────────────────────────
    🔗 Amazon Cognito  pool=eu-west-2_aa7ucEcDs  region=eu-west-2
    🔗 Amazon Cognito  pool=eu-west-2_kdwwnU0Yu  region=eu-west-2
    🔗 Amazon Cognito  pool=eu-west-2_uRGwE4ZG2  region=eu-west-2

    Total: 3 provider(s)
```

**Step 2 — Back up to a local directory:**

```cmd
python supabase-auth-copy.py backup --project-ref abcdefghijklmnop --token sbp_xxxxxxxxxxxx
```

```
  Backing up Auth config for project: abcdefghijklmnop
  Destination: J:\Dev\SupabaseTools\supabase-auth-copy\auth_backup_abcdefghijklmnop

  Fetching auth config... saved (3,847 bytes)
    ⚠️  Sensitive keys stripped: jwt_secret, smtp_pass
  Fetching third-party providers... saved (3 provider(s), 412 bytes)
    🔗 Amazon Cognito  pool=eu-west-2_aa7ucEcDs  region=eu-west-2
    🔗 Amazon Cognito  pool=eu-west-2_kdwwnU0Yu  region=eu-west-2
    🔗 Amazon Cognito  pool=eu-west-2_uRGwE4ZG2  region=eu-west-2

  Backup complete.
  Manifest: J:\Dev\SupabaseTools\supabase-auth-copy\auth_backup_abcdefghijklmnop\manifest.json

  To restore:
    Same project:      python supabase-auth-copy.py restore --project-ref abcdefghijklmnop --dir auth_backup_abcdefghijklmnop
    Different project: python supabase-auth-copy.py restore --project-ref <target-ref> --dir auth_backup_abcdefghijklmnop
```

**Step 3 — Restore to a different project:**

```cmd
python supabase-auth-copy.py restore --project-ref newprojectref --token sbp_xxxxxxxxxxxx --dir auth_backup_abcdefghijklmnop
```

```
  Restoring Auth to project: newprojectref
  Source backup:    J:\Dev\SupabaseTools\supabase-auth-copy\auth_backup_abcdefghijklmnop
  Backup taken:     2026-04-02T15:00:00.000000+00:00
  Original project: abcdefghijklmnop

  ── Auth Config (applying) ──────────────────
    87 key(s) to apply
    site_url: https://myapp.com
    jwt_exp: 3600
    disable_signup: False
    email_confirmations: True
    ✅ Auth config applied.

  ── Third-Party Providers (restoring) ─────────────────
    ✅ Added: Amazon Cognito  pool=eu-west-2_aa7ucEcDs  region=eu-west-2
    ✅ Added: Amazon Cognito  pool=eu-west-2_kdwwnU0Yu  region=eu-west-2
    ✅ Added: Amazon Cognito  pool=eu-west-2_uRGwE4ZG2  region=eu-west-2

    3 added, 0 skipped (already existed)

  Restore complete.
```

---

## 🔧 Commands & Parameters

### `list` — Show auth config and providers

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `--project-ref` | Yes* | `SUPABASE_PROJECT_REF` | Project reference ID |
| `--token` | Yes* | `SUPABASE_ACCESS_TOKEN` | Personal Access Token |

```cmd
python supabase-auth-copy.py list --project-ref abcdefghijklmnop --token sbp_xxxxxxxxxxxx
```

---

### `backup` — Save auth config and providers to disk

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `--project-ref` | Yes* | `SUPABASE_PROJECT_REF` | Source project reference ID |
| `--token` | Yes* | `SUPABASE_ACCESS_TOKEN` | Personal Access Token |
| `--dir` | No | `auth_backup_<project-ref>` | Directory to save backup into |

```cmd
REM Default directory (named after project ref)
python supabase-auth-copy.py backup --project-ref abcdefghijklmnop --token sbp_xxxxxxxxxxxx

REM Custom directory
python supabase-auth-copy.py backup --project-ref abcdefghijklmnop --token sbp_xxxxxxxxxxxx --dir C:\Backups\my-auth-backup
```

---

### `restore` — Apply auth config and providers to a project

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `--project-ref` | Yes* | `SUPABASE_PROJECT_REF` | **Target** project reference ID |
| `--token` | Yes* | `SUPABASE_ACCESS_TOKEN` | Personal Access Token |
| `--dir` | No | `auth_backup_<project-ref>` | Directory containing the backup |
| `--skip-config` | No | `false` | Skip the main auth config — only restore providers |
| `--skip-providers` | No | `false` | Skip providers — only restore the main auth config |
| `--dry-run` | No | `false` | Preview what would be changed without making any changes |

**Restore to same project** (default `--dir` works automatically):
```cmd
python supabase-auth-copy.py restore --project-ref abcdefghijklmnop --token sbp_xxxxxxxxxxxx
```

**Restore to a DIFFERENT project** — point `--dir` at the source backup:
```cmd
python supabase-auth-copy.py restore --project-ref newprojectref --token sbp_xxxxxxxxxxxx --dir auth_backup_abcdefghijklmnop
```

**Restore only third-party providers (skip general auth config):**
```cmd
python supabase-auth-copy.py restore --project-ref newprojectref --token sbp_xxxxxxxxxxxx --dir auth_backup_abcdefghijklmnop --skip-config
```

**Restore only auth config (skip providers):**
```cmd
python supabase-auth-copy.py restore --project-ref newprojectref --token sbp_xxxxxxxxxxxx --dir auth_backup_abcdefghijklmnop --skip-providers
```

**Preview without making any changes:**
```cmd
python supabase-auth-copy.py restore --project-ref newprojectref --token sbp_xxxxxxxxxxxx --dir auth_backup_abcdefghijklmnop --dry-run
```

> 💡 Providers already matching on the target (same type + pool ID + region) are automatically skipped — no duplicates will be created.

---

## 🌍 Environment Variables

| Variable | Equivalent flag | Description |
|----------|----------------|-------------|
| `SUPABASE_ACCESS_TOKEN` | `--token` | Personal Access Token |
| `SUPABASE_PROJECT_REF` | `--project-ref` | Project reference ID |

```cmd
REM Command Prompt
set SUPABASE_ACCESS_TOKEN=sbp_xxxxxxxxxxxx
set SUPABASE_PROJECT_REF=abcdefghijklmnop
```

```powershell
# PowerShell
$env:SUPABASE_ACCESS_TOKEN="sbp_xxxxxxxxxxxx"
$env:SUPABASE_PROJECT_REF="abcdefghijklmnop"
```

---

## 🗂️ Backup Directory Structure

```
auth_backup_abcdefghijklmnop/
  manifest.json           # project_ref, backup_time, provider count, stripped keys
  auth_config.json        # full auth config blob (sensitive keys removed)
  third_party_auth.json   # list of third-party provider configs
```

---

## 📦 What Gets Backed Up

| Item | Backed up | Notes |
|------|-----------|-------|
| Site URL, redirect URLs | ✅ | |
| JWT expiry | ✅ | |
| Email/password settings | ✅ | |
| Session config | ✅ | |
| Rate limits | ✅ | |
| MFA settings | ✅ | |
| OAuth provider enabled flags | ✅ | Client IDs backed up; **secrets stripped** |
| Amazon Cognito User Pool integrations | ✅ | Pool ID + region |
| JWT secret | ❌ | Sensitive — set manually |
| OAuth client secrets | ❌ | Sensitive — set manually |
| SMTP password | ❌ | Sensitive — set manually |
| User data | ❌ | Not part of auth config |
| RLS policies | ❌ | Not part of auth config |

---

## 🔄 Typical Workflow: Clone Auth Config to a New Project

```cmd
REM 1. Back up source
python supabase-auth-copy.py backup --project-ref sourceref --token sbp_xxxxxxxxxxxx

REM 2. Preview what will be restored
python supabase-auth-copy.py restore --project-ref targetref --token sbp_xxxxxxxxxxxx --dir auth_backup_sourceref --dry-run

REM 3. Restore
python supabase-auth-copy.py restore --project-ref targetref --token sbp_xxxxxxxxxxxx --dir auth_backup_sourceref

REM 4. Manually set secrets on target project (JWT secret, OAuth secrets, SMTP password)
REM    via Supabase Dashboard > Authentication > Settings
```

---

## ⚠️ Important Notes

- 🔒 **Sensitive keys are stripped from backups** — JWT secret, OAuth client secrets, SMTP password and other sensitive values are never written to disk or restored. Set them manually on the target.
- 🔗 **Provider deduplication** — the restore command checks existing providers and skips any that already match (same type + pool ID + region).
- 📋 **Auth config is PATCHed** — only the keys present in the backup are applied; other settings on the target are left untouched.
- 🌐 **Site URL** — if you're copying to a different project with a different domain, update `site_url` and redirect URLs on the target after restoring.
