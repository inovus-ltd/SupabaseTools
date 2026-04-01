#!/usr/bin/env python3
"""
Supabase Edge Functions Backup & Restore Tool
==============================================

Backs up all Edge Functions from a Supabase project (metadata + source code)
to a local directory, and can restore them to the same or a different project.

Uses the Supabase Management API:
  https://supabase.com/docs/reference/api

Requirements:
  - Python 3.8+
  - requests library (pip install requests)
  - A Supabase Personal Access Token (PAT) from:
    https://supabase.com/dashboard/account/tokens

Usage:
  # Backup all edge functions from a project
  python supabase_edge_functions_backup.py backup --project-ref <ref> --token <pat>

  # Restore all edge functions to a (possibly different) project
  python supabase_edge_functions_backup.py restore --project-ref <ref> --token <pat>

  # List functions on a project without downloading anything
  python supabase_edge_functions_backup.py list --project-ref <ref> --token <pat>

  # Restore only specific functions by slug
  python supabase_edge_functions_backup.py restore --project-ref <ref> --token <pat> --slugs func-a func-b

Environment variables (alternative to CLI flags):
  SUPABASE_ACCESS_TOKEN   - Your PAT token
  SUPABASE_PROJECT_REF    - The project reference ID
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
DEFAULT_BACKUP_DIR_PREFIX = "edge_functions_backup"

# The Management API allows 120 requests/min per project. We add a small
# courtesy delay between calls to stay well within limits.
REQUEST_DELAY_SECONDS = 0.3


# ---------------------------------------------------------------------------
# API helper
# ---------------------------------------------------------------------------

class SupabaseManagementAPI:
    """
    Thin wrapper around the Supabase Management API endpoints we need
    for Edge Functions backup and restore.
    """

    def __init__(self, access_token: str):
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {access_token}",
        })

    # -- Edge Functions: read -------------------------------------------------

    def list_functions(self, project_ref: str) -> list:
        """Return metadata for every Edge Function in the project."""
        url = f"{MANAGEMENT_API_BASE}/projects/{project_ref}/functions"
        resp = self._get(url)
        return resp.json()

    def get_function_meta(self, project_ref: str, slug: str) -> dict:
        """Return detailed metadata for a single Edge Function."""
        url = f"{MANAGEMENT_API_BASE}/projects/{project_ref}/functions/{slug}"
        resp = self._get(url)
        return resp.json()

    def get_function_body(self, project_ref: str, slug: str) -> bytes:
        """
        Download the function's source as an eszip bundle (binary).
        The Management API returns the compiled/bundled artefact.
        """
        url = f"{MANAGEMENT_API_BASE}/projects/{project_ref}/functions/{slug}/body"
        resp = self._get(url, stream=True)
        return resp.content

    # -- Edge Functions: write ------------------------------------------------

    def deploy_function(
        self,
        project_ref: str,
        slug: str,
        source_path: Path,
        metadata: dict,
    ) -> dict:
        """
        Deploy (create or update) an Edge Function using the newer
        /functions/deploy endpoint. Sends the source file + metadata
        as multipart/form-data.
        """
        url = (
            f"{MANAGEMENT_API_BASE}/projects/{project_ref}"
            f"/functions/deploy?slug={slug}"
        )

        # Build the metadata payload — the API expects at minimum an
        # entrypoint_path and optionally a name and verify_jwt flag.
        meta_payload = {
            "entrypoint_path": metadata.get("entrypoint_path", "index.ts"),
            "name": metadata.get("name", slug),
        }
        if "verify_jwt" in metadata:
            meta_payload["verify_jwt"] = metadata["verify_jwt"]
        if "import_map_path" in metadata and metadata["import_map_path"]:
            meta_payload["import_map_path"] = metadata["import_map_path"]

        with open(source_path, "rb") as f:
            files = {
                "metadata": (None, json.dumps(meta_payload), "application/json"),
                "file": (source_path.name, f, "application/octet-stream"),
            }
            resp = self.session.post(url, files=files)

        if resp.status_code >= 400:
            raise RuntimeError(
                f"Deploy failed for '{slug}' (HTTP {resp.status_code}): "
                f"{resp.text}"
            )
        return resp.json()

    def delete_function(self, project_ref: str, slug: str) -> None:
        """Delete an Edge Function by slug."""
        url = f"{MANAGEMENT_API_BASE}/projects/{project_ref}/functions/{slug}"
        resp = self.session.delete(url)
        if resp.status_code >= 400:
            raise RuntimeError(
                f"Delete failed for '{slug}' (HTTP {resp.status_code}): "
                f"{resp.text}"
            )

    # -- Internal helpers -----------------------------------------------------

    def _get(self, url: str, **kwargs) -> requests.Response:
        resp = self.session.get(url, **kwargs)
        if resp.status_code == 429:
            # Rate-limited — back off and retry once
            retry_ms = int(resp.headers.get("X-RateLimit-Reset", 5000))
            wait = max(retry_ms / 1000, 1)
            print(f"  Rate-limited. Waiting {wait:.0f}s before retrying...")
            time.sleep(wait)
            resp = self.session.get(url, **kwargs)
        if resp.status_code >= 400:
            raise RuntimeError(
                f"GET {url} failed (HTTP {resp.status_code}): {resp.text}"
            )
        return resp


# ---------------------------------------------------------------------------
# Backup logic
# ---------------------------------------------------------------------------

def do_backup(api: SupabaseManagementAPI, project_ref: str, backup_dir: str):
    """
    Download every Edge Function's metadata and source bundle into
    a timestamped backup directory.

    Directory layout:
      <backup_dir>/
        manifest.json          # summary of all functions + backup timestamp
        <slug>/
          metadata.json        # function config (name, verify_jwt, etc.)
          function.eszip       # compiled source bundle from the API
    """
    root = Path(backup_dir)

    print(f"\n Backing up Edge Functions for project: {project_ref}")
    print(f"   Destination: {root.resolve()}\n")

    functions = api.list_functions(project_ref)

    if not functions:
        print("  No Edge Functions found on this project. Nothing to back up.")
        return

    print(f"  Found {len(functions)} function(s):\n")

    manifest = {
        "project_ref": project_ref,
        "backup_time": datetime.now(timezone.utc).isoformat(),
        "functions": [],
    }

    for fn in functions:
        slug = fn["slug"]
        print(f"  -> {slug} (v{fn.get('version', '?')})")

        fn_dir = root / slug
        fn_dir.mkdir(parents=True, exist_ok=True)

        # 1. Save metadata
        meta = api.get_function_meta(project_ref, slug)
        meta_path = fn_dir / "metadata.json"
        meta_path.write_text(json.dumps(meta, indent=2))
        time.sleep(REQUEST_DELAY_SECONDS)

        # 2. Save source bundle
        body = api.get_function_body(project_ref, slug)
        body_path = fn_dir / "function.eszip"
        body_path.write_bytes(body)
        time.sleep(REQUEST_DELAY_SECONDS)

        manifest["functions"].append({
            "slug": slug,
            "name": fn.get("name", slug),
            "version": fn.get("version"),
            "status": fn.get("status"),
            "verify_jwt": fn.get("verify_jwt"),
            "entrypoint_path": fn.get("entrypoint_path", "index.ts"),
            "import_map_path": fn.get("import_map_path"),
        })

        print(f"     metadata saved  ({meta_path.stat().st_size:,} bytes)")
        print(f"     source saved    ({body_path.stat().st_size:,} bytes)")

    # Write the manifest
    manifest_path = root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))

    print(f"\n  Backup complete. {len(functions)} function(s) saved.")
    print(f"  Manifest: {manifest_path.resolve()}")
    print(f"\n  To restore these functions:")
    print(f"    Same project:      python supabase-functions-backup.py restore --project-ref {project_ref}")
    print(f"    Different project: python supabase-functions-backup.py restore --project-ref <target-ref> --dir {root.resolve()}")
    print(f"    e.g.               python supabase-functions-backup.py restore --project-ref abcdefghijklmnop --dir {root.resolve()}")
    print()


# ---------------------------------------------------------------------------
# Restore logic
# ---------------------------------------------------------------------------

def do_restore(
    api: SupabaseManagementAPI,
    project_ref: str,
    backup_dir: str,
    slugs=None,
    dry_run: bool = False,
):
    """
    Restore Edge Functions from a backup directory to the target project.

    If --slugs is provided, only those functions will be restored.
    If --dry-run is set, nothing is actually deployed — just a preview.
    """
    root = Path(backup_dir)
    manifest_path = root / "manifest.json"

    if not manifest_path.exists():
        print(f"ERROR: No manifest.json found in {root.resolve()}")
        print()
        print("  This usually means you are restoring to a DIFFERENT project than the one you backed up.")
        print("  The backup folder is named after the SOURCE project, not the restore target.")
        print()
        print("  Use --dir to point at the correct backup folder, e.g.:")
        print(f"    python supabase-functions-backup.py restore --project-ref {project_ref} --dir edge_functions_backup_<source-project-ref>")
        print()
        print("  Available backup folders in the current directory:")
        found_any = False
        for p in sorted(Path(".").iterdir()):
            if p.is_dir() and (p / "manifest.json").exists():
                found_any = True
                mf = json.loads((p / "manifest.json").read_text())
                print(f"    {p}  (backed up from: {mf.get('project_ref', '?')}, at: {mf.get('backup_time', '?')})")
        if not found_any:
            print("    (none found — run 'backup' first)")
        sys.exit(1)

    manifest = json.loads(manifest_path.read_text())
    all_functions = manifest["functions"]

    print(f"\n Restoring Edge Functions to project: {project_ref}")
    print(f"   Source backup: {root.resolve()}")
    print(f"   Backup taken:  {manifest['backup_time']}")
    print(f"   Original project: {manifest['project_ref']}\n")

    if manifest["project_ref"] == project_ref:
        print("  NOTE: You are restoring to the SAME project the backup came from.")
        print("        Existing functions with the same slug will be overwritten.\n")

    # Filter to requested slugs if specified
    if slugs:
        selected = [f for f in all_functions if f["slug"] in slugs]
        missing = set(slugs) - {f["slug"] for f in selected}
        if missing:
            print(f"  WARNING: These slugs were not found in the backup: {missing}")
    else:
        selected = all_functions

    if not selected:
        print("  No functions to restore.")
        return

    print(f"  Will restore {len(selected)} function(s):\n")

    for fn_info in selected:
        slug = fn_info["slug"]
        fn_dir = root / slug
        body_path = fn_dir / "function.eszip"
        meta_path = fn_dir / "metadata.json"

        if not body_path.exists():
            print(f"  SKIP {slug} — source bundle not found at {body_path}")
            continue

        meta = {}
        if meta_path.exists():
            meta = json.loads(meta_path.read_text())

        # Merge manifest-level info with file-level metadata. The file-level
        # metadata is more detailed, but manifest has the essentials too.
        deploy_meta = {
            "name": meta.get("name", fn_info.get("name", slug)),
            "entrypoint_path": meta.get(
                "entrypoint_path", fn_info.get("entrypoint_path", "index.ts")
            ),
            "verify_jwt": meta.get(
                "verify_jwt", fn_info.get("verify_jwt", True)
            ),
            "import_map_path": meta.get(
                "import_map_path", fn_info.get("import_map_path")
            ),
        }

        size = body_path.stat().st_size
        jwt_label = "JWT verified" if deploy_meta["verify_jwt"] else "NO JWT check"

        if dry_run:
            print(f"  [DRY RUN] Would deploy: {slug} ({size:,} bytes, {jwt_label})")
        else:
            print(f"  -> Deploying: {slug} ({size:,} bytes, {jwt_label}) ...", end=" ")
            try:
                result = api.deploy_function(
                    project_ref, slug, body_path, deploy_meta
                )
                print(f"OK (v{result.get('version', '?')})")
            except RuntimeError as e:
                print(f"FAILED\n     {e}")

            time.sleep(REQUEST_DELAY_SECONDS)

    action = "previewed" if dry_run else "restored"
    print(f"\n  Restore {action}. {len(selected)} function(s) processed.\n")


# ---------------------------------------------------------------------------
# List logic
# ---------------------------------------------------------------------------

def do_list(api: SupabaseManagementAPI, project_ref: str):
    """Print a table of all Edge Functions on the project."""
    print(f"\n Edge Functions on project: {project_ref}\n")

    functions = api.list_functions(project_ref)

    if not functions:
        print("  (none)")
        return

    # Header
    print(f"  {'Slug':<30} {'Name':<30} {'Ver':>4} {'Status':<10} {'JWT':>5}")
    print(f"  {'-'*30} {'-'*30} {'-'*4} {'-'*10} {'-'*5}")

    for fn in functions:
        jwt = "yes" if fn.get("verify_jwt") else "no"
        print(
            f"  {fn['slug']:<30} "
            f"{fn.get('name', ''):<30} "
            f"{fn.get('version', '?'):>4} "
            f"{fn.get('status', '?'):<10} "
            f"{jwt:>5}"
        )

    print(f"\n  Total: {len(functions)} function(s)\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Backup and restore Supabase Edge Functions via the Management API.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Backup
  python %(prog)s backup --project-ref abcdefghijkl --token sbp_xxx

  # Backup to a specific directory
  python %(prog)s backup --project-ref abcdefghijkl --dir ./my_backup

  # List functions without downloading
  python %(prog)s list --project-ref abcdefghijkl

  # Restore to a DIFFERENT project
  python %(prog)s restore --project-ref newproject123 --dir ./my_backup

  # Restore only selected functions
  python %(prog)s restore --project-ref newproject123 --slugs hello-world send-email

  # Preview what a restore would do (no changes made)
  python %(prog)s restore --project-ref newproject123 --dry-run

Environment variables:
  SUPABASE_ACCESS_TOKEN   Your personal access token (alternative to --token)
  SUPABASE_PROJECT_REF    Project reference (alternative to --project-ref)
""",
    )

    subparsers = parser.add_subparsers(dest="command")

    # -- Shared arguments via parent --
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument(
        "--project-ref",
        default=os.environ.get("SUPABASE_PROJECT_REF"),
        help="Supabase project reference ID (or set SUPABASE_PROJECT_REF).",
    )
    parent.add_argument(
        "--token",
        default=os.environ.get("SUPABASE_ACCESS_TOKEN"),
        help="Supabase personal access token (or set SUPABASE_ACCESS_TOKEN).",
    )

    # -- backup --
    bp = subparsers.add_parser(
        "backup",
        parents=[parent],
        help="Download all Edge Functions to a local directory.",
    )
    bp.add_argument(
        "--dir",
        default=None,
        help=(
            "Directory to save backups into. "
            f"Defaults to {DEFAULT_BACKUP_DIR_PREFIX}_<project-ref> so each project "
            "gets its own folder automatically."
        ),
    )

    # -- restore --
    rp = subparsers.add_parser(
        "restore",
        parents=[parent],
        help="Deploy Edge Functions from a backup directory to a project.",
    )
    rp.add_argument(
        "--dir",
        default=None,
        help=(
            "Directory containing the backup to restore from. "
            f"Defaults to {DEFAULT_BACKUP_DIR_PREFIX}_<project-ref>."
        ),
    )
    rp.add_argument(
        "--slugs",
        nargs="+",
        default=None,
        help="Only restore these specific function slugs.",
    )
    rp.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview what would be restored without making any changes.",
    )

    # -- list --
    subparsers.add_parser(
        "list",
        parents=[parent],
        help="List all Edge Functions on a project.",
    )

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    # Print full help when called with no arguments
    if not args.command:
        parser.print_help()
        sys.exit(0)

    # Validate required params with friendly, actionable messages
    subparser = parser._subparsers._actions[-1].choices[args.command]
    ok = True
    if not args.token:
        print("ERROR: Access token is required.")
        print("  Use --token <your_token> or set the SUPABASE_ACCESS_TOKEN environment variable.")
        print("  Get a token at: https://supabase.com/dashboard/account/tokens")
        ok = False
    if not args.project_ref:
        print("ERROR: Project reference is required.")
        print("  Use --project-ref <ref> or set the SUPABASE_PROJECT_REF environment variable.")
        print("  Your project ref is in the dashboard URL: supabase.com/dashboard/project/<ref>")
        ok = False
    if not ok:
        print()
        subparser.print_help()
        sys.exit(1)

    api = SupabaseManagementAPI(args.token)

    # Resolve --dir default to a project-scoped folder so each project's
    # backup lives in its own directory and can't be confused with another.
    backup_dir = args.dir if args.dir else f"{DEFAULT_BACKUP_DIR_PREFIX}_{args.project_ref}"

    if args.command == "backup":
        do_backup(api, args.project_ref, backup_dir)

    elif args.command == "restore":
        do_restore(
            api,
            args.project_ref,
            backup_dir,
            slugs=args.slugs,
            dry_run=args.dry_run,
        )

    elif args.command == "list":
        do_list(api, args.project_ref)


if __name__ == "__main__":
    main()