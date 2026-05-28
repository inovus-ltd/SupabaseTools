# 🛠️ SupabaseTools

A collection of tools for managing, automating, and maintaining [Supabase](https://supabase.com) projects.

## ⬇️ Install (No Python Required)

Install all tools with a single command — no Python needed.

**Windows** (run PowerShell as Administrator):
```powershell
irm https://raw.githubusercontent.com/inovus-ltd/SupabaseTools/master/install.ps1 | iex
```

**macOS / Linux:**
```bash
curl -fsSL https://raw.githubusercontent.com/inovus-ltd/SupabaseTools/master/install.sh | sudo bash
```

All 4 tools are downloaded from the latest GitHub Release and placed on your system PATH. Open a new terminal and they're ready to use.

---

Or download individual executables manually from the [**Releases page**](../../releases/latest):

| Tool | Windows | macOS | Linux |
|------|---------|-------|-------|
| supabase-functions-backup | [⬇ .exe](../../releases/latest/download/supabase-functions-backup-windows.exe) | [⬇ binary](../../releases/latest/download/supabase-functions-backup-macos) | [⬇ binary](../../releases/latest/download/supabase-functions-backup-linux) |
| supabase-storage-copy | [⬇ .exe](../../releases/latest/download/supabase-storage-copy-windows.exe) | [⬇ binary](../../releases/latest/download/supabase-storage-copy-macos) | [⬇ binary](../../releases/latest/download/supabase-storage-copy-linux) |
| supabase-auth-copy | [⬇ .exe](../../releases/latest/download/supabase-auth-copy-windows.exe) | [⬇ binary](../../releases/latest/download/supabase-auth-copy-macos) | [⬇ binary](../../releases/latest/download/supabase-auth-copy-linux) |
| supabase-secrets-manager | [⬇ .exe](../../releases/latest/download/supabase-secrets-manager-windows.exe) | [⬇ binary](../../releases/latest/download/supabase-secrets-manager-macos) | [⬇ binary](../../releases/latest/download/supabase-secrets-manager-linux) |

> **Windows:** If Windows Defender warns about the file, click **More info → Run anyway**.
>
> **macOS / Linux:** Make the binary executable first: `chmod +x supabase-functions-backup-macos`

Once downloaded, use exactly like the Python scripts — just replace `python supabase-functions-backup.py` with `supabase-functions-backup-windows.exe`:

```cmd
supabase-functions-backup-windows.exe list --project-ref abcdefghijklmnop --token sbp_xxxx
supabase-storage-copy-windows.exe backup --project-ref abcdefghijklmnop --token sbp_xxxx --service-key eyJ...
supabase-auth-copy-windows.exe restore --project-ref newref --token sbp_xxxx --dir auth_backup_abcdefghijklmnop
supabase-secrets-manager-windows.exe list --project-ref abcdefghijklmnop --token sbp_xxxx
```

---

## 📦 Tools

| Tool | Description |
|------|-------------|
| [`supabase-functions-backup`](./supabase-functions-backup/README.md) | 🔄 Backup and restore Supabase Edge Functions using the Management API |
| [`supabase-storage-copy`](./supabase-storage-copy/README.md) | 🗄️ Backup and restore Supabase Storage buckets (config + files) across projects |
| [`supabase-secrets-manager`](./supabase-secrets-manager/README.md) | 🔑 List, add, update, and delete Edge Function secrets on any project |
| [`supabase-auth-copy`](./supabase-auth-copy/README.md) | 🔐 Backup and restore Auth config and Third-Party Auth providers (e.g. Amazon Cognito) across projects |

## ✅ Prerequisites

- 🐍 **Python 3.8+** — [python.org/downloads](https://www.python.org/downloads/)
- 📦 **pip** — bundled with Python 3.4+; upgrade with `python -m pip install --upgrade pip`
- 🌐 **`requests` library** — used by all HTTP-based tools: `pip install requests`
- 🔑 **Supabase Personal Access Token (PAT)** — see [🔑 How to Get Your Token](#-how-to-get-your-token) below
- 🗝️ **Supabase Service Role Key** *(storage tools only)* — found in *Project Settings → API → Project API Keys → service_role*
- 🆔 **Supabase Project Reference ID** — the alphanumeric string in your project's dashboard URL:
  `https://supabase.com/dashboard/project/abcdefghijklmnop` → ref is `abcdefghijklmnop`
  Also found under *Project Settings → General* in the Supabase dashboard.

## 🔑 How to Get Your Token

1. Log in to [supabase.com](https://supabase.com)
2. Click your **avatar** (top-right) → **Account Preferences**
3. Go to [Account Preferences → Access Tokens](https://supabase.com/dashboard/account/tokens)
4. Click **Generate new token**, give it a descriptive name (e.g. `backup-tool`), and copy the value

> ⚠️ The token is shown **only once** — copy it immediately and store it somewhere safe (e.g. a password manager or a local `.env` file).
>
> 🔒 This is an **account-level** token with access to **all projects** in your Supabase account. Treat it like a password and never commit it to version control.

## 🚀 Getting Started

**1. Clone this repository:**

```bash
git clone https://github.com/inovus-ltd/SupabaseTools.git
cd SupabaseTools
```

**2. (Recommended) Create and activate a virtual environment:**

```bash
# Windows
python -m venv .venv
.venv\Scripts\activate

# macOS / Linux
python -m venv .venv
source .venv/bin/activate
```

**3. Install shared dependencies:**

```bash
pip install requests
```

**4. Set your credentials as environment variables** to avoid passing them on every call:

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

**5.** Navigate to the tool you want to use and follow its `README.md`.

## 🔨 Build Executables Locally

If you want to build the standalone executables yourself (e.g. to test changes before a release):

**Prerequisites:**
```cmd
pip install -r requirements-build.txt
```

**Build all tools (Command Prompt):**
```cmd
build-all.bat
```

**Build all tools (PowerShell):**
```powershell
.\build-all.ps1
```

Executables are written to `dist\`. The `build\` and `dist\` directories are gitignored.

**Releasing a new version:** Push a tag and GitHub Actions builds all platform binaries automatically:
```cmd
git tag v1.0.0
git push origin v1.0.0
```

---

## 🤝 Contributing

Each tool lives in its own subdirectory. When adding a new tool:

- Create a new subdirectory with a descriptive name (e.g. `supabase-migrate`)
- Include a `README.md` covering prerequisites, parameters, usage, and examples
- Add an entry to the table above

## 🔒 Security

- **Never commit tokens or project refs** to version control — use environment variables or a `.env` file (already gitignored)
- Supabase Personal Access Tokens have **account-level access** to all your projects — treat them like passwords
