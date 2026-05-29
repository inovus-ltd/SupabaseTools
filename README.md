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
> ⚠️ **Windows Defender warning?** You may see a "Windows protected your PC" SmartScreen prompt the first time you run one of these tools. This happens because the executables are not commercially code-signed — not because they contain anything harmful. The full source code for every tool is right here in this repository and is openly auditable.
>
> To proceed: click **More info** → **Run anyway**.
>
> 🔐 **Security-conscious users:** If code signing matters to your organisation, you're warmly encouraged to **fork this repository**, add your own code signing certificate to the GitHub Actions workflow, and distribute your own signed builds to your team. The build pipeline is already set up — it just needs a certificate.

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

## � How to Clone a Supabase Project

Want to duplicate a project — for a staging environment, a new customer, or a safe place to test changes? Here's the complete step-by-step process.

> ⏱️ **How long does this take?** About 10–20 minutes depending on your database and storage size.

---

### Step 1 — Restore the Database

The database has to be done first through the Supabase dashboard. Everything else (functions, storage, auth) gets copied using SupabaseTools afterwards.

1. Open the **source project** (the one you want to clone) in the [Supabase dashboard](https://supabase.com/dashboard)
2. In the left menu go to **Database → Backups**
3. Find a recent backup and click **Restore to a new project**
4. Set a **new project name** and a **new database password** — store the password somewhere safe
5. Click through and wait — this takes a few minutes

> 💡 During restore Supabase will show you what the new project will inherit: all your tables, data, views, functions, indexes, roles and permissions.

**What the database restore does NOT copy** — you'll handle these in the next steps:

| ❌ Not copied automatically | ✅ Copied by SupabaseTools |
|----------------------------|--------------------------|
| Edge Functions | ✅ Step 3 below |
| Storage buckets & files | ✅ Step 4 below |
| Auth configuration | ✅ Step 5 below |
| Edge Function secrets | ✅ Step 6 below |

---

### Step 2 — Get Set Up

**Install SupabaseTools** if you haven't already (see [Install in 30 Seconds](#-install-in-30-seconds) above).

**Gather the things you'll need before running any commands:**

#### 🔑 Your Personal Access Token
Go to [supabase.com/dashboard/account/tokens](https://supabase.com/dashboard/account/tokens), generate a token, and copy it. You'll use this for every command below.

#### 🆔 Two Project Reference IDs
You need the ref for the **source** (original) project and the **target** (new) project.

Find each one in the dashboard URL:
```
https://supabase.com/dashboard/project/abcdefghijklmnop
                                        ↑ this is the ref
```

#### 🗝️ Two Service Role Keys *(for Storage only)*
In each project: go to **Project Settings → API** and copy the `service_role` key.
You need one from the **source** project and one from the **target** project.

> 🔒 Keep these safe — service role keys bypass Row Level Security and have full database access.

---

### Step 3 — Copy Edge Functions

```
supabase-functions-backup backup --project-ref SOURCE_REF --token YOUR_TOKEN
supabase-functions-backup restore --project-ref TARGET_REF --token YOUR_TOKEN --dir edge_functions_backup_SOURCE_REF
```

**What gets copied:** Function source code, metadata, JWT settings, import maps, entrypoint config.

**What doesn't:** Secrets — handled separately in Step 6.

---

### Step 4 — Copy Storage Buckets & Files

```
supabase-storage-copy backup --project-ref SOURCE_REF --token YOUR_TOKEN --service-key SOURCE_SERVICE_KEY
supabase-storage-copy restore --project-ref TARGET_REF --token YOUR_TOKEN --service-key TARGET_SERVICE_KEY --dir storage_backup_SOURCE_REF --mode overwrite
```

> ⚠️ Make sure you use the **target** project's service role key for the restore command, not the source.

**What gets copied:** All buckets, all files, folder structure, public/private settings, MIME types.

**What doesn't:** Storage RLS policies — recreate these from your migrations or manually in the dashboard.

---

### Step 5 — Copy Auth Configuration

```
supabase-auth-copy backup --project-ref SOURCE_REF --token YOUR_TOKEN
supabase-auth-copy restore --project-ref TARGET_REF --token YOUR_TOKEN --dir auth_backup_SOURCE_REF
```

**What gets copied:** Site URL, redirect URLs, JWT expiry, MFA settings, email/session config, OAuth provider on/off settings, Amazon Cognito integrations.

**What doesn't:** Sensitive secrets (JWT secret, OAuth client secrets, SMTP password) — these are intentionally stripped for security. Re-enter them manually in **Project Settings → Auth** on the new project.

---

### Step 6 — Copy Edge Function Secrets

Supabase's API doesn't let you export secret *values* — only names. So you need to have the values somewhere (like a `.env` file or a password manager).

**See what secrets the source project has:**
```
supabase-secrets-manager list --project-ref SOURCE_REF --token YOUR_TOKEN
```

**Option A — push from a `.env` file** (easiest if you have one):
```
supabase-secrets-manager push --project-ref TARGET_REF --token YOUR_TOKEN --env-file .env.production
```

**Option B — enter them interactively:**
```
supabase-secrets-manager set --project-ref TARGET_REF --token YOUR_TOKEN
```

---

### Step 7 — Final Checks ✅

Run through this checklist before pointing any apps at the new project:

**Database**
- [ ] Tables and data look correct
- [ ] RLS policies are in place

**Edge Functions**
- [ ] Functions show up in the dashboard
- [ ] Secrets are configured
- [ ] Test a function call — does it respond correctly?

**Storage**
- [ ] Buckets exist with correct public/private settings
- [ ] A few files are accessible

**Auth**
- [ ] Can you log in?
- [ ] OAuth providers work (check redirect URLs point to the new project URL)
- [ ] Password reset / confirmation emails are sending

**Your Application**
- [ ] Update your app's environment variables to the new project URL and anon key
- [ ] No hardcoded references to the old project ref anywhere
- [ ] Third-party webhooks, OAuth callbacks, and SMTP settings updated

> 💡 **New project URL and API keys** are found in the new project under **Project Settings → API**.

---

### Full Clone Command Reference

Here's every command in one place — just substitute your values:

```
# Replace these with your real values:
# SOURCE_REF     = project ref of the project you're cloning FROM
# TARGET_REF     = project ref of the newly restored project
# YOUR_TOKEN     = your Personal Access Token (sbp_...)
# SOURCE_KEY     = service_role key from the SOURCE project
# TARGET_KEY     = service_role key from the TARGET project

supabase-functions-backup backup  --project-ref SOURCE_REF --token YOUR_TOKEN
supabase-functions-backup restore --project-ref TARGET_REF --token YOUR_TOKEN --dir edge_functions_backup_SOURCE_REF

supabase-storage-copy backup  --project-ref SOURCE_REF --token YOUR_TOKEN --service-key SOURCE_KEY
supabase-storage-copy restore --project-ref TARGET_REF --token YOUR_TOKEN --service-key TARGET_KEY --dir storage_backup_SOURCE_REF --mode overwrite

supabase-auth-copy backup  --project-ref SOURCE_REF --token YOUR_TOKEN
supabase-auth-copy restore --project-ref TARGET_REF --token YOUR_TOKEN --dir auth_backup_SOURCE_REF

supabase-secrets-manager list --project-ref SOURCE_REF --token YOUR_TOKEN
supabase-secrets-manager push --project-ref TARGET_REF --token YOUR_TOKEN --env-file .env.production
```

---

## �📖 Detailed Guides

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
