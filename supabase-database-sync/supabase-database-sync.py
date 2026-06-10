#!/usr/bin/env python3
"""
Supabase Database Sync Tool
===========================

Sync table data from a source Supabase project to a target project.
Requires identical schemas and primary keys. Uses Management API only (PAT).

WARNING: This tool MODIFIES the TARGET database. Source is read-only.

Requirements:
  - Python 3.8+
  - requests library (pip install requests)
  - Personal Access Token from https://supabase.com/dashboard/account/tokens

Usage:
  python supabase-database-sync.py plan --source-ref SRC --target-ref TGT --token PAT
  python supabase-database-sync.py sync --source-ref SRC --target-ref TGT --token PAT [--mode upsert|mirror]
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    import requests
except ImportError:
    print("ERROR: 'requests' library is required. Install it with: pip install requests")
    sys.exit(1)


MANAGEMENT_API_BASE = "https://api.supabase.com/v1"
REQUEST_DELAY_SECONDS = 0.3
DEFAULT_SCHEMAS = ["public"]
IDENT_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


def _quote_ident(name: str) -> str:
    if not IDENT_RE.match(name):
        raise ValueError(f"Invalid SQL identifier: {name!r}")
    return f'"{name}"'


def _table_key(schema: str, table: str) -> str:
    return f"{schema}.{table}"


def _parse_table_key(key: str) -> tuple:
    schema, table = key.split(".", 1)
    return schema, table


def _qualified_table(schema: str, table: str) -> str:
    return f"{_quote_ident(schema)}.{_quote_ident(table)}"


# ---------------------------------------------------------------------------
# Progress
# ---------------------------------------------------------------------------

class Progress:
    def __init__(self, enabled: bool = True, width: int = 28):
        self.enabled = enabled and sys.stdout.isatty()
        self.width = width
        self.total = 0
        self.current = 0
        self._active = False

    def start(self, total: int, label: str = ""):
        self.total = max(total, 1)
        self.current = 0
        self._active = True
        self._draw(label)

    def step(self, label: str = ""):
        if not self._active:
            return
        self.current = min(self.current + 1, self.total)
        self._draw(label)

    def finish(self, label: str = "Done"):
        if not self.enabled:
            if label and self._active:
                print(f"  {label}")
            self._active = False
            return
        if self._active:
            self.current = self.total
            self._draw(label)
            sys.stdout.write("\n")
            sys.stdout.flush()
        self._active = False

    def _draw(self, label: str):
        if not self.enabled:
            if label:
                print(f"  {label}")
            return
        filled = int(self.width * self.current / self.total)
        bar = "#" * filled + "-" * (self.width - filled)
        pct = int(100 * self.current / self.total)
        sys.stdout.write(f"\r  [{bar}] {self.current}/{self.total} ({pct:3d}%) {label[:55]:<55}")
        sys.stdout.flush()


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

class SupabaseManagementAPI:
    def __init__(self, access_token: str):
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        })

    def query_read_only(self, project_ref: str, sql: str) -> list:
        return self._query(project_ref, sql, read_only=True)

    def query_write(self, project_ref: str, sql: str) -> list:
        return self._query(project_ref, sql, read_only=False)

    def _query(self, project_ref: str, sql: str, read_only: bool) -> list:
        path = "database/query/read-only" if read_only else "database/query"
        url = f"{MANAGEMENT_API_BASE}/projects/{project_ref}/{path}"
        resp = self._post(url, {"query": sql})
        data = resp.json()
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            if "result" in data and isinstance(data["result"], list):
                return data["result"]
            if "rows" in data and isinstance(data["rows"], list):
                return data["rows"]
        return []

    def _post(self, url: str, payload: dict) -> requests.Response:
        resp = self.session.post(url, json=payload)
        if resp.status_code == 429:
            wait = max(int(resp.headers.get("X-RateLimit-Reset", 5000)) / 1000, 1)
            print(f"  Rate-limited. Waiting {wait:.0f}s...")
            time.sleep(wait)
            resp = self.session.post(url, json=payload)
        if resp.status_code >= 400:
            raise RuntimeError(f"POST failed (HTTP {resp.status_code}): {resp.text}")
        time.sleep(REQUEST_DELAY_SECONDS)
        return resp


# ---------------------------------------------------------------------------
# SQL helpers
# ---------------------------------------------------------------------------

def _sql_literal(value) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (dict, list)):
        escaped = json.dumps(value).replace("'", "''")
        return f"'{escaped}'::jsonb"
    s = str(value).replace("'", "''")
    return f"'{s}'"


def _schemas_sql_list(schemas: list) -> str:
    return f"ARRAY[{', '.join(repr(s) for s in schemas)}]"


# ---------------------------------------------------------------------------
# Schema introspection
# ---------------------------------------------------------------------------

def collect_tables(api: SupabaseManagementAPI, project_ref: str, schemas: list) -> dict:
    sql = f"""
        SELECT table_schema, table_name FROM information_schema.tables
        WHERE table_schema = ANY({_schemas_sql_list(schemas)}) AND table_type = 'BASE TABLE'
        ORDER BY 1, 2;
    """
    rows = api.query_read_only(project_ref, sql)
    return {
        _table_key(r["table_schema"], r["table_name"]): {"schema": r["table_schema"], "table": r["table_name"]}
        for r in rows if r.get("table_schema") and r.get("table_name")
    }


def collect_columns(api: SupabaseManagementAPI, project_ref: str, schema: str, table: str) -> list:
    sql = f"""
        SELECT column_name, data_type, is_nullable, column_default, ordinal_position
        FROM information_schema.columns
        WHERE table_schema = '{schema}' AND table_name = '{table}'
        ORDER BY ordinal_position;
    """
    return api.query_read_only(project_ref, sql)


def collect_primary_key_columns(api: SupabaseManagementAPI, project_ref: str, schema: str, table: str) -> list:
    sql = f"""
        SELECT kcu.column_name FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON tc.constraint_name = kcu.constraint_name
         AND tc.table_schema = kcu.table_schema AND tc.table_name = kcu.table_name
        WHERE tc.constraint_type = 'PRIMARY KEY'
          AND tc.table_schema = '{schema}' AND tc.table_name = '{table}'
        ORDER BY kcu.ordinal_position;
    """
    return [r["column_name"] for r in api.query_read_only(project_ref, sql) if r.get("column_name")]


def diff_columns(source_cols: list, target_cols: list) -> dict:
    src_map = {c["column_name"]: c for c in source_cols}
    tgt_map = {c["column_name"]: c for c in target_cols}
    only_source = sorted(set(src_map) - set(tgt_map))
    only_target = sorted(set(tgt_map) - set(src_map))
    different = []
    for name in sorted(set(src_map) & set(tgt_map)):
        s, t = src_map[name], tgt_map[name]
        if (s["data_type"], s["is_nullable"], s["column_default"]) != (
            t["data_type"], t["is_nullable"], t["column_default"]
        ):
            different.append(name)
    return {
        "identical": not only_source and not only_target and not different,
        "only_in_source": only_source,
        "only_in_target": only_target,
        "different": different,
    }


def collect_fk_edges(api: SupabaseManagementAPI, project_ref: str, schemas: list) -> list:
    sql = f"""
        SELECT tc.table_schema AS child_schema, tc.table_name AS child_table,
               ccu.table_schema AS parent_schema, ccu.table_name AS parent_table
        FROM information_schema.table_constraints tc
        JOIN information_schema.constraint_column_usage ccu
          ON tc.constraint_name = ccu.constraint_name AND tc.table_schema = ccu.table_schema
        WHERE tc.constraint_type = 'FOREIGN KEY'
          AND tc.table_schema = ANY({_schemas_sql_list(schemas)});
    """
    edges = []
    for r in api.query_read_only(project_ref, sql):
        child = _table_key(r["child_schema"], r["child_table"])
        parent = _table_key(r["parent_schema"], r["parent_table"])
        edges.append((child, parent))
    return edges


def sort_tables_by_fk(table_keys: list, fk_edges: list) -> list:
    """Return table keys in FK order (parents before children)."""
    keys = set(table_keys)
    deps = {k: set() for k in keys}
    for child, parent in fk_edges:
        if child in keys and parent in keys and child != parent:
            deps[child].add(parent)
    ordered = []
    remaining = set(keys)
    while remaining:
        ready = sorted(k for k in remaining if not (deps[k] & remaining))
        if not ready:
            ordered.extend(sorted(remaining))
            break
        ordered.extend(ready)
        remaining -= set(ready)
    return ordered


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_table_for_sync(
    api: SupabaseManagementAPI,
    source_ref: str,
    target_ref: str,
    table_key: str,
) -> dict:
    schema, table = _parse_table_key(table_key)
    src_cols = collect_columns(api, source_ref, schema, table)
    tgt_cols = collect_columns(api, target_ref, schema, table)
    if not src_cols:
        return {"ok": False, "reason": "Table not found on source"}
    if not tgt_cols:
        return {"ok": False, "reason": "Table not found on target"}
    col_diff = diff_columns(src_cols, tgt_cols)
    if not col_diff["identical"]:
        return {"ok": False, "reason": f"Schema mismatch: {col_diff}"}
    pk_cols = collect_primary_key_columns(api, source_ref, schema, table)
    if not pk_cols:
        return {"ok": False, "reason": "No primary key — sync blocked"}
    col_names = [c["column_name"] for c in src_cols]
    return {
        "ok": True,
        "schema": schema,
        "table": table,
        "columns": col_names,
        "primary_key": pk_cols,
    }


def resolve_table_list(
    api: SupabaseManagementAPI,
    source_ref: str,
    target_ref: str,
    schemas: list,
    tables_filter: list,
    from_report: str,
) -> tuple:
    source_tables = collect_tables(api, source_ref, schemas)
    target_tables = collect_tables(api, target_ref, schemas)
    shared = sorted(set(source_tables) & set(target_tables))

    if from_report:
        report_path = Path(from_report)
        if not report_path.is_absolute():
            candidate = Path.home() / "Documents" / "SupabaseTools" / from_report
            if candidate.exists():
                report_path = candidate
        report = json.loads(report_path.read_text(encoding="utf-8"))
        sync_asm = report.get("sync_assessment", {}).get("tables", {})
        shared = [k for k in shared if sync_asm.get(k, {}).get("syncable", True)]

    if tables_filter:
        allowed = set()
        for name in tables_filter:
            if "." in name:
                allowed.add(name)
            else:
                for k in shared:
                    if k.endswith(f".{name}"):
                        allowed.add(k)
        shared = [k for k in shared if k in allowed]

    return shared, source_tables, target_tables


# ---------------------------------------------------------------------------
# Sync engine
# ---------------------------------------------------------------------------

def fetch_all_rows(api: SupabaseManagementAPI, project_ref: str, schema: str, table: str,
                   pk_cols: list, batch_size: int, progress: Progress = None) -> list:
    qual = _qualified_table(schema, table)
    order = ", ".join(_quote_ident(c) for c in pk_cols) if pk_cols else "1"
    all_rows = []
    offset = 0
    while True:
        sql = f"SELECT * FROM {qual} ORDER BY {order} LIMIT {batch_size} OFFSET {offset};"
        batch = api.query_read_only(project_ref, sql)
        if not batch:
            break
        all_rows.extend(batch)
        if progress:
            progress.step(f"Read {table}: {len(all_rows)} rows")
        if len(batch) < batch_size:
            break
        offset += batch_size
    return all_rows


def _pk_tuple(row: dict, pk_cols: list) -> tuple:
    return tuple(row.get(c) for c in pk_cols)


def upsert_batch(api: SupabaseManagementAPI, target_ref: str, schema: str, table: str,
                 columns: list, pk_cols: list, rows: list, dry_run: bool) -> int:
    if not rows:
        return 0
    qual = _qualified_table(schema, table)
    col_list = ", ".join(_quote_ident(c) for c in columns)
    pk_list = ", ".join(_quote_ident(c) for c in pk_cols)
    update_cols = [c for c in columns if c not in pk_cols]
    value_rows = []
    for row in rows:
        vals = ", ".join(_sql_literal(row.get(c)) for c in columns)
        value_rows.append(f"({vals})")
    values_sql = ",\n".join(value_rows)
    if update_cols:
        set_clause = ", ".join(f'{_quote_ident(c)} = EXCLUDED.{_quote_ident(c)}' for c in update_cols)
        conflict = f"ON CONFLICT ({pk_list}) DO UPDATE SET {set_clause}"
    else:
        conflict = f"ON CONFLICT ({pk_list}) DO NOTHING"
    sql = f"INSERT INTO {qual} ({col_list}) VALUES\n{values_sql}\n{conflict};"
    if dry_run:
        return len(rows)
    api.query_write(target_ref, sql)
    return len(rows)


def delete_orphans_batch(
    api: SupabaseManagementAPI,
    target_ref: str,
    schema: str,
    table: str,
    pk_cols: list,
    source_pk_values: set,
    dry_run: bool,
    batch_size: int = 500,
) -> int:
    qual = _qualified_table(schema, table)
    if len(pk_cols) != 1:
        return 0

    pk = _quote_ident(pk_cols[0])
    if not source_pk_values:
        cnt_sql = f"SELECT COUNT(*)::bigint AS cnt FROM {qual};"
        rows = api.query_read_only(target_ref, cnt_sql)
        total = int(rows[0]["cnt"]) if rows else 0
        if dry_run:
            return total
        api.query_write(target_ref, f"DELETE FROM {qual};")
        return total

    source_flat = source_pk_values
    deleted = 0
    offset = 0
    while True:
        sql = f"SELECT {_quote_ident(pk_cols[0])} AS pk FROM {qual} ORDER BY {_quote_ident(pk_cols[0])} LIMIT {batch_size} OFFSET {offset};"
        batch = api.query_read_only(target_ref, sql)
        if not batch:
            break
        orphans = [r["pk"] for r in batch if r.get("pk") not in source_flat]
        if orphans:
            for i in range(0, len(orphans), batch_size):
                chunk = orphans[i:i + batch_size]
                literals = ", ".join(_sql_literal(v) for v in chunk)
                if dry_run:
                    deleted += len(chunk)
                else:
                    api.query_write(target_ref, f"DELETE FROM {qual} WHERE {pk} IN ({literals});")
                    deleted += len(chunk)
        if len(batch) < batch_size:
            break
        offset += batch_size
    return deleted


def sync_table_upsert(
    api: SupabaseManagementAPI,
    source_ref: str,
    target_ref: str,
    table_key: str,
    batch_size: int,
    dry_run: bool,
    progress: Progress = None,
) -> dict:
    meta = validate_table_for_sync(api, source_ref, target_ref, table_key)
    if not meta["ok"]:
        return {"table": table_key, "skipped": True, "reason": meta["reason"]}

    schema, table = meta["schema"], meta["table"]
    columns, pk_cols = meta["columns"], meta["primary_key"]

    rows = fetch_all_rows(api, source_ref, schema, table, pk_cols, batch_size, progress)
    upserted = 0
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        upserted += upsert_batch(api, target_ref, schema, table, columns, pk_cols, batch, dry_run)

    source_pks = {_pk_tuple(r, pk_cols) for r in rows}
    return {
        "table": table_key,
        "skipped": False,
        "schema": schema,
        "table_name": table,
        "primary_key": pk_cols,
        "rows_read": len(rows),
        "rows_upserted": upserted,
        "rows_deleted": 0,
        "source_pks": source_pks,
    }


def mirror_delete_orphans(
    api: SupabaseManagementAPI,
    target_ref: str,
    sync_result: dict,
    batch_size: int,
    dry_run: bool,
) -> int:
    if sync_result.get("skipped"):
        return 0
    schema = sync_result["schema"]
    table = sync_result["table_name"]
    pk_cols = sync_result["primary_key"]
    source_pks = sync_result["source_pks"]
    if len(pk_cols) == 1:
        flat_pks = {t[0] for t in source_pks}
        return delete_orphans_batch(
            api, target_ref, schema, table, pk_cols, flat_pks, dry_run, batch_size=batch_size
        )
    tgt_rows = fetch_all_rows(api, target_ref, schema, table, pk_cols, batch_size)
    orphan_pks = [_pk_tuple(r, pk_cols) for r in tgt_rows if _pk_tuple(r, pk_cols) not in source_pks]
    if dry_run:
        return len(orphan_pks)
    deleted = 0
    for pk_val in orphan_pks:
        where = " AND ".join(
            f"{_quote_ident(pk_cols[i])} = {_sql_literal(pk_val[i])}" for i in range(len(pk_cols))
        )
        api.query_write(target_ref, f"DELETE FROM {_qualified_table(schema, table)} WHERE {where};")
        deleted += 1
    return deleted


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def _print_plan_header(source_ref: str, target_ref: str, mode: str, dry_run: bool):
    print(f"\n {'[DRY RUN] ' if dry_run else ''}Sync plan")
    print(f"   SOURCE (read-only): {source_ref}")
    print(f"   TARGET (will be modified): {target_ref}")
    print(f"   Mode: {mode}")
    if mode == "mirror":
        print("   Mirror: upsert + delete target rows not in source")
    else:
        print("   Upsert: insert/update from source; extra target rows kept")
    print()


def do_sync(
    api: SupabaseManagementAPI,
    source_ref: str,
    target_ref: str,
    schemas: list,
    tables_filter: list,
    from_report: str,
    mode: str,
    batch_size: int,
    dry_run: bool,
    quiet: bool,
):
    _print_plan_header(source_ref, target_ref, mode, dry_run)
    table_keys, _, _ = resolve_table_list(api, source_ref, target_ref, schemas, tables_filter, from_report)
    fk_edges = collect_fk_edges(api, source_ref, schemas)
    ordered = sort_tables_by_fk(table_keys, fk_edges)

    print("  Pre-flight validation:\n")
    to_sync = []
    for key in ordered:
        meta = validate_table_for_sync(api, source_ref, target_ref, key)
        if meta["ok"]:
            print(f"    OK  {key}")
            to_sync.append(key)
        else:
            print(f"    SKIP {key} — {meta['reason']}")

    if not to_sync:
        print("\n  No tables to sync. Aborting.\n")
        return

    if not dry_run:
        print("\n  WARNING: This will MODIFY data on the TARGET project.")
        print(f"  TARGET: {target_ref}\n")
        confirm_ref = input("  Type the TARGET project ref to confirm: ").strip()
        if confirm_ref != target_ref:
            print("  Aborted — target ref did not match.\n")
            return
        confirm_sync = input("  Type YES SYNC to confirm: ").strip()
        if confirm_sync != "YES SYNC":
            print("  Aborted — confirmation not received.\n")
            return

    progress = Progress(enabled=not quiet)
    total_steps = len(to_sync) * (2 if mode == "mirror" else 1)
    progress.start(total_steps, "Sync starting")
    results = []
    for key in ordered:
        if key not in to_sync:
            continue
        progress.step(f"Upsert {key}")
        try:
            result = sync_table_upsert(
                api, source_ref, target_ref, key, batch_size, dry_run, progress
            )
            results.append(result)
        except RuntimeError as e:
            results.append({"table": key, "skipped": True, "reason": str(e)})

    if mode == "mirror":
        for key in reversed(ordered):
            if key not in to_sync:
                continue
            progress.step(f"Mirror delete {key}")
            match = next((r for r in results if r.get("table") == key and not r.get("skipped")), None)
            if not match:
                continue
            try:
                match["rows_deleted"] = mirror_delete_orphans(
                    api, target_ref, match, batch_size, dry_run
                )
            except RuntimeError as e:
                match["delete_error"] = str(e)

    progress.finish("Sync complete")

    print(f"\n  {'[DRY RUN] ' if dry_run else ''}Results:\n")
    total_upserted = 0
    total_deleted = 0
    for r in results:
        if r.get("skipped"):
            print(f"    SKIP {r['table']}: {r.get('reason', '?')}")
        else:
            deleted = r.get("rows_deleted", 0)
            total_upserted += r["rows_upserted"]
            total_deleted += deleted
            print(
                f"    {r['table']}: read {r['rows_read']}, "
                f"upserted {r['rows_upserted']}, deleted {deleted}"
            )
            if r.get("delete_error"):
                print(f"           delete error: {r['delete_error']}")
    if dry_run:
        print(
            f"\n  Dry-run summary: {total_upserted} row(s) would be upserted"
            + (f", {total_deleted} row(s) would be deleted (mirror)" if mode == "mirror" else "")
        )
        print("  No changes were made. Run sync without --dry-run to apply (requires confirmation).\n")
    else:
        print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Sync table data from source to target Supabase project. MODIFIES TARGET.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python %(prog)s plan --source-ref sourceref --target-ref targetref --token sbp_xxx
  python %(prog)s sync --source-ref sourceref --target-ref targetref --token sbp_xxx --dry-run
  python %(prog)s sync --source-ref sourceref --target-ref targetref --mode mirror --dry-run
  python %(prog)s sync --from-report compare_sourceref_vs_targetref_20260101.json --dry-run

Run supabase-database-compare first to check sync feasibility.

Environment variables:
  SUPABASE_ACCESS_TOKEN         Personal access token
  SUPABASE_SOURCE_PROJECT_REF   Source project ref
  SUPABASE_TARGET_PROJECT_REF   Target project ref
""",
    )
    subparsers = parser.add_subparsers(dest="command")

    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument("--token", default=os.environ.get("SUPABASE_ACCESS_TOKEN"))
    parent.add_argument("--source-ref", default=os.environ.get("SUPABASE_SOURCE_PROJECT_REF"))
    parent.add_argument("--target-ref", default=os.environ.get("SUPABASE_TARGET_PROJECT_REF"))

    for cmd in ("plan", "sync"):
        help_text = "Full dry-run preview (no writes)." if cmd == "plan" else "Execute table data sync."
        p = subparsers.add_parser(cmd, parents=[parent], help=help_text)
        p.add_argument("--schemas", nargs="+", default=DEFAULT_SCHEMAS)
        p.add_argument("--tables", nargs="+", default=None)
        p.add_argument("--from-report", default=None, help="Compare JSON report to filter syncable tables.")
        p.add_argument("--mode", choices=["upsert", "mirror"], default="upsert")
        p.add_argument("--batch-size", type=int, default=200)
        p.add_argument(
            "--dry-run",
            action="store_true",
            help="Full preview: validate, simulate upserts and mirror deletes, no writes.",
        )
        p.add_argument("--quiet", action="store_true")

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(0)
    if not args.token:
        print("ERROR: --token or SUPABASE_ACCESS_TOKEN required.")
        sys.exit(1)
    if not args.source_ref or not args.target_ref:
        print("ERROR: --source-ref and --target-ref required.")
        sys.exit(1)

    api = SupabaseManagementAPI(args.token)

    dry_run = args.command == "plan" or args.dry_run
    do_sync(
        api, args.source_ref, args.target_ref, args.schemas, args.tables,
        args.from_report, args.mode, args.batch_size, dry_run, args.quiet,
    )


if __name__ == "__main__":
    main()
