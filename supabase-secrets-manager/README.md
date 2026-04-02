# 🔑 supabase-secrets-manager

Add, update, delete, and list Supabase Edge Function secrets on any project using the Management API. Values are entered interactively (hidden as you type) or loaded from a `.env` file.

> ⚠️ The Supabase API **never returns secret values** — only names. This tool cannot read existing values out of a project. It can only list names, set new values, or delete secrets.

---

## 📋 Prerequisites

- 🐍 **Python 3.8+**
- 📦 **requests** library — `pip install requests`
- 🔑 **Supabase Personal Access Token (PAT)** — see [🔑 How to Get Your Token](../README.md#-how-to-get-your-token) in the root README
- 🆔 **Supabase Project Reference ID** — the alphanumeric string in your project dashboard URL:
  `https://supabase.com/dashboard/project/abcdefghijklmnop` → ref is `abcdefghijklmnop`

---

## ⚡ Quick Start

```cmd
REM See what secrets exist on a project
python supabase-secrets-manager.py list --project-ref abcdefghijklmnop --token sbp_xxxxxxxxxxxx

REM Interactively add or update secrets (values hidden as you type)
python supabase-secrets-manager.py set --project-ref abcdefghijklmnop --token sbp_xxxxxxxxxxxx

REM Push all secrets from a .env file
python supabase-secrets-manager.py push --project-ref abcdefghijklmnop --token sbp_xxxxxxxxxxxx --env-file .env.production
```

---

## 🔧 Commands & Parameters

### `list` — List all secret names

Prints every secret name on the project. **Values are never returned by the API.**

```cmd
python supabase-secrets-manager.py list --project-ref abcdefghijklmnop --token sbp_xxxxxxxxxxxx
```

**Example output:**
```
  Secrets on project: abcdefghijklmnop

  🔑 OPENAI_API_KEY
  🔑 STRIPE_SECRET_KEY
  🔑 WEBHOOK_SECRET

  Total: 3 secret(s)
```

---

### `set` — Add or update secrets interactively

Prompts for secret names and values. Values are **hidden as you type** (like a password prompt). Existing secrets with the same name are overwritten.

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `--project-ref` | Yes* | `SUPABASE_PROJECT_REF` | Project reference ID |
| `--token` | Yes* | `SUPABASE_ACCESS_TOKEN` | Personal Access Token |
| `--names` | No | *(prompted)* | Space-separated secret names — skips the name prompt, only asks for values |
| `--dry-run` | No | `false` | Preview what would be set without making changes |

```cmd
REM Fully interactive — prompts for both name and value
python supabase-secrets-manager.py set --project-ref abcdefghijklmnop --token sbp_xxxxxxxxxxxx
```

```
  Set secrets on project: abcdefghijklmnop
  Values are hidden as you type. Press Enter with no value to skip a secret.

  Enter secrets one at a time. Leave the name blank to finish.

  Secret name (blank to finish): OPENAI_API_KEY
  Value for 'OPENAI_API_KEY':
  Secret name (blank to finish): STRIPE_SECRET_KEY
  Value for 'STRIPE_SECRET_KEY':
  Secret name (blank to finish):

  Setting 2 secret(s):
    🔑 OPENAI_API_KEY
    🔑 STRIPE_SECRET_KEY

  ✅ 2 secret(s) set successfully.
```

```cmd
REM Provide names up front — only prompts for each value
python supabase-secrets-manager.py set --project-ref abcdefghijklmnop --token sbp_xxxxxxxxxxxx --names OPENAI_API_KEY STRIPE_SECRET_KEY
```

---

### `delete` — Delete secrets by name

Deletes one or more secrets. Asks for confirmation before proceeding.

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `--project-ref` | Yes* | `SUPABASE_PROJECT_REF` | Project reference ID |
| `--token` | Yes* | `SUPABASE_ACCESS_TOKEN` | Personal Access Token |
| `--names` | Yes | — | Space-separated secret names to delete |
| `--dry-run` | No | `false` | Preview what would be deleted without making changes |

```cmd
REM Delete a single secret
python supabase-secrets-manager.py delete --project-ref abcdefghijklmnop --token sbp_xxxxxxxxxxxx --names OLD_SECRET

REM Delete multiple secrets
python supabase-secrets-manager.py delete --project-ref abcdefghijklmnop --token sbp_xxxxxxxxxxxx --names OLD_KEY_1 OLD_KEY_2

REM Preview without deleting
python supabase-secrets-manager.py delete --project-ref abcdefghijklmnop --token sbp_xxxxxxxxxxxx --names OLD_SECRET --dry-run
```

---

### `push` — Push secrets from a `.env` file

Reads a `.env` file and sets all key=value pairs as secrets on the project. Useful for copying secrets from one project to another when you have the values in a file.

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `--project-ref` | Yes* | `SUPABASE_PROJECT_REF` | Project reference ID |
| `--token` | Yes* | `SUPABASE_ACCESS_TOKEN` | Personal Access Token |
| `--env-file` | No | `.env` | Path to the `.env` file to read from |
| `--dry-run` | No | `false` | Preview what would be pushed without making changes |

```cmd
REM Push from default .env file in current directory
python supabase-secrets-manager.py push --project-ref abcdefghijklmnop --token sbp_xxxxxxxxxxxx

REM Push from a specific file
python supabase-secrets-manager.py push --project-ref abcdefghijklmnop --token sbp_xxxxxxxxxxxx --env-file .env.production

REM Preview without pushing
python supabase-secrets-manager.py push --project-ref abcdefghijklmnop --token sbp_xxxxxxxxxxxx --env-file .env.production --dry-run
```

**Example output:**
```
  Push secrets from .env file to project: abcdefghijklmnop
  File: J:\Dev\MyProject\.env.production

  Setting 4 secret(s):
    🔑 OPENAI_API_KEY
    🔑 STRIPE_SECRET_KEY
    🔑 WEBHOOK_SECRET
    🔑 DATABASE_URL

  ✅ 4 secret(s) pushed successfully.
```

**Supported `.env` file format:**
```
# Comments are ignored
OPENAI_API_KEY=sk-xxxxxxxxxxxx
STRIPE_SECRET_KEY="sk_live_xxxx"   # quoted values are supported
WEBHOOK_SECRET='my-secret-value'   # single quotes too
```

---

## 🔄 Typical Workflow: Copy Secrets Between Projects

Because the API never returns values, a full copy from project A to project B requires you to have the values. The recommended approach:

**If you have a `.env` file with the values:**
```cmd
python supabase-secrets-manager.py push --project-ref targetref --token sbp_xxxxxxxxxxxx --env-file .env.production
```

**If you don't have a file — list source names first, then type each value for the target:**
```cmd
REM Step 1: See what secrets exist on the source
python supabase-secrets-manager.py list --project-ref sourceref --token sbp_xxxxxxxxxxxx

REM Step 2: Set each one on the target (prompted interactively)
python supabase-secrets-manager.py set --project-ref targetref --token sbp_xxxxxxxxxxxx --names OPENAI_API_KEY STRIPE_SECRET_KEY WEBHOOK_SECRET
```

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

Once set, commands simplify to:
```cmd
python supabase-secrets-manager.py list
python supabase-secrets-manager.py set --names MY_KEY
```

---

## ⚠️ Important Notes

- 🔒 **Secret values are NEVER returned by the API** — this is by design. You cannot use this tool to export existing secret values from a project.
- ✏️ **`set` always upserts** — if a secret with the same name already exists, it will be overwritten with the new value.
- 🗑️ **`delete` requires confirmation** — you must type `YES` to proceed. Use `--dry-run` to preview first.
- 📄 **`.env` files are never uploaded** — the `push` command reads the file locally and sends values via the API. The file itself is never transmitted.
