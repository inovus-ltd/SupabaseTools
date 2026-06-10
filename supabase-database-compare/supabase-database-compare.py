#!/usr/bin/env python3
"""
Supabase Database Compare Tool
==============================

Compare two Supabase projects: table schemas, Edge Functions, table data,
and estimated last-write times. 100% non-destructive — read-only Management
API only (PAT required). Never modifies source or target projects.

Requirements:
  - Python 3.8+
  - requests library (pip install requests)
  - A Supabase Personal Access Token from:
    https://supabase.com/dashboard/account/tokens

Usage:
  python supabase-database-compare.py list --project-ref <ref> --token <pat>
  python supabase-database-compare.py compare --source-ref <ref> --target-ref <ref> --token <pat>

Environment variables:
  SUPABASE_ACCESS_TOKEN        Personal access token
  SUPABASE_PROJECT_REF         Project ref (list command)
  SUPABASE_SOURCE_PROJECT_REF  Source project ref (compare)
  SUPABASE_TARGET_PROJECT_REF  Target project ref (compare)
"""

import argparse
import hashlib
import html
import json
import os
import re
import sys
import time
import webbrowser
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
TIMESTAMP_COLUMN_PRIORITY = ("updated_at", "modified_at", "last_modified", "created_at")
EDGE_META_FIELDS = ("name", "verify_jwt", "entrypoint_path", "import_map_path", "status")
IDENT_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


def _default_report_root() -> Path:
    base = Path.home() / "Documents" / "SupabaseTools"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _exe_name() -> str:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).name
    return "python supabase-database-compare.py"


def _quote_ident(name: str) -> str:
    if not IDENT_RE.match(name):
        raise ValueError(f"Invalid SQL identifier: {name!r}")
    return f'"{name}"'


def _table_key(schema: str, table: str) -> str:
    return f"{schema}.{table}"


def _parse_table_key(key: str) -> tuple:
    schema, table = key.split(".", 1)
    return schema, table


# ---------------------------------------------------------------------------
# Progress
# ---------------------------------------------------------------------------

class Progress:
    """Simple terminal progress bar (stdlib only, works in PowerShell/CMD)."""

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
        text = f"\r  [{bar}] {self.current}/{self.total} ({pct:3d}%) {label[:55]:<55}"
        sys.stdout.write(text)
        sys.stdout.flush()


# ---------------------------------------------------------------------------
# API helper
# ---------------------------------------------------------------------------

class SupabaseManagementAPI:
    """Thin wrapper around Supabase Management API endpoints."""

    def __init__(self, access_token: str):
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        })

    def query_read_only(self, project_ref: str, sql: str) -> list:
        url = f"{MANAGEMENT_API_BASE}/projects/{project_ref}/database/query/read-only"
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

    def list_functions(self, project_ref: str) -> list:
        url = f"{MANAGEMENT_API_BASE}/projects/{project_ref}/functions"
        resp = self._get(url)
        return resp.json()

    def get_function_meta(self, project_ref: str, slug: str) -> dict:
        url = f"{MANAGEMENT_API_BASE}/projects/{project_ref}/functions/{slug}"
        resp = self._get(url)
        return resp.json()

    def get_function_source_files(self, project_ref: str, slug: str) -> list:
        url = f"{MANAGEMENT_API_BASE}/projects/{project_ref}/functions/{slug}/body"
        resp = self._get(url, headers={"Accept": "multipart/form-data"}, stream=True)
        content_type = resp.headers.get("Content-Type", "")
        if "multipart" not in content_type:
            return [{"filename": "function.eszip", "content": resp.content}]
        boundary = None
        for part in content_type.split(";"):
            part = part.strip()
            if part.startswith("boundary="):
                boundary = part[len("boundary="):].strip('"')
                break
        if not boundary:
            return [{"filename": "function.eszip", "content": resp.content}]
        return _parse_multipart(resp.content, boundary)

    def _get(self, url: str, **kwargs) -> requests.Response:
        resp = self.session.get(url, **kwargs)
        if resp.status_code == 429:
            retry_ms = int(resp.headers.get("X-RateLimit-Reset", 5000))
            wait = max(retry_ms / 1000, 1)
            print(f"  Rate-limited. Waiting {wait:.0f}s before retrying...")
            time.sleep(wait)
            resp = self.session.get(url, **kwargs)
        if resp.status_code >= 400:
            raise RuntimeError(f"GET {url} failed (HTTP {resp.status_code}): {resp.text}")
        time.sleep(REQUEST_DELAY_SECONDS)
        return resp

    def _post(self, url: str, payload: dict) -> requests.Response:
        resp = self.session.post(url, json=payload)
        if resp.status_code == 429:
            retry_ms = int(resp.headers.get("X-RateLimit-Reset", 5000))
            wait = max(retry_ms / 1000, 1)
            print(f"  Rate-limited. Waiting {wait:.0f}s before retrying...")
            time.sleep(wait)
            resp = self.session.post(url, json=payload)
        if resp.status_code >= 400:
            raise RuntimeError(f"POST {url} failed (HTTP {resp.status_code}): {resp.text}")
        time.sleep(REQUEST_DELAY_SECONDS)
        return resp


def _parse_multipart(body: bytes, boundary: str) -> list:
    delimiter = f"--{boundary}".encode()
    parts = body.split(delimiter)
    files = []
    for part in parts:
        if not part or part == b"--\r\n" or part == b"--":
            continue
        if b"\r\n\r\n" not in part:
            continue
        headers_raw, content = part.split(b"\r\n\r\n", 1)
        content = content.rstrip(b"\r\n")
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
            normalized = Path(filename.replace("file://", ""))
            parts_path = normalized.parts
            if "source" in parts_path:
                idx = list(parts_path).index("source")
                filename = str(Path(*parts_path[idx + 1:]))
            else:
                filename = normalized.name
            files.append({"filename": filename, "content": content})
    return files if files else [{"filename": "function.eszip", "content": body}]


# ---------------------------------------------------------------------------
# Schema collectors
# ---------------------------------------------------------------------------

def _schemas_sql_list(schemas: list) -> str:
    quoted = ", ".join(f"'{s}'" for s in schemas)
    return f"ARRAY[{quoted}]"


def collect_tables(api: SupabaseManagementAPI, project_ref: str, schemas: list) -> dict:
    sql = f"""
        SELECT table_schema, table_name
        FROM information_schema.tables
        WHERE table_schema = ANY({_schemas_sql_list(schemas)})
          AND table_type = 'BASE TABLE'
        ORDER BY table_schema, table_name;
    """
    rows = api.query_read_only(project_ref, sql)
    tables = {}
    for row in rows:
        schema = row.get("table_schema") or row.get("table_schema".upper())
        name = row.get("table_name") or row.get("table_name".upper())
        if schema and name:
            tables[_table_key(schema, name)] = {"schema": schema, "table": name}
    return tables


def collect_columns(api: SupabaseManagementAPI, project_ref: str, schema: str, table: str) -> list:
    sql = f"""
        SELECT column_name, data_type, is_nullable, column_default, ordinal_position
        FROM information_schema.columns
        WHERE table_schema = '{schema}' AND table_name = '{table}'
        ORDER BY ordinal_position;
    """
    rows = api.query_read_only(project_ref, sql)
    columns = []
    for row in rows:
        columns.append({
            "column_name": row.get("column_name"),
            "data_type": row.get("data_type"),
            "is_nullable": row.get("is_nullable"),
            "column_default": row.get("column_default"),
            "ordinal_position": row.get("ordinal_position"),
        })
    return columns


