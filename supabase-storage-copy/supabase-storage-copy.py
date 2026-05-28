#!/usr/bin/env python3
"""
Supabase Storage Backup & Restore Tool
=======================================

Backs up all Storage buckets (config + files) from a Supabase project to a
local directory, and can restore them to the same or a different project.

Uses two Supabase APIs:
  - Management API (https://api.supabase.com/v1) — bucket metadata
  - Storage API   (https://<ref>.supabase.co/storage/v1) — file operations

Requirements:
  - Python 3.8+
  - requests library (pip install requests)
  - A Supabase Personal Access Token (PAT):
      https://supabase.com/dashboard/account/tokens
  - A Supabase Service Role Key (found in Project Settings → API):
      https://supabase.com/dashboard/project/<ref>/settings/api

Usage:
  python supabase-storage-copy.py backup  --project-ref <ref> --token <pat> --service-key <key>
  python supabase-storage-copy.py restore --project-ref <ref> --token <pat> --service-key <key>
  python supabase-storage-copy.py list    --project-ref <ref> --token <pat> --service-key <key>

Environment variables (alternative to CLI flags):
  SUPABASE_ACCESS_TOKEN      - Your PAT
  SUPABASE_SERVICE_ROLE_KEY  - Your service role key
  SUPABASE_PROJECT_REF       - The project reference ID
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
DEFAULT_BACKUP_DIR_PREFIX = "storage_backup"


def _default_backup_root() -> Path:
    """
    Return a safe, user-writable directory for storing backups.
    Resolves to ~/Documents/SupabaseTools to avoid writing into system
    directories (e.g. System32) when the exe is installed there.

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
    return "python supabase-storage-copy.py"

# Small courtesy delay between API calls to stay within rate limits.
REQUEST_DELAY_SECONDS = 0.1

# Storage API list endpoint returns up to this many objects per page.
LIST_PAGE_SIZE = 100


# ---------------------------------------------------------------------------
# API helper
# ---------------------------------------------------------------------------

