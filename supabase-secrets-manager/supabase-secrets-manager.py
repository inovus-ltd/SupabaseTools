#!/usr/bin/env python3
"""
Supabase Secrets Manager
========================

List, add, update, and delete Edge Function secrets on a Supabase project
using the Supabase Management API.

Because the API never returns secret *values* (only names), this tool lets
you type values in interactively or supply them via a .env file.

Uses the Supabase Management API:
  https://supabase.com/docs/reference/api

Requirements:
  - Python 3.8+
  - requests library (pip install requests)
  - A Supabase Personal Access Token (PAT):
      https://supabase.com/dashboard/account/tokens

Commands:
  list    -- List all secret names on a project (values are never shown)
  set     -- Interactively add or update one or more secrets
  delete  -- Delete one or more secrets by name
  push    -- Read secrets from a .env file and push them to a project

Environment variables (alternative to CLI flags):
  SUPABASE_ACCESS_TOKEN  - Your PAT
  SUPABASE_PROJECT_REF   - The project reference ID
"""

import argparse
import getpass
import json
import os
import sys
import time
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

# Small courtesy delay between API calls to stay within rate limits.
REQUEST_DELAY_SECONDS = 0.2


# ---------------------------------------------------------------------------
# API client
# ---------------------------------------------------------------------------