def collect_primary_key_columns(api: SupabaseManagementAPI, project_ref: str, schema: str, table: str) -> list:
    sql = f"""
        SELECT kcu.column_name
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON tc.constraint_name = kcu.constraint_name
         AND tc.table_schema = kcu.table_schema
         AND tc.table_name = kcu.table_name
        WHERE tc.constraint_type = 'PRIMARY KEY'
          AND tc.table_schema = '{schema}'
          AND tc.table_name = '{table}'
        ORDER BY kcu.ordinal_position;
    """
    rows = api.query_read_only(project_ref, sql)
    return [r.get("column_name") for r in rows if r.get("column_name")]


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
            different.append({
                "column": name,
                "source": s,
                "target": t,
            })
    return {
        "identical": not only_source and not only_target and not different,
        "only_in_source": only_source,
        "only_in_target": only_target,
        "different": different,
    }


def compare_table_schemas(
    api: SupabaseManagementAPI,
    source_ref: str,
    target_ref: str,
    schemas: list,
    progress: Progress = None,
) -> dict:
    if progress:
        progress.start(2 + 1, "Listing tables on source")
    source_tables = collect_tables(api, source_ref, schemas)
    if progress:
        progress.step("Listing tables on target")
    target_tables = collect_tables(api, target_ref, schemas)
    source_keys = set(source_tables)
    target_keys = set(target_tables)
    only_source = sorted(source_keys - target_keys)
    only_target = sorted(target_keys - source_keys)
    shared = sorted(source_keys & target_keys)
    if progress:
        progress.total = 2 + max(len(shared) * 2, 1)
        progress.current = 2
    identical = []
    different = []
    for i, key in enumerate(shared):
        schema, table = _parse_table_key(key)
        if progress:
            progress.step(f"Schema columns: {key} ({i + 1}/{len(shared)})")
        src_cols = collect_columns(api, source_ref, schema, table)
        if progress:
            progress.step(f"Schema columns: {key} target")
        tgt_cols = collect_columns(api, target_ref, schema, table)
        col_diff = diff_columns(src_cols, tgt_cols)
        entry = {"table": key, "column_diff": col_diff}
        if col_diff["identical"]:
            identical.append(key)
        else:
            different.append(entry)
    if progress:
        progress.finish("Table schemas complete")
    return {
        "only_in_source": only_source,
        "only_in_target": only_target,
        "identical": identical,
        "different": different,
    }


# ---------------------------------------------------------------------------
# Edge Function collectors
# ---------------------------------------------------------------------------

def _function_source_hash(source_files: list) -> str:
    parts = []
    for sf in sorted(source_files, key=lambda x: x["filename"]):
        parts.append(sf["filename"].encode())
        parts.append(sf["content"])
    digest = hashlib.sha256(b"".join(parts)).hexdigest()
    return digest


def _function_meta_subset(meta: dict) -> dict:
    return {k: meta.get(k) for k in EDGE_META_FIELDS}


def collect_edge_functions(
    api: SupabaseManagementAPI,
    project_ref: str,
    include_hashes: bool = True,
    progress: Progress = None,
    label: str = "",
) -> dict:
    functions = api.list_functions(project_ref)
    total = max(len(functions) * (3 if include_hashes else 2), 1)
    if progress:
        progress.start(total, f"{label}: listing functions")
    result = {}
    for i, fn in enumerate(functions):
        slug = fn["slug"]
        if progress:
            progress.step(f"{label}: {slug} metadata ({i + 1}/{len(functions)})")
        meta = api.get_function_meta(project_ref, slug)
        entry = {
            "slug": slug,
            "list_meta": fn,
            "meta": _function_meta_subset(meta),
            "source_hash": None,
        }
        if include_hashes:
            if progress:
                progress.step(f"{label}: {slug} source")
            source_files = api.get_function_source_files(project_ref, slug)
            entry["source_hash"] = _function_source_hash(source_files)
        result[slug] = entry
    if progress:
        progress.finish(f"{label}: Edge Functions complete")
    return result


def compare_edge_functions(
    api: SupabaseManagementAPI,
    source_ref: str,
    target_ref: str,
    progress: Progress = None,
) -> dict:
    source_fns = collect_edge_functions(api, source_ref, progress=progress, label="Source")
    target_fns = collect_edge_functions(api, target_ref, progress=progress, label="Target")
    source_slugs = set(source_fns)
    target_slugs = set(target_fns)
    only_source = sorted(source_slugs - target_slugs)
    only_target = sorted(target_slugs - source_slugs)
    identical = []
    different = []
    for slug in sorted(source_slugs & target_slugs):
        s, t = source_fns[slug], target_fns[slug]
        meta_match = s["meta"] == t["meta"]
        hash_match = s["source_hash"] == t["source_hash"]
        if meta_match and hash_match:
            identical.append(slug)
        else:
            reasons = []
            if not meta_match:
                reasons.append("metadata")
            if not hash_match:
                reasons.append("source")
            different.append({
                "slug": slug,
                "reasons": reasons,
                "source_meta": s["meta"],
                "target_meta": t["meta"],
                "source_hash": s["source_hash"],
                "target_hash": t["source_hash"],
            })
    return {
        "only_in_source": only_source,
        "only_in_target": only_target,
        "identical": identical,
        "different": different,
    }


# ---------------------------------------------------------------------------
# Data comparison
# ---------------------------------------------------------------------------

def _qualified_table(schema: str, table: str) -> str:
    return f"{_quote_ident(schema)}.{_quote_ident(table)}"


def get_row_count(api: SupabaseManagementAPI, project_ref: str, schema: str, table: str) -> int:
    sql = f"SELECT COUNT(*)::bigint AS cnt FROM {_qualified_table(schema, table)};"
    rows = api.query_read_only(project_ref, sql)
    if not rows:
        return 0
    val = rows[0].get("cnt")
    return int(val) if val is not None else 0


def get_table_checksum(api: SupabaseManagementAPI, project_ref: str, schema: str, table: str, pk_cols: list) -> str:
    qual = _qualified_table(schema, table)
    if pk_cols:
        order_expr = ", ".join(_quote_ident(c) for c in pk_cols)
        sql = f"""
            SELECT md5(coalesce(string_agg(row_data, '' ORDER BY row_data), '')) AS checksum
            FROM (
                SELECT t::text AS row_data
                FROM {qual} t
                ORDER BY {order_expr}
            ) sub;
        """
    else:
        sql = f"""
            SELECT md5(coalesce(string_agg(row_data, '' ORDER BY row_data), '')) AS checksum
            FROM (
                SELECT t::text AS row_data
                FROM {qual} t
                ORDER BY t::text
            ) sub;
        """
    rows = api.query_read_only(project_ref, sql)
    if not rows:
        return ""
    return rows[0].get("checksum") or ""


def fetch_table_rows(api: SupabaseManagementAPI, project_ref: str, schema: str, table: str,
                     pk_cols: list, max_rows: int) -> list:
    qual = _qualified_table(schema, table)
    if pk_cols:
        order_expr = ", ".join(_quote_ident(c) for c in pk_cols)
    else:
        order_expr = "ctid"
    sql = f"SELECT * FROM {qual} ORDER BY {order_expr} LIMIT {int(max_rows)};"
    return api.query_read_only(project_ref, sql)