class SupabaseStorageAPI:
    """
    Wraps both the Management API (bucket CRUD) and the Storage API
    (object list/download/upload) for a single Supabase project.
    """

    def __init__(self, project_ref: str, access_token: str, service_role_key: str):
        self.project_ref = project_ref
        self.storage_base = f"https://{project_ref}.supabase.co/storage/v1"

        # Management API uses the PAT
        self._mgmt = requests.Session()
        self._mgmt.headers.update({"Authorization": f"Bearer {access_token}"})

        # Storage API uses the service role key
        self._storage = requests.Session()
        self._storage.headers.update({
            "Authorization": f"Bearer {service_role_key}",
            "apikey": service_role_key,
        })

    # -- Buckets (Management API) ---------------------------------------------

    def list_buckets(self) -> list:
        """Return all storage buckets for this project."""
        url = f"{MANAGEMENT_API_BASE}/projects/{self.project_ref}/storage/buckets"
        resp = self._mgmt_get(url)
        return resp.json()

    def create_bucket(self, bucket_id: str, config: dict) -> dict:
        """
        Create a storage bucket. Uses bucket.json config fields where valid.

        Args:
            bucket_id (str): Bucket identifier.
            config (dict): Bucket config from backup (public, file_size_limit, etc.).

        Returns:
            dict: API response.
        """
        url = f"{MANAGEMENT_API_BASE}/projects/{self.project_ref}/storage/buckets"
        payload = {
            "id": bucket_id,
            "name": bucket_id,
            "public": config.get("public", False),
        }
        if config.get("file_size_limit"):
            payload["file_size_limit"] = config["file_size_limit"]
        if config.get("allowed_mime_types"):
            payload["allowed_mime_types"] = config["allowed_mime_types"]

        resp = self._mgmt.post(url, json=payload)
        if resp.status_code >= 400:
            raise RuntimeError(
                f"Create bucket '{bucket_id}' failed (HTTP {resp.status_code}): {resp.text}"
            )
        return resp.json()

    def update_bucket(self, bucket_id: str, config: dict) -> dict:
        """
        Update an existing storage bucket's configuration via the Storage API.

        Reason: The Management API has no PUT /storage/buckets endpoint —
        bucket config updates must go through the per-project Storage API.

        Args:
            bucket_id (str): Bucket identifier.
            config (dict): New config values.

        Returns:
            dict: API response.
        """
        url = f"{self.storage_base}/bucket/{bucket_id}"
        # Reason: only send public flag and mime types — file_size_limit is an
        # integer that some Storage API versions mishandle in PUT/PATCH bodies,
        # and overwriting it is rarely needed for a cross-project copy.
        payload = {"public": config.get("public", False)}
        if config.get("allowed_mime_types"):
            payload["allowed_mime_types"] = config["allowed_mime_types"]

        resp = self._storage.put(url, json=payload)
        if resp.status_code >= 400:
            raise RuntimeError(
                f"Update bucket '{bucket_id}' failed (HTTP {resp.status_code}): {resp.text}"
            )
        return resp.json()

    # -- Objects (Storage API) ------------------------------------------------

    def list_objects(self, bucket_id: str, prefix: str = "") -> list:
        """
        Recursively list all objects in a bucket.

        Args:
            bucket_id (str): Bucket identifier.
            prefix (str): Path prefix to list within (empty = root).

        Returns:
            list: Flat list of object paths (str).
        """
        all_objects = []
        self._list_recursive(bucket_id, prefix, all_objects)
        return all_objects

    def _list_recursive(self, bucket_id: str, prefix: str, results: list):
        """
        Walk the bucket tree depth-first via the Storage list endpoint.

        Args:
            bucket_id (str): Bucket to list.
            prefix (str): Current folder path.
            results (list): Accumulator for file paths.
        """
        url = f"{self.storage_base}/object/list/{bucket_id}"
        offset = 0

        while True:
            payload = {
                "prefix": prefix,
                "limit": LIST_PAGE_SIZE,
                "offset": offset,
                "sortBy": {"column": "name", "order": "asc"},
            }
            resp = self._storage.post(url, json=payload)
            if resp.status_code >= 400:
                raise RuntimeError(
                    f"List '{bucket_id}/{prefix}' failed (HTTP {resp.status_code}): {resp.text}"
                )

            items = resp.json()
            if not items:
                break

            for item in items:
                name = item.get("name", "")
                full_path = f"{prefix}/{name}".lstrip("/") if prefix else name

                if item.get("id") is None:
                    # Reason: items with no id are folders — recurse into them
                    self._list_recursive(bucket_id, full_path, results)
                else:
                    results.append(full_path)

            if len(items) < LIST_PAGE_SIZE:
                break
            offset += LIST_PAGE_SIZE

    def download_object(self, bucket_id: str, path: str) -> bytes:
        """
        Download a single object from storage.

        Args:
            bucket_id (str): Bucket identifier.
            path (str): Object path within the bucket.

        Returns:
            bytes: Raw file content.
        """
        url = f"{self.storage_base}/object/{bucket_id}/{path}"
        resp = self._storage.get(url, stream=True)
        if resp.status_code >= 400:
            raise RuntimeError(
                f"Download '{bucket_id}/{path}' failed (HTTP {resp.status_code}): {resp.text}"
            )
        return resp.content

    def upload_object(self, bucket_id: str, path: str, content: bytes, content_type: str = "application/octet-stream") -> dict:
        """
        Upload a single object to storage, creating or replacing it.

        Args:
            bucket_id (str): Target bucket identifier.
            path (str): Destination path within the bucket.
            content (bytes): File content to upload.
            content_type (str): MIME type for the upload.

        Returns:
            dict: API response.
        """
        url = f"{self.storage_base}/object/{bucket_id}/{path}"
        headers = {"Content-Type": content_type, "x-upsert": "true"}
        resp = self._storage.post(url, data=content, headers=headers)
        if resp.status_code >= 400:
            raise RuntimeError(
                f"Upload '{bucket_id}/{path}' failed (HTTP {resp.status_code}): {resp.text}"
            )
        return resp.json()

    # -- Internal helpers -----------------------------------------------------

    def _mgmt_get(self, url: str) -> requests.Response:
        """
        GET against the Management API with a single rate-limit retry.

        Args:
            url (str): Full URL to request.

        Returns:
            requests.Response: Successful response.
        """
        resp = self._mgmt.get(url)
        if resp.status_code == 429:
            wait = max(int(resp.headers.get("X-RateLimit-Reset", 5000)) / 1000, 1)
            print(f"  Rate-limited. Waiting {wait:.0f}s...")
            time.sleep(wait)
            resp = self._mgmt.get(url)
        if resp.status_code >= 400:
            raise RuntimeError(f"GET {url} failed (HTTP {resp.status_code}): {resp.text}")
        return resp


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _guess_content_type(filename: str) -> str:
    """
    Guess a MIME type from file extension. Falls back to octet-stream.

    Args:
        filename (str): Filename or path with extension.

    Returns:
        str: MIME type string.
    """
    ext = Path(filename).suffix.lower()
    mime_map = {
        # Images
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
        ".gif": "image/gif", ".webp": "image/webp", ".svg": "image/svg+xml",
        ".ico": "image/x-icon", ".bmp": "image/bmp", ".tiff": "image/tiff",
        ".avif": "image/avif", ".heic": "image/heic",
        # Video
        ".mp4": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime",
        ".avi": "video/x-msvideo", ".mkv": "video/x-matroska",
        ".m4v": "video/x-m4v", ".ogv": "video/ogg", ".3gp": "video/3gpp",
        # Audio
        ".mp3": "audio/mpeg", ".ogg": "audio/ogg", ".wav": "audio/wav",
        ".aac": "audio/aac", ".m4a": "audio/x-m4a", ".flac": "audio/flac",
        ".opus": "audio/opus", ".weba": "audio/webm",
        # Documents & data
        ".pdf": "application/pdf", ".json": "application/json",
        ".txt": "text/plain", ".csv": "text/csv", ".html": "text/html",
        ".htm": "text/html", ".css": "text/css", ".js": "application/javascript",
        ".ts": "application/typescript", ".xml": "application/xml",
        ".zip": "application/zip", ".gz": "application/gzip",
        ".tar": "application/x-tar",
        # Fonts
        ".woff": "font/woff", ".woff2": "font/woff2",
        ".ttf": "font/ttf", ".otf": "font/otf",
    }
    return mime_map.get(ext, "application/octet-stream")


