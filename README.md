# 🛠️ SupabaseTools

**Command-line tools for backing up, copying, and managing your [Supabase](https://supabase.com) projects.**

Migrate storage buckets, clone auth settings, copy Edge Functions, and manage secrets — all from your terminal. No coding required.

---

## 🚀 Install in 30 Seconds

No Python. No dependencies. Just paste one command and you're done.

**Windows** — open PowerShell as Administrator and run:

```powershell
irm https://raw.githubusercontent.com/inovus-ltd/SupabaseTools/master/install.ps1 | iex
```

**macOS / Linux:**

```bash
curl -fsSL https://raw.githubusercontent.com/inovus-ltd/SupabaseTools/master/install.sh | sudo bash
```

That's it. All 4 tools download automatically and are instantly available from any terminal window.

> 💡 **Windows tip:** To open PowerShell as Administrator — right-click the Start button → *Windows PowerShell (Admin)*
>
> ⚠️ **Windows Defender warning?** If you see "Windows protected your PC", click **More info** then **Run anyway**. This is normal for unsigned executables downloaded from the internet.

---

## 🧰 What's Included

| Tool | What it does |
|------|-------------|
| [**supabase-functions-backup**](./supabase-functions-backup/README.md) | Back up and restore your Edge Functions between projects |
| [**supabase-storage-copy**](./supabase-storage-copy/README.md) | Back up and restore Storage buckets and all their files |
| [**supabase-auth-copy**](./supabase-auth-copy/README.md) | Copy your Auth settings and third-party providers (e.g. Amazon Cognito) to another project |
| [**supabase-secrets-manager**](./supabase-secrets-manager/README.md) | View and manage Edge Function secrets across projects |

---

## 🔑 Before You Start — Get Your Credentials

Every tool needs two things: a **Personal Access Token** and your **Project Reference ID**.

### Personal Access Token (PAT)

This is the password that lets the tools talk to your Supabase account.

1. Go to [supabase.com/dashboard/account/tokens](https://supabase.com/dashboard/account/tokens)
2. Click **Generate new token**
3. Give it a name like `backup-tool` and click **Generate**
4. **Copy it immediately** — it's only shown once

> 🔒 This token has access to **all projects** in your account. Keep it safe — treat it like a password and never share it or commit it to git.

### Project Reference ID

This is the unique ID for each of your Supabase projects. You'll need it for the source project you're backing up from, and the target project you're restoring to.

**Find it here:** Open your project in the Supabase dashboard. Look at the URL:

```
https://supabase.com/dashboard/project/abcdefghijklmnop
                                        ↑ this is your project ref
```

Or go to **Project Settings → General** and it's listed there as "Reference ID".

---

## ⚡ Quick Examples

Once installed, here's what you can do. Replace `YOUR_REF` and `YOUR_TOKEN` with your real values.

### Back up Edge Functions
```
supabase-functions-backup backup --project-ref YOUR_REF --token YOUR_TOKEN
```

### Copy Storage buckets from one project to another
```
supabase-storage-copy backup --project-ref SOURCE_REF --token YOUR_TOKEN --service-key YOUR_SERVICE_KEY
supabase-storage-copy restore --project-ref TARGET_REF --token YOUR_TOKEN --service-key TARGET_SERVICE_KEY --dir storage_backup_SOURCE_REF
```

### Clone Auth settings to a new project
```
supabase-auth-copy backup --project-ref SOURCE_REF --token YOUR_TOKEN
supabase-auth-copy restore --project-ref TARGET_REF --token YOUR_TOKEN --dir auth_backup_SOURCE_REF
```

### List Edge Function secrets
```
supabase-secrets-manager list --project-ref YOUR_REF --token YOUR_TOKEN
```

> 💡 **Tip:** Every command supports `--help` for full usage details, and `--dry-run` to preview what will happen before making any changes.

---

## 📖 Detailed Guides

Each tool has its own README with full documentation, all commands, parameters, and real example output:

- 📄 [supabase-functions-backup — full guide](./supabase-functions-backup/README.md)
- 📄 [supabase-storage-copy — full guide](./supabase-storage-copy/README.md)
- 📄 [supabase-auth-copy — full guide](./supabase-auth-copy/README.md)
- 📄 [supabase-secrets-manager — full guide](./supabase-secrets-manager/README.md)

---

## 🪟 Prefer to Download Manually?

If you'd rather download individual tools instead of using the installer:

| Tool | Windows | macOS | Linux |
|------|---------|-------|-------|
| supabase-functions-backup | [⬇ .exe](../../releases/latest/download/supabase-functions-backup-windows.exe) | [⬇ binary](../../releases/latest/download/supabase-functions-backup-macos) | [⬇ binary](../../releases/latest/download/supabase-functions-backup-linux) |
| supabase-storage-copy | [⬇ .exe](../../releases/latest/download/supabase-storage-copy-windows.exe) | [⬇ binary](../../releases/latest/download/supabase-storage-copy-macos) | [⬇ binary](../../releases/latest/download/supabase-storage-copy-linux) |
| supabase-auth-copy | [⬇ .exe](../../releases/latest/download/supabase-auth-copy-windows.exe) | [⬇ binary](../../releases/latest/download/supabase-auth-copy-macos) | [⬇ binary](../../releases/latest/download/supabase-auth-copy-linux) |
| supabase-secrets-manager | [⬇ .exe](../../releases/latest/download/supabase-secrets-manager-windows.exe) | [⬇ binary](../../releases/latest/download/supabase-secrets-manager-macos) | [⬇ binary](../../releases/latest/download/supabase-secrets-manager-linux) |

Save the file somewhere on your computer, then run it from your terminal in that folder.

**macOS / Linux only** — make it executable first:
```bash
chmod +x supabase-functions-backup-macos
./supabase-functions-backup-macos list --project-ref YOUR_REF --token YOUR_TOKEN
```

---

## 🛠️ Running from Source (Developers)

If you want to run the Python scripts directly or contribute to the project:

**1. Clone the repo:**
```bash
git clone https://github.com/inovus-ltd/SupabaseTools.git
cd SupabaseTools
```

**2. Install the one dependency:**
```bash
pip install requests
```

**3. Run any tool directly:**
```bash
python supabase-functions-backup/supabase-functions-backup.py list --project-ref YOUR_REF --token YOUR_TOKEN
```

**Building executables locally:**
```powershell
pip install -r requirements-build.txt
.\build-all.ps1
```

**Publishing a new release** — just push a version tag and GitHub Actions builds everything automatically:
```bash
git tag v1.2.0
git push origin v1.2.0
```

---

## 🔒 Security Notes

- **Tokens are never stored by these tools** — they're only used for the duration of each command
- **Never commit your token** to version control — use environment variables instead:
  ```powershell
  # PowerShell — set once per session, no need to pass --token every time
  $env:SUPABASE_ACCESS_TOKEN="sbp_your_token_here"
  ```
  ```bash
  # macOS / Linux
  export SUPABASE_ACCESS_TOKEN=sbp_your_token_here
  ```
- **Backups are local** — nothing is sent anywhere except directly to/from your Supabase projects via their official API