def _row_pk_key(row: dict, pk_cols: list) -> tuple:
    if pk_cols:
        return tuple(row.get(c) for c in pk_cols)
    return (json.dumps(row, sort_keys=True, default=str),)


def compare_table_data_summary(
    api: SupabaseManagementAPI,
    source_ref: str,
    target_ref: str,
    table_keys: list,
    progress: Progress = None,
) -> dict:
    matching = []
    different = []
    total_steps = max(len(table_keys) * 5, 1)
    if progress:
        progress.start(total_steps, "Data: starting")
    for i, key in enumerate(table_keys):
        schema, table = _parse_table_key(key)
        if progress:
            progress.step(f"Data: {key} PK ({i + 1}/{len(table_keys)})")
        pk_cols = collect_primary_key_columns(api, source_ref, schema, table)
        if progress:
            progress.step(f"Data: {key} row counts")
        src_count = get_row_count(api, source_ref, schema, table)
        tgt_count = get_row_count(api, target_ref, schema, table)
        if progress:
            progress.step(f"Data: {key} source checksum")
        src_checksum = get_table_checksum(api, source_ref, schema, table, pk_cols)
        if progress:
            progress.step(f"Data: {key} target checksum")
        tgt_checksum = get_table_checksum(api, target_ref, schema, table, pk_cols)
        entry = {
            "table": key,
            "source_row_count": src_count,
            "target_row_count": tgt_count,
            "source_checksum": src_checksum,
            "target_checksum": tgt_checksum,
            "row_count_match": src_count == tgt_count,
            "checksum_match": src_checksum == tgt_checksum and src_checksum != "",
        }
        if entry["row_count_match"] and entry["checksum_match"]:
            matching.append(key)
        else:
            different.append(entry)
    if progress:
        progress.finish("Data summary complete")
    return {"matching": matching, "different": different}


def compare_table_data_deep(
    api: SupabaseManagementAPI,
    source_ref: str,
    target_ref: str,
    table_keys: list,
    max_rows: int,
    explicit_tables: bool,
    progress: Progress = None,
) -> dict:
    results = []
    total_steps = max(len(table_keys) * 4, 1)
    if progress:
        progress.start(total_steps, "Data deep: starting")
    for i, key in enumerate(table_keys):
        schema, table = _parse_table_key(key)
        if progress:
            progress.step(f"Data deep: {key} ({i + 1}/{len(table_keys)})")
        pk_cols = collect_primary_key_columns(api, source_ref, schema, table)
        src_count = get_row_count(api, source_ref, schema, table)
        tgt_count = get_row_count(api, target_ref, schema, table)
        if not explicit_tables and (src_count > max_rows or tgt_count > max_rows):
            results.append({
                "table": key,
                "skipped": True,
                "reason": f"row count exceeds --max-rows ({max_rows}); use --tables to force",
                "source_row_count": src_count,
                "target_row_count": tgt_count,
            })
            continue
        if progress:
            progress.step(f"Data deep: {key} fetch rows")
        src_rows = fetch_table_rows(api, source_ref, schema, table, pk_cols, max_rows)
        tgt_rows = fetch_table_rows(api, target_ref, schema, table, pk_cols, max_rows)
        src_map = {_row_pk_key(r, pk_cols): r for r in src_rows}
        tgt_map = {_row_pk_key(r, pk_cols): r for r in tgt_rows}
        src_keys = set(src_map)
        tgt_keys = set(tgt_map)
        only_source = [src_map[k] for k in sorted(src_keys - tgt_keys, key=str)]
        only_target = [tgt_map[k] for k in sorted(tgt_keys - src_keys, key=str)]
        changed = []
        for k in sorted(src_keys & tgt_keys, key=str):
            if src_map[k] != tgt_map[k]:
                changed.append({
                    "key": list(k) if pk_cols else k,
                    "source": src_map[k],
                    "target": tgt_map[k],
                })
        results.append({
            "table": key,
            "skipped": False,
            "source_row_count": src_count,
            "target_row_count": tgt_count,
            "rows_compared": max(len(src_rows), len(tgt_rows)),
            "only_in_source": only_source,
            "only_in_target": only_target,
            "changed": changed,
            "identical": not only_source and not only_target and not changed,
        })
    if progress:
        progress.finish("Data deep complete")
    return {"tables": results}


# ---------------------------------------------------------------------------
# Last write estimates
# ---------------------------------------------------------------------------

def _find_timestamp_column(api: SupabaseManagementAPI, project_ref: str, schema: str, table: str) -> str:
    cols_sql = ", ".join(f"'{c}'" for c in TIMESTAMP_COLUMN_PRIORITY)
    sql = f"""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = '{schema}' AND table_name = '{table}'
          AND column_name IN ({cols_sql})
        ORDER BY CASE column_name
            WHEN 'updated_at' THEN 1
            WHEN 'modified_at' THEN 2
            WHEN 'last_modified' THEN 3
            WHEN 'created_at' THEN 4
            ELSE 5 END
        LIMIT 1;
    """
    rows = api.query_read_only(project_ref, sql)
    if rows and rows[0].get("column_name"):
        return rows[0]["column_name"]
    return ""


def estimate_last_write(api: SupabaseManagementAPI, project_ref: str, schema: str, table: str) -> dict:
    col = _find_timestamp_column(api, project_ref, schema, table)
    if col:
        qual = _qualified_table(schema, table)
        sql = f"SELECT MAX({_quote_ident(col)}) AS last_write FROM {qual};"
        rows = api.query_read_only(project_ref, sql)
        val = rows[0].get("last_write") if rows else None
        return {
            "method": f"max({col})",
            "last_write_estimate": val,
            "column": col,
        }
    stats_sql = f"""
        SELECT n_tup_ins, n_tup_upd, n_tup_del, last_autovacuum, last_autoanalyze
        FROM pg_stat_user_tables
        WHERE schemaname = '{schema}' AND relname = '{table}';
    """
    rows = api.query_read_only(project_ref, stats_sql)
    if rows:
        row = rows[0]
        return {
            "method": "pg_stat_user_tables",
            "last_write_estimate": None,
            "note": "No timestamp column found; stats are since last reset, not absolute last-write time",
            "stats": {
                "n_tup_ins": row.get("n_tup_ins"),
                "n_tup_upd": row.get("n_tup_upd"),
                "n_tup_del": row.get("n_tup_del"),
                "last_autovacuum": row.get("last_autovacuum"),
                "last_autoanalyze": row.get("last_autoanalyze"),
            },
        }
    return {
        "method": "unavailable",
        "last_write_estimate": None,
        "note": "No timestamp column or pg_stat data found",
    }


def collect_last_write_estimates(
    api: SupabaseManagementAPI,
    project_ref: str,
    table_keys: list,
    progress: Progress = None,
    label: str = "",
) -> dict:
    estimates = {}
    if progress:
        progress.start(max(len(table_keys), 1), f"{label}: last-write estimates")
    for i, key in enumerate(table_keys):
        schema, table = _parse_table_key(key)
        if progress:
            progress.step(f"{label}: {key} ({i + 1}/{len(table_keys)})")
        estimates[key] = estimate_last_write(api, project_ref, schema, table)
    if progress:
        progress.finish(f"{label}: last-write complete")
    return estimates


# ---------------------------------------------------------------------------
# Report output
# ---------------------------------------------------------------------------

def _default_output_path(source_ref: str, target_ref: str, ext: str = ".json") -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    name = f"compare_{source_ref}_vs_{target_ref}_{ts}{ext}"
    return str(_default_report_root() / name)


