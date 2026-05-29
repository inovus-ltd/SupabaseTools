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


def _default_backup_root() -> Path:
    """
    Return a safe, user-writable directory for storing backups.
    Resolves to ~/Documents/SupabaseTools, which is appropriate on all
    platforms and avoids writing into system directories (e.g. System32)
    when the exe is installed there.

    Returns:
        Path: Guaranteed-to-exist base directory for backups.
    """
    base = Path.home() / "Documents" / "SupabaseTools"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _exe_name() -> str:
    """
    Return the name of the current executable for use in help/hint text.
    When frozen by PyInstaller sys.frozen is True and we use sys.executable.
    When running as a plain script we use the script filename.

    Returns:
        str: Command name to show in restore hints.
    """
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).name
    return "python supabase-functions-backup.py"


def _resolve_dir(dir_arg, default_name: str) -> str:
    """
    Resolve a backup directory path from a CLI argument.

    Resolution order:
      1. If no arg given: use ~/Documents/SupabaseTools/<default_name>
      2. If arg is an absolute path: use as-is
      3. If arg is a bare name / relative path and exists in CWD: use CWD-relative
      4. If arg is a bare name and exists in ~/Documents/SupabaseTools/: use that
      5. Otherwise: fall back to ~/Documents/SupabaseTools/<arg> (will fail
         gracefully with a clear error inside do_restore)

    This means users can type just the folder name from the restore hint and
    it will be found automatically regardless of their CWD.

    Args:
        dir_arg (str | None): Value of --dir from argparse, or None.
        default_name (str): Folder name to use when no --dir given.

    Returns:
        str: Resolved absolute path string.
    """
    if not dir_arg:
        return str(_default_backup_root() / default_name)
    p = Path(dir_arg)
    if p.is_absolute():
        return str(p)
    # Relative: check CWD first, then ~/Documents/SupabaseTools/
    if p.exists():
        return str(p.resolve())
    candidate = _default_backup_root() / p
    if candidate.exists():
        return str(candidate)
    # Neither found — return the Documents path so the error message is helpful
    return str(_default_backup_root() / p)

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

    def get_function_source_files(self, project_ref: str, slug: str) -> list:
        """
        Download the function's source files via the multipart body endpoint.

        Returns a list of dicts: [{"filename": str, "content": bytes}, ...]
        The API returns multipart/form-data with one part per source file.
        """
        url = f"{MANAGEMENT_API_BASE}/projects/{project_ref}/functions/{slug}/body"
        resp = self._get(url, headers={"Accept": "multipart/form-data"}, stream=True)

        content_type = resp.headers.get("Content-Type", "")
        if "multipart" not in content_type:
            # Reason: older API or fallback — single binary blob, save as-is
            return [{"filename": "function.eszip", "content": resp.content}]

        # Parse the multipart boundary and extract each source file
        boundary = None
        for part in content_type.split(";"):
            part = part.strip()
            if part.startswith("boundary="):
                boundary = part[len("boundary="):].strip('"')
                break

        if not boundary:
            return [{"filename": "function.eszip", "content": resp.content}]

        return _parse_multipart(resp.content, boundary)

    # -- Edge Functions: write ------------------------------------------------

    def deploy_function(
        self,
        project_ref: str,
        slug: str,
        source_files: list,
        metadata: dict,
    ) -> dict:
        """
        Deploy (create or update) an Edge Function.

        source_files is a list of dicts: [{"filename": str, "content": bytes}, ...]
        The entrypoint file (e.g. index.ts) must be among them.
        """
        url = (
            f"{MANAGEMENT_API_BASE}/projects/{project_ref}"
            f"/functions/deploy?slug={slug}"
        )

        meta_payload = {
            "entrypoint_path": metadata.get("entrypoint_path", "index.ts"),
            "name": metadata.get("name", slug),
        }
        if "verify_jwt" in metadata:
            meta_payload["verify_jwt"] = metadata["verify_jwt"]
        if "import_map_path" in metadata and metadata["import_map_path"]:
            meta_payload["import_map_path"] = metadata["import_map_path"]

        # Build multipart: one 'metadata' part + one part per source file
        files = [("metadata", (None, json.dumps(meta_payload), "application/json"))]
        for sf in source_files:
            files.append(("file", (sf["filename"], sf["content"], "application/octet-stream")))

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
# Multipart parser
# ---------------------------------------------------------------------------

def _parse_multipart(body: bytes, boundary: str) -> list:
    """
    Parse a multipart/form-data response body and extract file parts.

    Returns a list of dicts: [{"filename": str, "content": bytes}, ...]
    """
    delimiter = f"--{boundary}".encode()
    parts = body.split(delimiter)
    files = []

    for part in parts:
        if not part or part == b"--\r\n" or part == b"--":
            continue
        # Split headers from body on the first double CRLF
        if b"\r\n\r\n" not in part:
            continue
        headers_raw, content = part.split(b"\r\n\r\n", 1)
        # Strip trailing CRLF from content
        content = content.rstrip(b"\r\n")

        # Extract filename from Content-Disposition header
        filename = None
        for line in headers_raw.decode(errors="replace").splitlines():
            if "content-disposition" in line.lower() and "filename=" in line.lower():
                for token in line.split(";"):
                    token = token.strip()
                    if token.startswith("filename="):
                        filename = token[len("filename="):].strip('"').strip("'")
                        break
            if filename:
                break

        if filename and content:
            # Reason: strip any deployment-specific temp path prefix,
            # keeping only the relative filename (e.g. index.ts, utils/helper.ts)
            normalized = Path(filename.replace("file://", ""))
            # If it's an absolute path, take everything after 'source/' if present
            parts_path = normalized.parts
            if "source" in parts_path:
                idx = list(parts_path).index("source")
                filename = str(Path(*parts_path[idx + 1:]))
            else:
                filename = normalized.name
            files.append({"filename": filename, "content": content})

    return files if files else [{"filename": "function.eszip", "content": body}]