# ---------------------------------------------------------------------------
# List logic
# ---------------------------------------------------------------------------

def do_list(api: SupabaseStorageAPI, show_files: bool = False):
    """
    Print all storage buckets and optionally their object counts.

    Args:
        api (SupabaseStorageAPI): Authenticated API wrapper.
        show_files (bool): If True, list object paths within each bucket.
    """
    print(f"\n Storage buckets on project: {api.project_ref}\n")

    buckets = api.list_buckets()
    if not buckets:
        print("  (none)")
        return

    for bucket in buckets:
        bid = bucket["id"]
        public = "public" if bucket.get("public") else "private"
        size_limit = bucket.get("file_size_limit")
        limit_str = f", max {size_limit // (1024*1024)}MB" if size_limit else ""
        print(f"  📦 {bid}  [{public}{limit_str}]")

        if show_files:
            try:
                objects = api.list_objects(bid)
                if objects:
                    for obj in objects:
                        print(f"       {obj}")
                else:
                    print("       (empty)")
            except RuntimeError as e:
                print(f"       ERROR listing objects: {e}")

    print(f"\n  Total: {len(buckets)} bucket(s)\n")


# ---------------------------------------------------------------------------
# Backup logic
# ---------------------------------------------------------------------------

def do_backup(api: SupabaseStorageAPI, backup_dir: str, buckets_filter: list = None):
    """
    Download all bucket configs and files to a local directory.

    Directory layout:
      <backup_dir>/
        manifest.json
        <bucket-id>/
          bucket.json       # bucket config
          files/
            path/to/file    # mirrors bucket object structure

    Args:
        api (SupabaseStorageAPI): Authenticated API wrapper.
        backup_dir (str): Local directory to write backup into.
        buckets_filter (list): Optional list of bucket IDs to limit backup to.
    """
    root = Path(backup_dir)
    project_ref = api.project_ref

    print(f"\n Backing up Storage for project: {project_ref}")
    print(f"   Destination: {root.resolve()}\n")

    buckets = api.list_buckets()
    if not buckets:
        print("  No storage buckets found. Nothing to back up.")
        return

    if buckets_filter:
        buckets = [b for b in buckets if b["id"] in buckets_filter]
        if not buckets:
            print(f"  No buckets matched filter: {buckets_filter}")
            return

    print(f"  Found {len(buckets)} bucket(s):\n")

    manifest = {
        "project_ref": project_ref,
        "backup_time": datetime.now(timezone.utc).isoformat(),
        "buckets": [],
    }

    for bucket in buckets:
        bid = bucket["id"]
        print(f"  📦 {bid}")

        bucket_dir = root / bid
        files_dir = bucket_dir / "files"
        files_dir.mkdir(parents=True, exist_ok=True)

        # Save bucket config
        bucket_path = bucket_dir / "bucket.json"
        bucket_path.write_text(json.dumps(bucket, indent=2))

        # List and download all objects
        try:
            objects = api.list_objects(bid)
        except RuntimeError as e:
            print(f"     ERROR listing objects: {e}")
            continue

        print(f"     {len(objects)} object(s)")

        downloaded = 0
        failed = 0
        total_bytes = 0

        for obj_path in objects:
            local_path = files_dir / obj_path
            local_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                content = api.download_object(bid, obj_path)
                local_path.write_bytes(content)
                total_bytes += len(content)
                downloaded += 1
                time.sleep(REQUEST_DELAY_SECONDS)
            except RuntimeError as e:
                print(f"     SKIP {obj_path}: {e}")
                failed += 1

        manifest["buckets"].append({
            "id": bid,
            "public": bucket.get("public", False),
            "file_size_limit": bucket.get("file_size_limit"),
            "allowed_mime_types": bucket.get("allowed_mime_types"),
            "object_count": downloaded,
            "total_bytes": total_bytes,
        })

        status = f"{downloaded} downloaded"
        if failed:
            status += f", {failed} failed"
        print(f"     {status} ({total_bytes / 1024:.1f} KB)")

    manifest_path = root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))

    print(f"\n  Backup complete. {len(manifest['buckets'])} bucket(s) saved.")
    print(f"  Manifest: {manifest_path.resolve()}")
    cmd = _exe_name()
    dir_arg = root.name
    print(f"\n  To restore these buckets:")
    print(f"    Same project:      {cmd} restore --project-ref {project_ref} --service-key <key>")
    print(f"    Different project: {cmd} restore --project-ref <target-ref> --service-key <key> --dir {dir_arg}")
    print(f"    e.g.               {cmd} restore --project-ref abcdefghijklmnop --service-key <key> --dir {dir_arg}")
    print()