def _format_last_write_value(entry: dict) -> str:
    val = entry.get("last_write_estimate")
    if val is not None:
        return str(val)
    if entry.get("method") == "pg_stat_user_tables":
        stats = entry.get("stats") or {}
        return (
            f"ins={stats.get('n_tup_ins', '?')} "
            f"upd={stats.get('n_tup_upd', '?')} "
            f"del={stats.get('n_tup_del', '?')}"
        )
    return "unavailable"


def _format_column_spec(col: dict) -> str:
    nullable = "NULL" if col.get("is_nullable") == "YES" else "NOT NULL"
    default = col.get("column_default")
    default_s = f" default={default}" if default else ""
    return f"{col.get('data_type')} {nullable}{default_s}"


def _print_schema_column_diff(table_entry: dict, source_ref: str, target_ref: str):
    cd = table_entry["column_diff"]
    table = table_entry["table"]
    if cd.get("only_in_source"):
        print(f"       columns only in SOURCE ({source_ref}):")
        for col in cd["only_in_source"]:
            print(f"         + {col}")
    if cd.get("only_in_target"):
        print(f"       columns only in TARGET ({target_ref}):")
        for col in cd["only_in_target"]:
            print(f"         + {col}")
    for diff in cd.get("different", []):
        name = diff["column"]
        src = _format_column_spec(diff["source"])
        tgt = _format_column_spec(diff["target"])
        print(f"       column {name}:")
        print(f"         SOURCE ({source_ref}): {src}")
        print(f"         TARGET ({target_ref}): {tgt}")


def print_text_report(report: dict):
    source_ref = report["source_ref"]
    target_ref = report["target_ref"]
    print(f"\n Comparing databases")
    print(f"   SOURCE: {source_ref}")
    print(f"   TARGET: {target_ref}")
    print(f"   Compared at: {report['compared_at']}\n")

    ts = report["tables"]
    print(" Tables (schema)")
    print(f"   Only in SOURCE ({source_ref}): {len(ts['only_in_source'])}")
    if ts["only_in_source"]:
        print(f"     {', '.join(ts['only_in_source'])}")
    print(f"   Only in TARGET ({target_ref}): {len(ts['only_in_target'])}")
    if ts["only_in_target"]:
        print(f"     {', '.join(ts['only_in_target'])}")
    print(f"   Identical schema: {len(ts['identical'])}")
    print(f"   Different schema: {len(ts['different'])}")
    for entry in ts["different"]:
        print(f"     {entry['table']}:")
        _print_schema_column_diff(entry, source_ref, target_ref)
    print()

    if report.get("edge_functions") is not None:
        ef = report["edge_functions"]
        print(" Edge Functions")
        print(f"   Only in SOURCE ({source_ref}): {len(ef['only_in_source'])}")
        if ef["only_in_source"]:
            print(f"     {', '.join(ef['only_in_source'])}")
        print(f"   Only in TARGET ({target_ref}): {len(ef['only_in_target'])}")
        if ef["only_in_target"]:
            print(f"     {', '.join(ef['only_in_target'])}")
        print(f"   Identical:      {len(ef['identical'])}")
        print(f"   Different:      {len(ef['different'])}")
        for d in ef["different"]:
            print(f"     {d['slug']} ({', '.join(d['reasons'])})")
        print()

    if report.get("data") is not None:
        data = report["data"]
        if "matching" in data:
            print(" Data (summary)")
            print(f"   Matching:  {len(data['matching'])} tables")
            print(f"   Different: {len(data['different'])} tables")
            for d in data["different"]:
                print(
                    f"     {d['table']}: "
                    f"SOURCE={d['source_row_count']} TARGET={d['target_row_count']} rows, "
                    f"checksum {'match' if d['checksum_match'] else 'mismatch'}"
                )
            print()
        elif "tables" in data:
            print(" Data (deep)")
            for t in data["tables"]:
                if t.get("skipped"):
                    print(f"   {t['table']}: SKIPPED — {t['reason']}")
                    continue
                status = "identical" if t["identical"] else "different"
                print(
                    f"   {t['table']}: {status} "
                    f"({len(t['only_in_source'])} only source, "
                    f"{len(t['only_in_target'])} only target, "
                    f"{len(t['changed'])} changed)"
                )
            print()

    if report.get("last_write"):
        print(" Last write estimates")
        lw = report["last_write"]
        for key in sorted(lw["source"].keys()):
            s = lw["source"][key]
            t = lw["target"][key]
            print(f"   {key}")
            print(f"     SOURCE ({source_ref}): {_format_last_write_value(s)} ({s.get('method', '?')})")
            print(f"     TARGET ({target_ref}): {_format_last_write_value(t)} ({t.get('method', '?')})")
        print()


def _category_score(identical: int, partial: int, missing: int) -> float:
    """Score 0-100: identical=100, partial=50, missing/exclusive=0."""
    total = identical + partial + missing
    if total == 0:
        return 100.0
    return (identical * 100 + partial * 50) / total


def _tier_from_score(score: float) -> tuple:
    if score >= 90:
        return "green", "Identical"
    if score >= 70:
        return "lime", "Mostly Similar"
    if score >= 50:
        return "yellow", "Partially Similar"
    if score >= 25:
        return "amber", "Mostly Different"
    return "red", "Not Similar"


def _compute_similarity(report: dict) -> dict:
    """Overall and per-category similarity ratings."""
    categories = []

    ts = report["tables"]
    schema_total = (
        len(ts["identical"]) + len(ts["different"])
        + len(ts["only_in_source"]) + len(ts["only_in_target"])
    )
    if schema_total:
        schema_score = _category_score(
            len(ts["identical"]), len(ts["different"]),
            len(ts["only_in_source"]) + len(ts["only_in_target"]),
        )
        tier, label = _tier_from_score(schema_score)
        categories.append({"name": "Table Schemas", "score": schema_score, "tier": tier, "label": label})

    ef = report.get("edge_functions")
    if ef is not None:
        ef_total = (
            len(ef["identical"]) + len(ef["different"])
            + len(ef["only_in_source"]) + len(ef["only_in_target"])
        )
        if ef_total:
            ef_score = _category_score(
                len(ef["identical"]), len(ef["different"]),
                len(ef["only_in_source"]) + len(ef["only_in_target"]),
            )
        else:
            ef_score = 100.0
        tier, label = _tier_from_score(ef_score)
        categories.append({"name": "Edge Functions", "score": ef_score, "tier": tier, "label": label})

    data = report.get("data")
    if data is not None:
        if "matching" in data:
            data_total = len(data["matching"]) + len(data["different"])
            if data_total:
                data_score = len(data["matching"]) / data_total * 100
                tier, label = _tier_from_score(data_score)
                categories.append({"name": "Table Data", "score": data_score, "tier": tier, "label": label})
        elif "tables" in data:
            tables = [t for t in data["tables"] if not t.get("skipped")]
            if tables:
                identical = sum(1 for t in tables if t.get("identical"))
                data_score = identical / len(tables) * 100
                tier, label = _tier_from_score(data_score)
                categories.append({"name": "Table Data", "score": data_score, "tier": tier, "label": label})

    if not categories:
        return {"score": 100, "tier": "green", "label": "Identical", "categories": []}

    weights = {"Table Schemas": 35, "Edge Functions": 25, "Table Data": 40}
    total_w = sum(weights.get(c["name"], 33) for c in categories)
    overall = sum(c["score"] * weights.get(c["name"], 33) for c in categories) / total_w
    tier, label = _tier_from_score(overall)
    return {"score": round(overall, 1), "tier": tier, "label": label, "categories": categories}