# ---------------------------------------------------------------------------
# Backup logic
# ---------------------------------------------------------------------------

def do_backup(api: SupabaseManagementAPI, project_ref: str, backup_dir: str):
    """
    Download every Edge Function's metadata and source files into
    a structured backup directory.

    Directory layout:
      <backup_dir>/
        manifest.json          # summary of all functions + backup timestamp
        <slug>/
          metadata.json        # function config (name, verify_jwt, etc.)
          source/
            index.ts           # source files as returned by the API
            utils/helper.ts    # (any additional files)
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

        # 2. Save source files from the multipart body endpoint
        source_files = api.get_function_source_files(project_ref, slug)
        source_dir = fn_dir / "source"
        source_dir.mkdir(exist_ok=True)
        total_bytes = 0
        for sf in source_files:
            sf_path = source_dir / sf["filename"]
            sf_path.parent.mkdir(parents=True, exist_ok=True)
            sf_path.write_bytes(sf["content"])
            total_bytes += len(sf["content"])
        time.sleep(REQUEST_DELAY_SECONDS)

        manifest["functions"].append({
            "slug": slug,
            "name": fn.get("name", slug),
            "version": fn.get("version"),
            "status": fn.get("status"),
            "verify_jwt": fn.get("verify_jwt"),
            "entrypoint_path": "index.ts",
            "import_map_path": fn.get("import_map_path"),
            "source_files": [sf["filename"] for sf in source_files],
        })

        print(f"     metadata saved  ({meta_path.stat().st_size:,} bytes)")
        print(f"     source saved    ({total_bytes:,} bytes, {len(source_files)} file(s))")

    # Write the manifest
    manifest_path = root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))

    print(f"\n  Backup complete. {len(functions)} function(s) saved.")
    print(f"  Manifest: {manifest_path.resolve()}")
    cmd = _exe_name()
    dir_arg = root.name
    print(f"\n  To restore these functions:")
    print(f"    Same project:      {cmd} restore --project-ref {project_ref}")
    print(f"    Different project: {cmd} restore --project-ref <target-ref> --dir {dir_arg}")
    print(f"    e.g.               {cmd} restore --project-ref abcdefghijklmnop --dir {dir_arg}")
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
        print(f"    {_exe_name()} restore --project-ref {project_ref} --dir edge_functions_backup_<source-project-ref>")
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
        source_dir = fn_dir / "source"
        meta_path = fn_dir / "metadata.json"

        if not source_dir.exists() or not any(source_dir.iterdir()):
            print(f"  SKIP {slug} — no source files found in {source_dir}")
            continue

        meta = {}
        if meta_path.exists():
            meta = json.loads(meta_path.read_text())

        # Load all source files from the source/ subdirectory
        source_files = []
        for sf_path in sorted(source_dir.rglob("*")):
            if sf_path.is_file():
                rel = sf_path.relative_to(source_dir)
                source_files.append({"filename": str(rel), "content": sf_path.read_bytes()})

        entrypoint = fn_info.get("entrypoint_path", "index.ts")
        total_bytes = sum(len(sf["content"]) for sf in source_files)
        jwt_label = "JWT verified" if meta.get("verify_jwt", fn_info.get("verify_jwt", True)) else "NO JWT check"

        deploy_meta = {
            "name": meta.get("name", fn_info.get("name", slug)),
            "entrypoint_path": entrypoint,
            "verify_jwt": meta.get("verify_jwt", fn_info.get("verify_jwt", True)),
            "import_map_path": meta.get("import_map_path", fn_info.get("import_map_path")),
        }

        if dry_run:
            print(f"  [DRY RUN] Would deploy: {slug} ({total_bytes:,} bytes, {len(source_files)} file(s), {jwt_label})")
        else:
            print(f"  -> Deploying: {slug} ({total_bytes:,} bytes, {len(source_files)} file(s), {jwt_label}) ...", end=" ")
            try:
                result = api.deploy_function(
                    project_ref, slug, source_files, deploy_meta
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

    if args.command == "backup":
        backup_dir = _resolve_dir(args.dir, f"{DEFAULT_BACKUP_DIR_PREFIX}_{args.project_ref}")
        do_backup(api, args.project_ref, backup_dir)

    elif args.command == "restore":
        backup_dir = _resolve_dir(args.dir, f"{DEFAULT_BACKUP_DIR_PREFIX}_{args.project_ref}")
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