class SupabaseSecretsAPI:
    """
    Thin wrapper around the Supabase Management API secrets endpoints.
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

    def list_secrets(self) -> list:
        """
        List all secret names on the project. Values are never returned by the API.

        Returns:
            list: List of dicts with at minimum a 'name' key.
        """
        url = f"{MANAGEMENT_API_BASE}/projects/{self.project_ref}/secrets"
        resp = self.session.get(url)
        if resp.status_code >= 400:
            raise RuntimeError(
                f"List secrets failed (HTTP {resp.status_code}): {resp.text}"
            )
        return resp.json()

    def set_secrets(self, secrets: list) -> None:
        """
        Create or update secrets. Existing secrets with matching names are overwritten.

        Args:
            secrets (list): List of dicts with 'name' and 'value' keys.
        """
        url = f"{MANAGEMENT_API_BASE}/projects/{self.project_ref}/secrets"
        resp = self.session.post(url, json=secrets)
        if resp.status_code >= 400:
            raise RuntimeError(
                f"Set secrets failed (HTTP {resp.status_code}): {resp.text}"
            )

    def delete_secrets(self, names: list) -> None:
        """
        Delete secrets by name.

        Args:
            names (list): List of secret name strings to delete.
        """
        url = f"{MANAGEMENT_API_BASE}/projects/{self.project_ref}/secrets"
        resp = self.session.delete(url, json=names)
        if resp.status_code >= 400:
            raise RuntimeError(
                f"Delete secrets failed (HTTP {resp.status_code}): {resp.text}"
            )


# ---------------------------------------------------------------------------
# .env file parser
# ---------------------------------------------------------------------------

def parse_env_file(path: str) -> dict:
    """
    Parse a .env file into a dict of name -> value pairs.
    Skips blank lines and comments. Strips surrounding quotes from values.

    Args:
        path (str): Path to the .env file.

    Returns:
        dict: Mapping of secret name to value.
    """
    result = {}
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f".env file not found: {path}")

    for line_no, raw in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        # Skip blanks and comments
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            print(f"  WARNING: Line {line_no} skipped (no '=' found): {raw!r}")
            continue
        name, _, value = line.partition("=")
        name = name.strip()
        value = value.strip()
        # Strip optional surrounding quotes
        if len(value) >= 2 and value[0] in ('"', "'") and value[-1] == value[0]:
            value = value[1:-1]
        if name:
            result[name] = value

    return result


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

def do_list(api: SupabaseSecretsAPI):
    """
    Print all secret names on the project.

    Args:
        api (SupabaseSecretsAPI): Authenticated API client.
    """
    print(f"\n  Secrets on project: {api.project_ref}\n")

    secrets = api.list_secrets()

    if not secrets:
        print("  No secrets found.")
        print()
        return

    # Sort alphabetically for easy reading
    secrets_sorted = sorted(secrets, key=lambda s: s.get("name", "").lower())

    for s in secrets_sorted:
        name = s.get("name", "(unnamed)")
        print(f"  🔑 {name}")

    print(f"\n  Total: {len(secrets)} secret(s)")
    print()


def do_set(api: SupabaseSecretsAPI, names: list = None, dry_run: bool = False):
    """
    Interactively prompt for secret names and values, then push them to the project.
    If names are provided up front, only those names are prompted for values.

    Args:
        api (SupabaseSecretsAPI): Authenticated API client.
        names (list): Optional list of secret names to set. If None, prompts for names too.
        dry_run (bool): If True, print what would be set without actually setting.
    """
    print(f"\n  Set secrets on project: {api.project_ref}")
    print(f"  Values are hidden as you type. Press Enter with no value to skip a secret.\n")

    to_set = []

    if names:
        # Names provided — just prompt for values
        for name in names:
            value = getpass.getpass(f"  Value for '{name}': ")
            if value:
                to_set.append({"name": name, "value": value})
            else:
                print(f"  (skipped '{name}')")
    else:
        # Interactive name + value entry loop
        print("  Enter secrets one at a time. Leave the name blank to finish.\n")
        while True:
            name = input("  Secret name (blank to finish): ").strip()
            if not name:
                break
            value = getpass.getpass(f"  Value for '{name}': ")
            if value:
                to_set.append({"name": name, "value": value})
            else:
                print(f"  (skipped '{name}' — no value entered)")

    if not to_set:
        print("\n  Nothing to set.")
        print()
        return

    print(f"\n  {'[DRY RUN] Would set' if dry_run else 'Setting'} {len(to_set)} secret(s):")
    for s in to_set:
        print(f"    🔑 {s['name']}")

    if dry_run:
        print()
        return

    print()
    try:
        api.set_secrets(to_set)
        print(f"  ✅ {len(to_set)} secret(s) set successfully.")
    except RuntimeError as e:
        print(f"  ERROR: {e}")
        sys.exit(1)

    print()


def do_delete(api: SupabaseSecretsAPI, names: list, dry_run: bool = False):
    """
    Delete secrets by name after confirmation.

    Args:
        api (SupabaseSecretsAPI): Authenticated API client.
        names (list): Secret names to delete.
        dry_run (bool): If True, print what would be deleted without deleting.
    """
    print(f"\n  Delete secrets on project: {api.project_ref}\n")

    if not names:
        print("  No secret names provided. Use --names NAME1 NAME2 ...")
        print()
        return

    print(f"  {'[DRY RUN] Would delete' if dry_run else 'About to delete'} {len(names)} secret(s):")
    for name in names:
        print(f"    🗑️  {name}")

    if dry_run:
        print()
        return

    confirm = input("\n  Type YES to confirm deletion: ").strip()
    if confirm != "YES":
        print("  Aborted.")
        print()
        return

    try:
        api.delete_secrets(names)
        print(f"\n  ✅ {len(names)} secret(s) deleted.")
    except RuntimeError as e:
        print(f"  ERROR: {e}")
        sys.exit(1)

    print()


def do_push(api: SupabaseSecretsAPI, env_file: str, dry_run: bool = False):
    """
    Read secrets from a .env file and push all of them to the project.

    Args:
        api (SupabaseSecretsAPI): Authenticated API client.
        env_file (str): Path to the .env file.
        dry_run (bool): If True, print what would be set without actually setting.
    """
    print(f"\n  Push secrets from .env file to project: {api.project_ref}")
    print(f"  File: {Path(env_file).resolve()}\n")

    try:
        parsed = parse_env_file(env_file)
    except FileNotFoundError as e:
        print(f"  ERROR: {e}")
        sys.exit(1)

    if not parsed:
        print("  No secrets found in the .env file.")
        print()
        return

    to_set = [{"name": k, "value": v} for k, v in parsed.items()]

    print(f"  {'[DRY RUN] Would set' if dry_run else 'Setting'} {len(to_set)} secret(s):")
    for s in to_set:
        print(f"    🔑 {s['name']}")

    if dry_run:
        print()
        return

    print()
    try:
        api.set_secrets(to_set)
        print(f"  ✅ {len(to_set)} secret(s) pushed successfully.")
    except RuntimeError as e:
        print(f"  ERROR: {e}")
        sys.exit(1)

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
        prog="supabase-secrets-manager.py",
        description="Manage Supabase Edge Function secrets via the Management API.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
commands:
  list    List all secret names on a project (values are never returned by the API)
  set     Interactively add or update secrets (values hidden as you type)
  delete  Delete one or more secrets by name
  push    Read secrets from a .env file and push them to a project

examples:
  python supabase-secrets-manager.py list --project-ref abcdefghijklmnop
  python supabase-secrets-manager.py set --project-ref abcdefghijklmnop
  python supabase-secrets-manager.py set --project-ref abcdefghijklmnop --names STRIPE_KEY OPENAI_KEY
  python supabase-secrets-manager.py delete --project-ref abcdefghijklmnop --names OLD_SECRET
  python supabase-secrets-manager.py push --project-ref abcdefghijklmnop --env-file .env.production
""",
    )

    # Shared args
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
    shared.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview what would be changed without making any API calls",
    )

    sub = parser.add_subparsers(dest="command")

    # list
    sub.add_parser(
        "list",
        parents=[shared],
        help="List all secret names on a project",
    )

    # set
    p_set = sub.add_parser(
        "set",
        parents=[shared],
        help="Interactively add or update secrets",
    )
    p_set.add_argument(
        "--names",
        nargs="+",
        metavar="NAME",
        help="Secret name(s) to set — prompts for each value interactively",
    )

    # delete
    p_del = sub.add_parser(
        "delete",
        parents=[shared],
        help="Delete one or more secrets by name",
    )
    p_del.add_argument(
        "--names",
        nargs="+",
        metavar="NAME",
        required=True,
        help="Secret name(s) to delete",
    )

    # push
    p_push = sub.add_parser(
        "push",
        parents=[shared],
        help="Read secrets from a .env file and push them to a project",
    )
    p_push.add_argument(
        "--env-file",
        default=".env",
        metavar="PATH",
        help="Path to the .env file (default: .env)",
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

    # Validate required credentials
    if not args.project_ref:
        print("ERROR: --project-ref is required (or set SUPABASE_PROJECT_REF).")
        sys.exit(1)
    if not args.token:
        print("ERROR: --token is required (or set SUPABASE_ACCESS_TOKEN).")
        sys.exit(1)

    api = SupabaseSecretsAPI(token=args.token, project_ref=args.project_ref)

    if args.command == "list":
        do_list(api)

    elif args.command == "set":
        do_set(api, names=getattr(args, "names", None), dry_run=args.dry_run)

    elif args.command == "delete":
        do_delete(api, names=args.names, dry_run=args.dry_run)

    elif args.command == "push":
        do_push(api, env_file=args.env_file, dry_run=args.dry_run)

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
