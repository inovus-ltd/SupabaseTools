#!/usr/bin/env python3
"""
Supabase Auth Config Copy Tool
================================

Backup and restore Supabase Auth configuration and Third-Party Auth providers
(e.g. Amazon Cognito) from one project to another using the Management API.

Covers two separate API surfaces:
  1. Auth config  -- GET/PATCH /v1/projects/{ref}/config/auth
     Includes: JWT settings, email/password settings, session config, rate
     limits, URL config, MFA settings, email templates, OAuth providers, etc.

  2. Third-party auth providers -- GET/POST/DELETE
                                   /v1/projects/{ref}/config/auth/third-party-auth
     Includes: Amazon Cognito User Pool integrations (and any future providers
     Supabase adds to this endpoint).

Requirements:
  - Python 3.8+
  - requests library (pip install requests)
  - A Supabase Personal Access Token (PAT):
      https://supabase.com/dashboard/account/tokens

Usage:
  python supabase-auth-copy.py list    --project-ref <ref> --token <pat>
  python supabase-auth-copy.py backup  --project-ref <ref> --token <pat>
  python supabase-auth-copy.py restore --project-ref <ref> --token <pat> --dir <backup-dir>

Environment variables (alternative to CLI flags):
  SUPABASE_ACCESS_TOKEN  - Your PAT
  SUPABASE_PROJECT_REF   - The project reference ID
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    import requests
except ImportError:
    print("ERROR: 'requests' library is required. Install it with: pip install requests")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MANAGEMENT_API_BASE = "https://api.supabase.com/v1"
DEFAULT_BACKUP_DIR_PREFIX = "auth_backup"

# Courtesy delay between API calls.
REQUEST_DELAY_SECONDS = 0.2

# Auth config keys that contain sensitive secrets — excluded from backup/restore.
SENSITIVE_AUTH_KEYS = {
    "jwt_secret",
    "smtp_pass",
    "external_github_secret",
    "external_google_secret",
    "external_apple_secret",
    "external_azure_secret",
    "external_discord_secret",
    "external_facebook_secret",
    "external_gitlab_secret",
    "external_keycloak_secret",
    "external_linkedin_oidc_secret",
    "external_notion_secret",
    "external_slack_oidc_secret",
    "external_spotify_secret",
    "external_twitch_secret",
    "external_twitter_secret",
    "external_workos_secret",
    "external_zoom_secret",
}

# Auth config keys that require SMTP to be fully configured before they can be
# set. Sending these when SMTP isn't set up on the target causes a 401 error.
# They are saved in the backup but skipped during restore.
SMTP_DEPENDENT_KEYS = {
    "smtp_admin_email",
    "smtp_host",
    "smtp_port",
    "smtp_user",
    "smtp_pass",
    "smtp_sender_name",
    "smtp_max_frequency",
    "rate_limit_email_sent",
    "mailer_secure_email_change_enabled",
}

# Keys returned by the API that are read-only or server-managed — sending
# them back in a PATCH causes errors or is silently ignored.
READONLY_AUTH_KEYS = {
    "id",
    "project_id",
    "created_at",
    "updated_at",
    "jwt_secret",
    "uri_allow_list",  # managed separately via redirect URLs
}


# ---------------------------------------------------------------------------
# API client
# ---------------------------------------------------------------------------

class SupabaseAuthAPI:
    """
    Thin wrapper around the Supabase Management API auth config endpoints.
    """

    def __init__(self, token: str, project_ref: str):
        """
        Initialise the API client.

        Args:
            token (str): Supabase Personal Access Token.
            project_ref (str): Supabase project reference ID.
        """
        self.project_ref = project_ref
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        })

    # -- Auth config ----------------------------------------------------------

    def get_auth_config(self) -> dict:
        """
        Get the full auth configuration for the project.

        Returns:
            dict: Auth config blob from the API.
        """
        url = f"{MANAGEMENT_API_BASE}/projects/{self.project_ref}/config/auth"
        resp = self.session.get(url)
        if resp.status_code >= 400:
            raise RuntimeError(
                f"Get auth config failed (HTTP {resp.status_code}): {resp.text}"
            )
        return resp.json()

    def update_auth_config(self, config: dict) -> dict:
        """
        Update the auth configuration for the project.

        Args:
            config (dict): Partial or full auth config to apply (PATCH semantics).

        Returns:
            dict: Updated auth config from the API.
        """
        url = f"{MANAGEMENT_API_BASE}/projects/{self.project_ref}/config/auth"
        resp = self.session.patch(url, json=config)
        if resp.status_code >= 400:
            raise RuntimeError(
                f"Update auth config failed (HTTP {resp.status_code}): {resp.text}"
            )
        return resp.json()

    # -- Third-party auth providers -------------------------------------------

    def list_third_party_providers(self) -> list:
        """
        List all third-party auth provider integrations on the project.

        Returns:
            list: List of provider dicts (type, id, config fields).
        """
        url = f"{MANAGEMENT_API_BASE}/projects/{self.project_ref}/config/auth/third-party-auth"
        resp = self.session.get(url)
        if resp.status_code >= 400:
            raise RuntimeError(
                f"List third-party providers failed (HTTP {resp.status_code}): {resp.text}"
            )
        data = resp.json()
        # API returns either a list directly or a dict with a key
        if isinstance(data, list):
            return data
        return data.get("third_party_auth", data.get("providers", []))

    def add_third_party_provider(self, provider: dict) -> dict:
        """
        Add a third-party auth provider integration to the project.

        Args:
            provider (dict): Provider config (type, cognito_user_pool_id, etc.).

        Returns:
            dict: Created provider from the API.
        """
        url = f"{MANAGEMENT_API_BASE}/projects/{self.project_ref}/config/auth/third-party-auth"
        resp = self.session.post(url, json=provider)
        if resp.status_code >= 400:
            raise RuntimeError(
                f"Add third-party provider failed (HTTP {resp.status_code}): {resp.text}"
            )
        return resp.json()

    def delete_third_party_provider(self, provider_id: str) -> None:
        """
        Delete a third-party auth provider integration by its ID.

        Args:
            provider_id (str): The provider's ID as returned by list_third_party_providers.
        """
        url = (
            f"{MANAGEMENT_API_BASE}/projects/{self.project_ref}"
            f"/config/auth/third-party-auth/{provider_id}"
        )
        resp = self.session.delete(url)
        if resp.status_code >= 400:
            raise RuntimeError(
                f"Delete third-party provider '{provider_id}' failed "
                f"(HTTP {resp.status_code}): {resp.text}"
            )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_cognito_issuer(oidc_issuer_url: str) -> tuple:
    """
    Extract (region, pool_id) from a Cognito OIDC issuer URL.

    The URL format is:
      https://cognito-idp.{region}.amazonaws.com/{pool_id}

    Args:
        oidc_issuer_url (str): The oidc_issuer_url field from the API.

    Returns:
        tuple: (region, pool_id) strings, or ('', '') if not parseable.
    """
    if not oidc_issuer_url:
        return "", ""
    try:
        # Strip trailing slash
        url = oidc_issuer_url.rstrip("/")
        # Path portion after the domain is the pool ID
        parts = url.split("/")
        pool_id = parts[-1]  # e.g. eu-west-2_aa7ucEcDs
        # Region is the subdomain segment: cognito-idp.{region}.amazonaws.com
        host = parts[2]  # e.g. cognito-idp.eu-west-2.amazonaws.com
        host_parts = host.split(".")
        region = host_parts[1] if len(host_parts) >= 3 else ""
        return region, pool_id
    except Exception:
        return "", ""


def _provider_label(p: dict) -> str:
    """
    Build a human-readable label for a third-party provider dict.

    Args:
        p (dict): Provider dict from the API.

    Returns:
        str: Display label.
    """
    ptype = p.get("type", "unknown").lower()
    if ptype == "cognito":
        # Reason: API returns oidc_issuer_url, not separate pool_id/region fields.
        # Pool ID and region are embedded in the URL.
        region, pool_id = _parse_cognito_issuer(p.get("oidc_issuer_url", ""))
        return f"Amazon Cognito  pool={pool_id}  region={region}"
    return f"{ptype}  {json.dumps({k: v for k, v in p.items() if k not in ('type', 'id', 'created_at', 'updated_at', 'inserted_at', 'resolved_jwks', 'resolved_at')})}"


def _strip_sensitive(config: dict) -> dict:
    """
    Remove known sensitive and read-only keys from an auth config dict before saving.

    Args:
        config (dict): Full auth config blob.

    Returns:
        dict: Config with sensitive/read-only keys removed.
    """
    exclude = SENSITIVE_AUTH_KEYS | READONLY_AUTH_KEYS
    return {k: v for k, v in config.items() if k not in exclude}


def _strip_for_restore(config: dict) -> dict:
    """
    Remove keys that cannot safely be PATCHed onto a target project.
    Strips sensitive keys, read-only keys, and SMTP-dependent keys that
    require SMTP to be pre-configured.

    Args:
        config (dict): Saved auth config blob.

    Returns:
        dict: Config safe to PATCH onto any project.
    """
    exclude = SENSITIVE_AUTH_KEYS | READONLY_AUTH_KEYS | SMTP_DEPENDENT_KEYS
    return {k: v for k, v in config.items() if k not in exclude}


def _build_provider_payload(p: dict) -> dict:
    """
    Build the POST payload for adding a third-party provider.

    The API accepts oidc_issuer_url (not cognito_user_pool_id/region).
    Strip server-managed fields (id, timestamps, resolved_jwks).

    Args:
        p (dict): Provider dict from backup.

    Returns:
        dict: Payload suitable for POST to third-party-auth endpoint.
    """
    skip = {"id", "created_at", "updated_at", "inserted_at", "resolved_at",
            "resolved_jwks", "cognito_user_pool_id", "cognito_user_pool_region"}
    return {k: v for k, v in p.items() if k not in skip and v is not None}


def _providers_equal(a: dict, b: dict) -> bool:
    """
    Check whether two provider dicts represent the same integration.
    Compares on oidc_issuer_url which uniquely identifies the provider.

    Args:
        a (dict): First provider.
        b (dict): Second provider.

    Returns:
        bool: True if they are functionally identical.
    """
    # Reason: both type+oidc_issuer_url together uniquely identify a provider.
    return (
        a.get("type") == b.get("type")
        and a.get("oidc_issuer_url") == b.get("oidc_issuer_url")
    )


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

def do_list(api: SupabaseAuthAPI):
    """
    Print the auth config summary and all third-party providers.

    Args:
        api (SupabaseAuthAPI): Authenticated API client.
    """
    print(f"\n  Auth configuration for project: {api.project_ref}\n")

    # Auth config summary
    try:
        config = api.get_auth_config()
        print("  ── Auth Config ──────────────────────────────────────────")
        interesting = {
            "site_url": "Site URL",
            "jwt_exp": "JWT expiry (seconds)",
            "disable_signup": "Signup disabled",
            "email_confirmations": "Email confirmations",
            "sms_provider": "SMS provider",
            "external_email_enabled": "Email auth enabled",
            "mailer_autoconfirm": "Auto-confirm emails",
            "mfa_totp_enroll_enabled": "MFA TOTP enroll",
            "mfa_totp_verify_enabled": "MFA TOTP verify",
        }
        for key, label in interesting.items():
            if key in config:
                print(f"    {label:<30} {config[key]}")
        time.sleep(REQUEST_DELAY_SECONDS)
    except RuntimeError as e:
        print(f"  WARNING: Could not fetch auth config: {e}")

    # Third-party providers
    print()
    print("  ── Third-Party Auth Providers ───────────────────────────")
    try:
        providers = api.list_third_party_providers()
        if not providers:
            print("    No third-party providers configured.")
        else:
            for p in providers:
                pid = p.get("id", "")
                label = _provider_label(p)
                print(f"    🔗 {label}")
                if pid:
                    print(f"       id: {pid}")
        print(f"\n    Total: {len(providers)} provider(s)")
    except RuntimeError as e:
        print(f"  WARNING: Could not fetch third-party providers: {e}")

    print()


def do_backup(api: SupabaseAuthAPI, project_ref: str, backup_dir: str):
    """
    Download the auth config and third-party providers to a local directory.

    Directory layout:
      <backup_dir>/
        manifest.json          # project_ref, backup_time, summary
        auth_config.json       # full auth config (sensitive keys stripped)
        third_party_auth.json  # list of third-party provider configs

    Args:
        api (SupabaseAuthAPI): Authenticated API client.
        project_ref (str): Source project reference ID.
        backup_dir (str): Directory to write backup into.
    """
    root = Path(backup_dir)
    root.mkdir(parents=True, exist_ok=True)

    print(f"\n  Backing up Auth config for project: {project_ref}")
    print(f"  Destination: {root.resolve()}\n")

    # 1. Auth config
    print("  Fetching auth config...", end=" ", flush=True)
    try:
        config = api.get_auth_config()
        safe_config = _strip_sensitive(config)
        config_path = root / "auth_config.json"
        config_path.write_text(json.dumps(safe_config, indent=2))
        stripped = sorted((SENSITIVE_AUTH_KEYS | READONLY_AUTH_KEYS) & set(config.keys()))
        print(f"saved ({config_path.stat().st_size:,} bytes)")
        if stripped:
            print(f"    ⚠️  Keys stripped (sensitive/read-only): {', '.join(stripped)}")
    except RuntimeError as e:
        print(f"\n  ERROR: {e}")
        sys.exit(1)

    time.sleep(REQUEST_DELAY_SECONDS)

    # 2. Third-party providers
    print("  Fetching third-party providers...", end=" ", flush=True)
    try:
        providers = api.list_third_party_providers()
        providers_path = root / "third_party_auth.json"
        providers_path.write_text(json.dumps(providers, indent=2))
        print(f"saved ({len(providers)} provider(s), {providers_path.stat().st_size:,} bytes)")
        for p in providers:
            print(f"    🔗 {_provider_label(p)}")
    except RuntimeError as e:
        print(f"\n  ERROR: {e}")
        sys.exit(1)

    time.sleep(REQUEST_DELAY_SECONDS)

    # 3. Manifest
    manifest = {
        "project_ref": project_ref,
        "backup_time": datetime.now(timezone.utc).isoformat(),
        "provider_count": len(providers),
        "auth_config_keys": len(safe_config),
        "sensitive_keys_stripped": sorted(SENSITIVE_AUTH_KEYS & set(config.keys())),
    }
    manifest_path = root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))

    print(f"\n  Backup complete.")
    print(f"  Manifest: {manifest_path.resolve()}")
    print(f"\n  To restore:")
    print(f"    Same project:      python supabase-auth-copy.py restore --project-ref {project_ref} --dir {root}")
    print(f"    Different project: python supabase-auth-copy.py restore --project-ref <target-ref> --dir {root}")
    print()


def do_restore(
    api: SupabaseAuthAPI,
    backup_dir: str,
    skip_config: bool = False,
    skip_providers: bool = False,
    dry_run: bool = False,
):
    """
    Restore auth config and third-party providers from a backup directory.

    Args:
        api (SupabaseAuthAPI): Authenticated API client (pointed at target project).
        backup_dir (str): Directory containing the backup.
        skip_config (bool): If True, skip restoring the main auth config.
        skip_providers (bool): If True, skip restoring third-party providers.
        dry_run (bool): If True, preview without making any changes.
    """
    root = Path(backup_dir)

    # Resolve default if not set
    if not root.exists():
        # Try to find backup dirs nearby
        candidates = sorted(Path(".").glob(f"{DEFAULT_BACKUP_DIR_PREFIX}_*"))
        if candidates:
            print(f"\n  ERROR: Backup directory not found: {root}")
            print(f"  Available backup directories:")
            for c in candidates:
                mf = c / "manifest.json"
                if mf.exists():
                    try:
                        m = json.loads(mf.read_text())
                        print(f"    {c}  (source: {m.get('project_ref','?')}, taken: {m.get('backup_time','?')})")
                    except Exception:
                        print(f"    {c}")
        else:
            print(f"\n  ERROR: Backup directory not found: {root}")
        sys.exit(1)

    manifest_path = root / "manifest.json"
    if not manifest_path.exists():
        print(f"\n  ERROR: No manifest.json found in {root}. Is this a valid backup directory?")
        sys.exit(1)

    manifest = json.loads(manifest_path.read_text())
    source_ref = manifest.get("project_ref", "unknown")

    print(f"\n  Restoring Auth to project: {api.project_ref}")
    print(f"  Source backup:    {root.resolve()}")
    print(f"  Backup taken:     {manifest.get('backup_time', 'unknown')}")
    print(f"  Original project: {source_ref}")
    if dry_run:
        print(f"  Mode:             DRY RUN — no changes will be made")
    print()

    # -- Auth config ----------------------------------------------------------
    config_path = root / "auth_config.json"
    if not skip_config and config_path.exists():
        raw_config = json.loads(config_path.read_text())
        # Reason: strip SMTP-dependent keys at restore time — they require SMTP
        # to be pre-configured on the target and cause 401 if sent without it.
        config = _strip_for_restore(raw_config)
        smtp_skipped = sorted(SMTP_DEPENDENT_KEYS & set(raw_config.keys()))

        print(f"  ── Auth Config ({'DRY RUN — skipping' if dry_run else 'applying'}) ──────────────────")
        print(f"    {len(config)} key(s) to apply")
        if smtp_skipped:
            print(f"    ⚠️  SMTP-dependent keys skipped (configure SMTP on target first): {', '.join(smtp_skipped)}")

        # Always show a few key values so user can verify
        preview_keys = ["site_url", "jwt_exp", "disable_signup", "email_confirmations"]
        for k in preview_keys:
            if k in config:
                print(f"    {k}: {config[k]}")

        if not dry_run:
            try:
                api.update_auth_config(config)
                print(f"    ✅ Auth config applied.")
            except RuntimeError as e:
                print(f"    ERROR: {e}")
        else:
            print(f"    [DRY RUN] Would PATCH auth config with {len(config)} key(s).")
        print()
        time.sleep(REQUEST_DELAY_SECONDS)
    elif skip_config:
        print("  ── Auth Config — SKIPPED (--skip-config) ────────────────\n")
    else:
        print("  ── Auth Config — SKIPPED (auth_config.json not found in backup) ────\n")

    # -- Third-party providers ------------------------------------------------
    providers_path = root / "third_party_auth.json"
    if not skip_providers and providers_path.exists():
        providers_to_restore = json.loads(providers_path.read_text())
        print(f"  ── Third-Party Providers ({'DRY RUN' if dry_run else 'restoring'}) ─────────────────")

        if not providers_to_restore:
            print("    No providers in backup.")
            print()
        else:
            # Fetch existing providers on the target to avoid duplicates
            try:
                existing = api.list_third_party_providers()
            except RuntimeError as e:
                print(f"    WARNING: Could not fetch existing providers: {e}")
                existing = []

            time.sleep(REQUEST_DELAY_SECONDS)

            added = 0
            skipped = 0
            for p in providers_to_restore:
                label = _provider_label(p)
                # Check if an identical provider already exists
                already_exists = any(_providers_equal(p, e) for e in existing)
                if already_exists:
                    print(f"    SKIP (already exists): {label}")
                    skipped += 1
                    continue

                # Build payload — strip server-managed fields, send oidc_issuer_url
                payload = _build_provider_payload(p)

                if dry_run:
                    print(f"    [DRY RUN] Would add: {label}")
                    added += 1
                else:
                    try:
                        api.add_third_party_provider(payload)
                        print(f"    ✅ Added: {label}")
                        added += 1
                        time.sleep(REQUEST_DELAY_SECONDS)
                    except RuntimeError as e:
                        print(f"    ERROR adding {label}: {e}")

            print()
            print(f"    {added} added, {skipped} skipped (already existed)")
            print()
    elif skip_providers:
        print("  ── Third-Party Providers — SKIPPED (--skip-providers) ──\n")
    else:
        print("  ── Third-Party Providers — SKIPPED (third_party_auth.json not found) ──\n")

    print(f"  Restore {'preview' if dry_run else 'complete'}.")
    print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    """
    Build the argument parser for all subcommands.

    Returns:
        argparse.ArgumentParser: Configured parser.
    """
    parser = argparse.ArgumentParser(
        prog="supabase-auth-copy.py",
        description="Backup and restore Supabase Auth config and Third-Party Auth providers.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
commands:
  list     Show auth config summary and third-party providers for a project
  backup   Save auth config + providers to a local directory
  restore  Apply auth config + providers from a backup to a project

examples:
  python supabase-auth-copy.py list --project-ref abcdefghijklmnop
  python supabase-auth-copy.py backup --project-ref abcdefghijklmnop
  python supabase-auth-copy.py restore --project-ref newprojectref --dir auth_backup_abcdefghijklmnop
  python supabase-auth-copy.py restore --project-ref newprojectref --dir auth_backup_abcdefghijklmnop --skip-config
  python supabase-auth-copy.py restore --project-ref newprojectref --dir auth_backup_abcdefghijklmnop --dry-run
""",
    )

    # Shared parent parser
    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument(
        "--project-ref",
        default=os.environ.get("SUPABASE_PROJECT_REF"),
        help="Supabase project reference ID (or set SUPABASE_PROJECT_REF env var)",
    )
    shared.add_argument(
        "--token",
        default=os.environ.get("SUPABASE_ACCESS_TOKEN"),
        help="Supabase Personal Access Token (or set SUPABASE_ACCESS_TOKEN env var)",
    )

    sub = parser.add_subparsers(dest="command")

    # list
    sub.add_parser(
        "list",
        parents=[shared],
        help="Show auth config summary and third-party providers",
    )

    # backup
    p_backup = sub.add_parser(
        "backup",
        parents=[shared],
        help="Save auth config and providers to a local directory",
    )
    p_backup.add_argument(
        "--dir",
        default=None,
        metavar="PATH",
        help="Directory to save the backup into (default: auth_backup_<project-ref>)",
    )

    # restore
    p_restore = sub.add_parser(
        "restore",
        parents=[shared],
        help="Restore auth config and providers from a backup to a project",
    )
    p_restore.add_argument(
        "--dir",
        default=None,
        metavar="PATH",
        help="Directory containing the backup (default: auth_backup_<project-ref>)",
    )
    p_restore.add_argument(
        "--skip-config",
        action="store_true",
        help="Skip restoring the main auth config — only restore third-party providers",
    )
    p_restore.add_argument(
        "--skip-providers",
        action="store_true",
        help="Skip restoring third-party providers — only restore the main auth config",
    )
    p_restore.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview what would be changed without making any API calls",
    )

    return parser


def main():
    """
    Entry point — parse args, validate credentials, dispatch to command handler.
    """
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    if not args.project_ref:
        print("ERROR: --project-ref is required (or set SUPABASE_PROJECT_REF).")
        sys.exit(1)
    if not args.token:
        print("ERROR: --token is required (or set SUPABASE_ACCESS_TOKEN).")
        sys.exit(1)

    api = SupabaseAuthAPI(token=args.token, project_ref=args.project_ref)

    if args.command == "list":
        do_list(api)

    elif args.command == "backup":
        backup_dir = args.dir or f"{DEFAULT_BACKUP_DIR_PREFIX}_{args.project_ref}"
        do_backup(api, project_ref=args.project_ref, backup_dir=backup_dir)

    elif args.command == "restore":
        backup_dir = args.dir or f"{DEFAULT_BACKUP_DIR_PREFIX}_{args.project_ref}"
        do_restore(
            api,
            backup_dir=backup_dir,
            skip_config=args.skip_config,
            skip_providers=args.skip_providers,
            dry_run=args.dry_run,
        )

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