def _open_in_browser(path: Path):
    uri = path.resolve().as_uri()
    try:
        webbrowser.open(uri)
    except Exception as e:
        print(f"  Could not open browser: {e}")
        print(f"  Open manually: {path.resolve()}")


def write_html_report(report: dict) -> str:
    """Return a self-contained, Apple-inspired HTML compare report."""
    source_ref = report["source_ref"]
    target_ref = report["target_ref"]
    compared_at = report.get("compared_at", "")
    sim = _compute_similarity(report)
    esc = lambda v: html.escape(str(v)) if v is not None else "—"
    tier = sim["tier"]
    score = sim["score"]

    def pill(label, t):
        return f'<span class="pill pill-{t}">{esc(label)}</span>'

    def meter(score_val, t):
        return (
            f'<div class="meter meter-{t}"><div class="meter-fill" style="width:{min(score_val, 100):.0f}%"></div></div>'
            f'<span class="meter-pct">{score_val:.0f}%</span>'
        )

    parts = [f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(sim['label'])} — {esc(source_ref)} vs {esc(target_ref)}</title>
<style>
  :root {{
    --bg: #f5f5f7; --surface: #ffffff; --surface2: #fbfbfd;
    --text: #1d1d1f; --muted: #86868b; --hairline: rgba(0,0,0,.08);
    --green: #34c759; --green-bg: #e8f8ec; --green-text: #1a7f37;
    --lime: #a8e063; --lime-bg: #f4fce8; --lime-text: #4d7c0f;
    --yellow: #ffcc00; --yellow-bg: #fff9e6; --yellow-text: #9a6700;
    --amber: #ff9500; --amber-bg: #fff4e5; --amber-text: #c93400;
    --red: #ff3b30; --red-bg: #ffebea; --red-text: #d70015;
    --source: #0071e3; --source-bg: #e8f1fb;
    --target: #5856d6; --target-bg: #ededfc;
    --radius: 18px; --shadow: 0 2px 16px rgba(0,0,0,.06);
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    background: var(--bg); color: var(--text); line-height: 1.47;
    -webkit-font-smoothing: antialiased;
  }}
  .page {{ max-width: 1080px; margin: 0 auto; padding: 32px 24px 64px; }}
  .hero {{
    background: var(--surface); border-radius: 24px; box-shadow: var(--shadow);
    padding: 40px 36px; margin-bottom: 28px; text-align: center;
  }}
  .hero-eyebrow {{ font-size: 13px; font-weight: 600; letter-spacing: .06em; text-transform: uppercase; color: var(--muted); margin-bottom: 8px; }}
  .hero h1 {{ font-size: 34px; font-weight: 700; letter-spacing: -.02em; margin-bottom: 6px; }}
  .hero-sub {{ color: var(--muted); font-size: 15px; margin-bottom: 28px; }}
  .score-ring {{
    width: 160px; height: 160px; border-radius: 50%; margin: 0 auto 16px;
    display: flex; flex-direction: column; align-items: center; justify-content: center;
    border: 6px solid; font-weight: 700;
  }}
  .score-ring-green {{ border-color: var(--green); background: var(--green-bg); color: var(--green-text); }}
  .score-ring-lime {{ border-color: var(--lime); background: var(--lime-bg); color: var(--lime-text); }}
  .score-ring-yellow {{ border-color: var(--yellow); background: var(--yellow-bg); color: var(--yellow-text); }}
  .score-ring-amber {{ border-color: var(--amber); background: var(--amber-bg); color: var(--amber-text); }}
  .score-ring-red {{ border-color: var(--red); background: var(--red-bg); color: var(--red-text); }}
  .score-num {{ font-size: 42px; line-height: 1; letter-spacing: -.03em; }}
  .score-label {{ font-size: 15px; font-weight: 600; margin-top: 4px; }}
  .verdict {{ font-size: 22px; font-weight: 600; margin-bottom: 20px; }}
  .projects {{ display: flex; gap: 12px; justify-content: center; flex-wrap: wrap; }}
  .proj {{
    padding: 10px 18px; border-radius: 980px; font-size: 13px; font-weight: 600;
    font-family: ui-monospace, "SF Mono", Menlo, monospace;
  }}
  .proj-source {{ background: var(--source-bg); color: var(--source); }}
  .proj-target {{ background: var(--target-bg); color: var(--target); }}
  .proj span {{ font-weight: 400; opacity: .7; margin-right: 6px; font-family: inherit; }}
  .cat-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 14px; margin-bottom: 28px; }}
  .cat-card {{
    background: var(--surface); border-radius: var(--radius); box-shadow: var(--shadow);
    padding: 20px 22px;
  }}
  .cat-card h3 {{ font-size: 13px; color: var(--muted); font-weight: 600; text-transform: uppercase; letter-spacing: .04em; margin-bottom: 10px; }}
  .cat-row {{ display: flex; align-items: center; gap: 10px; }}
  .meter {{ flex: 1; height: 8px; background: #e8e8ed; border-radius: 99px; overflow: hidden; }}
  .meter-fill {{ height: 100%; border-radius: 99px; transition: width .4s; }}
  .meter-green .meter-fill {{ background: var(--green); }}
  .meter-lime .meter-fill {{ background: var(--lime); }}
  .meter-yellow .meter-fill {{ background: var(--yellow); }}
  .meter-amber .meter-fill {{ background: var(--amber); }}
  .meter-red .meter-fill {{ background: var(--red); }}
  .meter-pct {{ font-size: 15px; font-weight: 600; min-width: 38px; text-align: right; }}
  .section {{
    background: var(--surface); border-radius: var(--radius); box-shadow: var(--shadow);
    padding: 28px 28px 24px; margin-bottom: 20px;
  }}
  .section-head {{ display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 10px; margin-bottom: 20px; }}
  .section h2 {{ font-size: 22px; font-weight: 700; letter-spacing: -.02em; }}
  .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 10px; margin-bottom: 20px; }}
  .stat {{
    background: var(--surface2); border-radius: 14px; padding: 14px 16px; text-align: center;
    border: 1px solid var(--hairline);
  }}
  .stat .n {{ font-size: 28px; font-weight: 700; letter-spacing: -.02em; }}
  .stat .l {{ font-size: 12px; color: var(--muted); margin-top: 2px; }}
  .stat-green .n {{ color: var(--green-text); }}
  .stat-yellow .n {{ color: var(--yellow-text); }}
  .stat-red .n {{ color: var(--red-text); }}
  .pill {{
    display: inline-block; padding: 4px 12px; border-radius: 980px;
    font-size: 12px; font-weight: 600; white-space: nowrap;
  }}
  .pill-green {{ background: var(--green-bg); color: var(--green-text); }}
  .pill-lime {{ background: var(--lime-bg); color: var(--lime-text); }}
  .pill-yellow {{ background: var(--yellow-bg); color: var(--yellow-text); }}
  .pill-amber {{ background: var(--amber-bg); color: var(--amber-text); }}
  .pill-red {{ background: var(--red-bg); color: var(--red-text); }}
  table {{ width: 100%; border-collapse: separate; border-spacing: 0; font-size: 14px; }}
  thead th {{
    text-align: left; padding: 12px 14px; font-size: 12px; font-weight: 600;
    color: var(--muted); text-transform: uppercase; letter-spacing: .04em;
    border-bottom: 1px solid var(--hairline); background: var(--surface2);
  }}
  thead th:first-child {{ border-radius: 12px 0 0 0; }}
  thead th:last-child {{ border-radius: 0 12px 0 0; }}
  tbody td {{ padding: 13px 14px; border-bottom: 1px solid var(--hairline); vertical-align: top; }}
  tbody tr:last-child td {{ border-bottom: none; }}
  tbody tr:hover {{ background: var(--surface2); }}
  .row-green {{ background: var(--green-bg); }}
  .row-yellow {{ background: var(--yellow-bg); }}
  .row-red {{ background: var(--red-bg); }}
  th.th-source {{ color: var(--source); }}
  th.th-target {{ color: var(--target); }}
  .mono {{ font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace; font-size: 13px; }}
  .detail-card {{
    background: var(--surface2); border-radius: 14px; padding: 18px 20px;
    margin-top: 14px; border: 1px solid var(--hairline);
  }}
  .detail-card h4 {{ font-size: 15px; font-weight: 600; margin-bottom: 12px; }}
  .col-list {{ list-style: none; margin: 8px 0; }}
  .col-list li {{ padding: 6px 0; font-size: 14px; }}
  .col-list li::before {{ content: "● "; }}
  .col-list-src li::before {{ color: var(--source); }}
  .col-list-tgt li::before {{ color: var(--target); }}
  .footer {{ text-align: center; color: var(--muted); font-size: 12px; margin-top: 32px; }}
  .legend-bar {{
    display: flex; gap: 16px; justify-content: center; flex-wrap: wrap;
    margin: 20px 0 0; font-size: 12px; color: var(--muted);
  }}
  .legend-item {{ display: flex; align-items: center; gap: 6px; }}
  .dot {{ width: 10px; height: 10px; border-radius: 50%; }}
  .dot-green {{ background: var(--green); }}
  .dot-yellow {{ background: var(--yellow); }}
  .dot-red {{ background: var(--red); }}