# ---------------------------------------------------------------------------
# Restore logic
# ---------------------------------------------------------------------------

def do_restore(
    api: SupabaseStorageAPI,
    backup_dir: str,
    buckets_filter: list = None,
    mode: str = "merge",
    dry_run: bool = False,
):
    """
    Restore buckets and their files from a local backup to the target project.

    Args:
        api (SupabaseStorageAPI): Authenticated API wrapper for the TARGET project.
        backup_dir (str): Local directory containing the backup.
        buckets_filter (list): Optional list of bucket IDs to limit restore to.
        mode (str): Conflict resolution — 'skip', 'merge', or 'overwrite'.
        dry_run (bool): If True, preview actions without making any changes.
    """
    root = Path(backup_dir)
    manifest_path = root / "manifest.json"

    if not manifest_path.exists():
        print(f"ERROR: No manifest.json found in {root.resolve()}")
        print()
        print("  This usually means you are restoring from a DIFFERENT project's backup.")
        print("  Use --dir to point at the correct backup folder, e.g.:")
        print(f"    {_exe_name()} restore --project-ref {api.project_ref} --dir storage_backup_<source-ref>")
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
    all_buckets = manifest["buckets"]

    print(f"\n Restoring Storage to project: {api.project_ref}")
    print(f"   Source backup:    {root.resolve()}")
    print(f"   Backup taken:     {manifest['backup_time']}")
    print(f"   Original project: {manifest['project_ref']}")
    print(f"   Mode:             {mode}")
    if dry_run:
        print(f"   *** DRY RUN — no changes will be made ***")
    print()

    if buckets_filter:
        all_buckets = [b for b in all_buckets if b["id"] in buckets_filter]
        if not all_buckets:
            print(f"  No buckets matched filter: {buckets_filter}")
            return

    # Build a set of existing bucket IDs on the target
    try:
        existing = {b["id"] for b in api.list_buckets()}
    except RuntimeError as e:
        print(f"ERROR: Could not list existing buckets on target: {e}")
        sys.exit(1)

    print(f"  Will restore {len(all_buckets)} bucket(s) [{mode} mode]:\n")

    for bucket_info in all_buckets:
        bid = bucket_info["id"]
        bucket_dir = root / bid
        files_dir = bucket_dir / "files"

        # Load bucket config from backup
        bucket_config = bucket_info
        bucket_json_path = bucket_dir / "bucket.json"
        if bucket_json_path.exists():
            bucket_config = json.loads(bucket_json_path.read_text())

        already_exists = bid in existing

        print(f"  📦 {bid}  ({'exists' if already_exists else 'new'})")

        if already_exists and mode == "skip":
            print(f"     SKIP — bucket already exists (mode=skip)")
            continue

        # Create or update the bucket
        if not dry_run:
            try:
                if not already_exists:
                    api.create_bucket(bid, bucket_config)
                    print(f"     created bucket")
                elif mode == "overwrite":
                    api.update_bucket(bid, bucket_config)
                    print(f"     updated bucket config")
                # merge: bucket exists, don't alter config, just upload files
            except RuntimeError as e:
                print(f"     ERROR managing bucket: {e}")
                continue
        else:
            action = "Would create" if not already_exists else ("Would update config" if mode == "overwrite" else "Would merge into existing")
            print(f"     [DRY RUN] {action}")

        # Upload files
        if not files_dir.exists() or not any(files_dir.rglob("*")):
            print(f"     (no files in backup)")
            continue

        all_files = [f for f in sorted(files_dir.rglob("*")) if f.is_file()]
        uploaded = 0
        failed = 0
        total_bytes = 0

        for local_path in all_files:
            rel = local_path.relative_to(files_dir)
            obj_path = str(rel).replace("\\", "/")
            size = local_path.stat().st_size

            if dry_run:
                print(f"     [DRY RUN] Would upload: {obj_path} ({size:,} bytes)")
                uploaded += 1
                total_bytes += size
            else:
                content_type = _guess_content_type(local_path.name)
                try:
                    content = local_path.read_bytes()
                    api.upload_object(bid, obj_path, content, content_type)
                    uploaded += 1
                    total_bytes += size
                    time.sleep(REQUEST_DELAY_SECONDS)
                except RuntimeError as e:
                    print(f"     FAILED {obj_path}: {e}")
                    failed += 1

        status = f"{uploaded} file(s) uploaded ({total_bytes / 1024:.1f} KB)"
        if failed:
            status += f", {failed} failed"
        print(f"     {status}")

    action = "previewed" if dry_run else "restored"
    print(f"\n  Restore {action}. {len(all_buckets)} bucket(s) processed.\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    """Build and return the argument parser."""
    parser = argparse.ArgumentParser(
        description="Backup and restore Supabase Storage buckets via the Management and Storage APIs.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # List all buckets
  python %(prog)s list --project-ref abcdefghijkl --token sbp_xxx --service-key eyJ...

  # List buckets and their files
  python %(prog)s list --project-ref abcdefghijkl --token sbp_xxx --service-key eyJ... --files

  # Backup all buckets
  python %(prog)s backup --project-ref abcdefghijkl --token sbp_xxx --service-key eyJ...

  # Backup specific buckets only
  python %(prog)s backup --project-ref abcdefghijkl --buckets avatars documents

  # Restore to a different project (merge mode — default)
  python %(prog)s restore --project-ref newproject123 --token sbp_xxx --service-key eyJ... --dir storage_backup_abcdefghijkl

  # Restore and skip any buckets that already exist
  python %(prog)s restore --project-ref newproject123 --mode skip --dir storage_backup_abcdefghijkl

  # Overwrite existing buckets (update config + re-upload files)
  python %(prog)s restore --project-ref newproject123 --mode overwrite --dir storage_backup_abcdefghijkl

  # Preview what a restore would do (no changes made)
  python %(prog)s restore --project-ref newproject123 --dry-run --dir storage_backup_abcdefghijkl

Environment variables:
  SUPABASE_ACCESS_TOKEN      Your personal access token (alternative to --token)
  SUPABASE_SERVICE_ROLE_KEY  Your service role key (alternative to --service-key)
  SUPABASE_PROJECT_REF       Project reference (alternative to --project-ref)
""",
    )

    subparsers = parser.add_subparsers(dest="command")

    # -- Shared parent parser -------------------------------------------------
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
    parent.add_argument(
        "--service-key",
        default=os.environ.get("SUPABASE_SERVICE_ROLE_KEY"),
        help="Supabase service role key (or set SUPABASE_SERVICE_ROLE_KEY).",
    )

    # -- list -----------------------------------------------------------------
    lp = subparsers.add_parser(
        "list",
        parents=[parent],
        help="List all storage buckets on a project.",
    )
    lp.add_argument(
        "--files",
        action="store_true",
        help="Also list all objects within each bucket.",
    )

    # -- backup ---------------------------------------------------------------
    bp = subparsers.add_parser(
        "backup",
        parents=[parent],
        help="Download all storage buckets and files to a local directory.",
    )
    bp.add_argument(
        "--dir",
        default=None,
        help=(
            "Directory to save backups into. "
            f"Defaults to {DEFAULT_BACKUP_DIR_PREFIX}_<project-ref>."
        ),
    )
    bp.add_argument(
        "--buckets",
        nargs="+",
        default=None,
        help="Only back up these specific bucket IDs.",
    )

    # -- restore --------------------------------------------------------------
    rp = subparsers.add_parser(
        "restore",
        parents=[parent],
        help="Restore storage buckets and files from a backup directory.",
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
        "--buckets",
        nargs="+",
        default=None,
        help="Only restore these specific bucket IDs.",
    )
    rp.add_argument(
        "--mode",
        choices=["skip", "merge", "overwrite"],
        default="merge",
        help=(
            "How to handle buckets that already exist on the target: "
            "skip (leave untouched), merge (upload files only, default), "
            "overwrite (update config + re-upload files)."
        ),
    )
    rp.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview what would be restored without making any changes.",
    )

    return parser