</style>
</head>
<body>
<div class="page">
  <div class="hero">
    <div class="hero-eyebrow">Supabase Database Compare</div>
    <h1>Similarity Report</h1>
    <p class="hero-sub">{esc(compared_at)}</p>
    <div class="score-ring score-ring-{tier}">
      <div class="score-num">{score:.0f}</div>
      <div class="score-label">/ 100</div>
    </div>
    <div class="verdict">{pill(sim['label'], tier)}</div>
    <div class="projects">
      <div class="proj proj-source"><span>Source</span>{esc(source_ref)}</div>
      <div class="proj proj-target"><span>Target</span>{esc(target_ref)}</div>
    </div>
    <div class="legend-bar">
      <div class="legend-item"><span class="dot dot-green"></span> Identical / Similar</div>
      <div class="legend-item"><span class="dot dot-yellow"></span> Partially Similar</div>
      <div class="legend-item"><span class="dot dot-red"></span> Different / Not Similar</div>
    </div>
  </div>
  <div class="cat-grid">
"""]

    for cat in sim["categories"]:
        parts.append(f"""    <div class="cat-card">
      <h3>{esc(cat['name'])}</h3>
      <div class="cat-row">{meter(cat['score'], cat['tier'])}{pill(cat['label'], cat['tier'])}</div>
    </div>""")

    parts.append("  </div>")

    # --- Tables ---
    ts = report["tables"]
    schema_tier, schema_lbl = _tier_from_score(
        _category_score(len(ts["identical"]), len(ts["different"]),
                        len(ts["only_in_source"]) + len(ts["only_in_target"])) if (
            len(ts["identical"]) + len(ts["different"]) + len(ts["only_in_source"]) + len(ts["only_in_target"])
        ) else 100
    )
    parts.append(f"""  <div class="section">
    <div class="section-head"><h2>Table Schemas</h2>{pill(schema_lbl, schema_tier)}</div>
    <div class="stats">
      <div class="stat stat-green"><div class="n">{len(ts['identical'])}</div><div class="l">Identical</div></div>
      <div class="stat stat-yellow"><div class="n">{len(ts['different'])}</div><div class="l">Different</div></div>
      <div class="stat stat-red"><div class="n">{len(ts['only_in_source'])}</div><div class="l">Only Source</div></div>
      <div class="stat stat-red"><div class="n">{len(ts['only_in_target'])}</div><div class="l">Only Target</div></div>
    </div>""")

    if ts["only_in_source"] or ts["only_in_target"]:
        parts.append("<table><thead><tr><th>Status</th><th>Table</th></tr></thead><tbody>")
        for t in ts["only_in_source"]:
            parts.append(f'<tr class="row-red"><td>{pill("Only in Source", "red")}</td><td class="mono">{esc(t)}</td></tr>')
        for t in ts["only_in_target"]:
            parts.append(f'<tr class="row-red"><td>{pill("Only in Target", "red")}</td><td class="mono">{esc(t)}</td></tr>')
        parts.append("</tbody></table>")

    for entry in ts["different"]:
        cd = entry["column_diff"]
        parts.append(f'<div class="detail-card"><h4 class="mono">{esc(entry["table"])}</h4>')
        parts.append(f'<div style="margin-bottom:10px">{pill("Schema Differs", "yellow")}</div>')
        if cd.get("only_in_source"):
            parts.append(f'<p style="font-size:13px;color:var(--muted);margin-bottom:6px">Columns only in <strong>Source</strong></p><ul class="col-list col-list-src">')
            for col in cd["only_in_source"]:
                parts.append(f"<li class='mono'>{esc(col)}</li>")
            parts.append("</ul>")
        if cd.get("only_in_target"):
            parts.append(f'<p style="font-size:13px;color:var(--muted);margin:10px 0 6px">Columns only in <strong>Target</strong></p><ul class="col-list col-list-tgt">')
            for col in cd["only_in_target"]:
                parts.append(f"<li class='mono'>{esc(col)}</li>")
            parts.append("</ul>")
        if cd.get("different"):
            parts.append("<table><thead><tr><th>Column</th><th class='th-source'>Source</th><th class='th-target'>Target</th></tr></thead><tbody>")
            for diff in cd["different"]:
                parts.append(
                    f'<tr class="row-yellow"><td class="mono">{esc(diff["column"])}</td>'
                    f'<td class="mono">{esc(_format_column_spec(diff["source"]))}</td>'
                    f'<td class="mono">{esc(_format_column_spec(diff["target"]))}</td></tr>'
                )
            parts.append("</tbody></table>")
        parts.append("</div>")

    if ts["identical"]:
        parts.append(f'<p style="margin-top:16px;font-size:14px;color:var(--muted)">{len(ts["identical"])} table(s) with identical schema: <span class="mono">{esc(", ".join(ts["identical"]))}</span></p>')

    parts.append("  </div>")

    # --- Edge Functions ---
    if report.get("edge_functions") is not None:
        ef = report["edge_functions"]
        ef_total = len(ef["identical"]) + len(ef["different"]) + len(ef["only_in_source"]) + len(ef["only_in_target"])
        ef_score = _category_score(len(ef["identical"]), len(ef["different"]),
                                   len(ef["only_in_source"]) + len(ef["only_in_target"])) if ef_total else 100
        ef_tier, ef_lbl = _tier_from_score(ef_score)
        parts.append(f"""  <div class="section">
    <div class="section-head"><h2>Edge Functions</h2>{pill(ef_lbl, ef_tier)}</div>
    <div class="stats">
      <div class="stat stat-green"><div class="n">{len(ef['identical'])}</div><div class="l">Identical</div></div>
      <div class="stat stat-yellow"><div class="n">{len(ef['different'])}</div><div class="l">Different</div></div>
      <div class="stat stat-red"><div class="n">{len(ef['only_in_source'])}</div><div class="l">Only Source</div></div>
      <div class="stat stat-red"><div class="n">{len(ef['only_in_target'])}</div><div class="l">Only Target</div></div>
    </div><table><thead><tr><th>Status</th><th>Function</th><th>Details</th></tr></thead><tbody>""")
        for slug in ef["only_in_source"]:
            parts.append(f'<tr class="row-red"><td>{pill("Only Source", "red")}</td><td class="mono">{esc(slug)}</td><td>—</td></tr>')
        for slug in ef["only_in_target"]:
            parts.append(f'<tr class="row-red"><td>{pill("Only Target", "red")}</td><td class="mono">{esc(slug)}</td><td>—</td></tr>')
        for slug in ef["identical"]:
            parts.append(f'<tr class="row-green"><td>{pill("Identical", "green")}</td><td class="mono">{esc(slug)}</td><td>Metadata &amp; source match</td></tr>')
        for d in ef["different"]:
            parts.append(
                f'<tr class="row-yellow"><td>{pill("Different", "yellow")}</td>'
                f'<td class="mono">{esc(d["slug"])}</td>'
                f'<td>{esc(", ".join(d["reasons"]))}</td></tr>'
            )
        parts.append("</tbody></table></div>")

    # --- Data ---
    if report.get("data") is not None:
        data = report["data"]
        parts.append('  <div class="section"><div class="section-head"><h2>Table Data</h2>')
        if "matching" in data:
            dt = len(data["matching"]) + len(data["different"])
            ds = len(data["matching"]) / dt * 100 if dt else 100
            dt_tier, dt_lbl = _tier_from_score(ds)
            parts.append(f'{pill(dt_lbl, dt_tier)}</div>')
            parts.append(f'<div class="stats"><div class="stat stat-green"><div class="n">{len(data["matching"])}</div><div class="l">Matching</div></div>')
            parts.append(f'<div class="stat stat-red"><div class="n">{len(data["different"])}</div><div class="l">Different</div></div></div>')
            parts.append("<table><thead><tr><th>Status</th><th>Table</th><th class='th-source'>Source Rows</th><th class='th-target'>Target Rows</th><th>Checksum</th></tr></thead><tbody>")
            for key in data["matching"]:
                parts.append(f'<tr class="row-green"><td>{pill("Match", "green")}</td><td class="mono">{esc(key)}</td><td colspan="3">Row count &amp; checksum identical</td></tr>')
            for d in data["different"]:
                row_t = "yellow" if d["row_count_match"] else "red"
                chk_t = "green" if d["checksum_match"] else "red"
                chk_l = "Match" if d["checksum_match"] else "Mismatch"
                parts.append(
                    f'<tr class="row-{row_t}"><td>{pill("Different", row_t)}</td>'
                    f'<td class="mono">{esc(d["table"])}</td>'
                    f'<td>{d["source_row_count"]}</td><td>{d["target_row_count"]}</td>'
                    f'<td>{pill(chk_l, chk_t)}</td></tr>'
                )
            parts.append("</tbody></table>")
        elif "tables" in data:
            tables = [t for t in data["tables"] if not t.get("skipped")]
            identical = sum(1 for t in tables if t.get("identical"))
            ds = identical / len(tables) * 100 if tables else 100
            dt_tier, dt_lbl = _tier_from_score(ds)
            parts.append(f'{pill(dt_lbl, dt_tier)}</div><table><thead><tr><th>Status</th><th>Table</th><th>Details</th></tr></thead><tbody>')
            for t in data["tables"]:
                if t.get("skipped"):
                    parts.append(f'<tr><td>{pill("Skipped", "amber")}</td><td class="mono">{esc(t["table"])}</td><td>{esc(t["reason"])}</td></tr>')
                elif t["identical"]:
                    parts.append(f'<tr class="row-green"><td>{pill("Identical", "green")}</td><td class="mono">{esc(t["table"])}</td><td>Deep compare: all rows match</td></tr>')
                else:
                    parts.append(
                        f'<tr class="row-red"><td>{pill("Different", "red")}</td>'
                        f'<td class="mono">{esc(t["table"])}</td>'
                        f'<td>{len(t["only_in_source"])} only source · {len(t["only_in_target"])} only target · {len(t["changed"])} changed</td></tr>'
                    )
            parts.append("</tbody></table>")
        parts.append("  </div>")

    # --- Last write ---
    if report.get("last_write"):
        lw = report["last_write"]
        parts.append(f"""  <div class="section">
    <div class="section-head"><h2>Last Write Estimates</h2></div>
    <table><thead><tr><th>Table</th><th class="th-source">Source</th><th class="th-target">Target</th><th>Status</th></tr></thead><tbody>""")
        for key in sorted(lw["source"].keys()):
            s, t = lw["source"][key], lw["target"][key]
            sv, tv = _format_last_write_value(s), _format_last_write_value(t)
            if sv == tv and sv != "unavailable":
                row_cls, status, st = "row-green", "Same", "green"
            elif sv == "unavailable" or tv == "unavailable":
                row_cls, status, st = "row-yellow", "Unknown", "yellow"
            else:
                row_cls, status, st = "row-yellow", "Differs", "yellow"
            parts.append(
                f'<tr class="{row_cls}"><td class="mono">{esc(key)}</td>'
                f'<td>{esc(sv)}</td><td>{esc(tv)}</td>'
                f'<td>{pill(status, st)}</td></tr>'
            )
        parts.append("</tbody></table></div>")

    parts.append(f"""
  <div class="footer">Read-only compare · No changes were made to either project</div>