def main():
    """Entry point — parse args, validate, dispatch to the correct command."""
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    subparser = parser._subparsers._actions[-1].choices[args.command]
    ok = True

    if not args.token:
        print("ERROR: Personal access token is required.")
        print("  Use --token <pat> or set SUPABASE_ACCESS_TOKEN.")
        print("  Get a token at: https://supabase.com/dashboard/account/tokens")
        ok = False

    if not args.project_ref:
        print("ERROR: Project reference is required.")
        print("  Use --project-ref <ref> or set SUPABASE_PROJECT_REF.")
        print("  Your project ref is in the dashboard URL: supabase.com/dashboard/project/<ref>")
        ok = False

    service_key = getattr(args, "service_key", None)
    if not service_key:
        print("ERROR: Service role key is required.")
        print("  Use --service-key <key> or set SUPABASE_SERVICE_ROLE_KEY.")
        print("  Find it at: https://supabase.com/dashboard/project/<ref>/settings/api")
        ok = False

    if not ok:
        print()
        subparser.print_help()
        sys.exit(1)

    api = SupabaseStorageAPI(args.project_ref, args.token, service_key)

    # Resolve --dir: explicit arg wins; otherwise use ~/Documents/SupabaseTools/<prefix>_<ref>
    # so backups are never written into system directories (e.g. System32).
    backup_dir = getattr(args, "dir", None) or str(_default_backup_root() / f"{DEFAULT_BACKUP_DIR_PREFIX}_{args.project_ref}")

    if args.command == "list":
        do_list(api, show_files=args.files)

    elif args.command == "backup":
        do_backup(api, backup_dir, buckets_filter=args.buckets)

    elif args.command == "restore":
        do_restore(
            api,
            backup_dir,
            buckets_filter=args.buckets,
            mode=args.mode,
            dry_run=args.dry_run,
        )


if __name__ == "__main__":
    main()