</div>
</body>
</html>""")
    return "".join(parts)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def do_list(api: SupabaseManagementAPI, project_ref: str, schemas: list):
    print(f"\n Database inventory for project: {project_ref}\n")
    tables = collect_tables(api, project_ref, schemas)
    print(f"  Tables ({len(tables)}):")
    if not tables:
        print("    (none)")
    else:
        for key in sorted(tables):
            print(f"    {key}")
    print()
    functions = api.list_functions(project_ref)
    print(f"  Edge Functions ({len(functions)}):")
    if not functions:
        print("    (none)")
    else:
        for fn in functions:
            print(f"    {fn['slug']} (v{fn.get('version', '?')}, {fn.get('status', '?')})")
    print()


def do_compare(
    api: SupabaseManagementAPI,
    source_ref: str,
    target_ref: str,
    schemas: list,
    tables_filter: list,
    skip_data: bool,
    skip_edge_functions: bool,
    deep: bool,
    max_rows: int,
    output_path: str,
    fmt: str,
    quiet: bool = False,
    open_browser: bool = True,
):
    progress = Progress(enabled=not quiet)

    print(f"\n Comparing projects")
    print(f"   SOURCE: {source_ref}")
    print(f"   TARGET: {target_ref}\n")

    table_diff = compare_table_schemas(api, source_ref, target_ref, schemas, progress=progress)

    shared_tables = sorted(set(table_diff["identical"]) | {d["table"] for d in table_diff["different"]})
    if tables_filter:
        allowed = set()
        for name in tables_filter:
            if "." in name:
                allowed.add(name)
            else:
                for key in shared_tables:
                    if key.endswith(f".{name}"):
                        allowed.add(key)
        shared_tables = [k for k in shared_tables if k in allowed]

    edge_diff = None
    if not skip_edge_functions:
        edge_diff = compare_edge_functions(api, source_ref, target_ref, progress=progress)

    data_diff = None
    if not skip_data and shared_tables:
        if deep:
            data_diff = compare_table_data_deep(
                api, source_ref, target_ref, shared_tables, max_rows,
                explicit_tables=bool(tables_filter),
                progress=progress,
            )
        else:
            data_diff = compare_table_data_summary(
                api, source_ref, target_ref, shared_tables, progress=progress,
            )

    last_write_keys = sorted(
        set(table_diff["only_in_source"])
        | set(table_diff["only_in_target"])
        | set(table_diff["identical"])
        | {d["table"] for d in table_diff["different"]}
    )
    last_write = {
        "source": collect_last_write_estimates(
            api, source_ref, last_write_keys, progress=progress, label="Source",
        ),
        "target": collect_last_write_estimates(
            api, target_ref, last_write_keys, progress=progress, label="Target",
        ),
    }

    report = {
        "compared_at": datetime.now(timezone.utc).isoformat(),
        "source_ref": source_ref,
        "target_ref": target_ref,
        "schemas": schemas,
        "tables": table_diff,
        "edge_functions": edge_diff,
        "data": data_diff,
        "last_write": last_write,
    }

    saved_html_path = None
    if output_path:
        out = Path(output_path)
        if not out.is_absolute():
            out = _default_report_root() / out
        out.parent.mkdir(parents=True, exist_ok=True)
        if fmt == "html" or str(out).lower().endswith(".html"):
            out.write_text(write_html_report(report), encoding="utf-8")
            saved_html_path = out
        else:
            out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        print(f"\n  Report saved: {out.resolve()}")

    if fmt == "json":
        print(json.dumps(report, indent=2, default=str))
    elif fmt == "html":
        sim = _compute_similarity(report)
        print(f"\n  Overall similarity: {sim['score']:.0f}/100 — {sim['label']}")
        if saved_html_path and open_browser:
            print("  Opening report in browser...")
            _open_in_browser(saved_html_path)
        elif saved_html_path:
            print(f"  Open in browser: {saved_html_path.resolve().as_uri()}")
    else:
        print_text_report(report)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Compare two Supabase projects: tables, Edge Functions, data, and last-write estimates. "
            "100% non-destructive (read-only)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python %(prog)s list --project-ref abcdefghijklmnop --token sbp_xxx

  python %(prog)s compare --source-ref sourceref --target-ref targetref --token sbp_xxx

  python %(prog)s compare --source-ref sourceref --target-ref targetref --tables users orders --deep

  python %(prog)s compare --source-ref sourceref --target-ref targetref --format text

  python %(prog)s compare --source-ref sourceref --target-ref targetref --format json --no-open

This tool is read-only. It never modifies, deletes, or deploys anything on your projects.

Environment variables:
  SUPABASE_ACCESS_TOKEN         Personal access token
  SUPABASE_PROJECT_REF          Project ref (list)
  SUPABASE_SOURCE_PROJECT_REF   Source project ref (compare)
  SUPABASE_TARGET_PROJECT_REF   Target project ref (compare)
""",
    )
    subparsers = parser.add_subparsers(dest="command")

    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument(
        "--token",
        default=os.environ.get("SUPABASE_ACCESS_TOKEN"),
        help="Supabase personal access token (or set SUPABASE_ACCESS_TOKEN).",
    )

    list_parent = argparse.ArgumentParser(add_help=False)
    list_parent.add_argument("--token", default=os.environ.get("SUPABASE_ACCESS_TOKEN"))
    list_parent.add_argument(
        "--project-ref",
        default=os.environ.get("SUPABASE_PROJECT_REF"),
        help="Project reference ID (or set SUPABASE_PROJECT_REF).",
    )

    lp = subparsers.add_parser("list", parents=[list_parent], help="Inventory tables and Edge Functions on one project.")
    lp.add_argument(
        "--schemas",
        nargs="+",
        default=DEFAULT_SCHEMAS,
        help="Schemas to include (default: public).",
    )

    compare_parent = argparse.ArgumentParser(add_help=False)
    compare_parent.add_argument("--token", default=os.environ.get("SUPABASE_ACCESS_TOKEN"))
    compare_parent.add_argument(
        "--source-ref",
        default=os.environ.get("SUPABASE_SOURCE_PROJECT_REF"),
        help="Source project ref (or set SUPABASE_SOURCE_PROJECT_REF).",
    )
    compare_parent.add_argument(
        "--target-ref",
        default=os.environ.get("SUPABASE_TARGET_PROJECT_REF"),
        help="Target project ref (or set SUPABASE_TARGET_PROJECT_REF).",
    )

    cp = subparsers.add_parser(
        "compare",
        parents=[compare_parent],
        help="Compare two projects.",
    )
    cp.add_argument(
        "--schemas",
        nargs="+",
        default=DEFAULT_SCHEMAS,
        help="Schemas to include (default: public).",
    )
    cp.add_argument(
        "--tables",
        nargs="+",
        default=None,
        help="Limit data comparison to these tables (schema.table or bare table name).",
    )
    cp.add_argument("--skip-data", action="store_true", help="Skip table data comparison.")
    cp.add_argument("--skip-edge-functions", action="store_true", help="Skip Edge Function comparison.")
    cp.add_argument("--deep", action="store_true", help="Row-level data diff (use with --tables for large DBs).")
    cp.add_argument("--max-rows", type=int, default=1000, help="Max rows per table in --deep mode (default: 1000).")
    cp.add_argument(
        "--output",
        default=None,
        help="Save report to this path (.json or .html; default path depends on --format).",
    )
    cp.add_argument(
        "--format",
        choices=["text", "json", "html"],
        default="html",
        help="Output format: html report (default), text summary, or json.",
    )
    cp.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress progress bar (print step labels only when not a TTY).",
    )
    cp.add_argument(
        "--no-open",
        action="store_true",
        help="Do not open the HTML report in the browser when complete.",
    )

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    if not args.token:
        print("ERROR: Access token is required.")
        print("  Use --token <your_token> or set SUPABASE_ACCESS_TOKEN.")
        print("  Get a token at: https://supabase.com/dashboard/account/tokens")
        sys.exit(1)

    api = SupabaseManagementAPI(args.token)

    if args.command == "list":
        if not args.project_ref:
            print("ERROR: Project reference is required.")
            print("  Use --project-ref <ref> or set SUPABASE_PROJECT_REF.")
            sys.exit(1)
        do_list(api, args.project_ref, args.schemas)

    elif args.command == "compare":
        if not args.source_ref or not args.target_ref:
            print("ERROR: Both --source-ref and --target-ref are required.")
            print("  Or set SUPABASE_SOURCE_PROJECT_REF and SUPABASE_TARGET_PROJECT_REF.")
            sys.exit(1)
        output = args.output
        if output is None and args.format in ("text", "html", "json"):
            ext = ".html" if args.format == "html" else ".json"
            output = _default_output_path(args.source_ref, args.target_ref, ext)
        do_compare(
            api,
            args.source_ref,
            args.target_ref,
            args.schemas,
            args.tables,
            args.skip_data,
            args.skip_edge_functions,
            args.deep,
            args.max_rows,
            output,
            args.format,
            args.quiet,
            open_browser=not args.no_open,
        )


if __name__ == "__main__":
    main()
