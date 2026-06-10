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


def compare_table_schemas(api: SupabaseManagementAPI, source_ref: str, target_ref: str, schemas: list) -> dict:
    source_tables = collect_tables(api, source_ref, schemas)
    target_tables = collect_tables(api, target_ref, schemas)
    source_keys = set(source_tables)
    target_keys = set(target_tables)
    only_source = sorted(source_keys - target_keys)
    only_target = sorted(target_keys - source_keys)
    shared = sorted(source_keys & target_keys)
    identical = []
    different = []
    for key in shared:
        schema, table = _parse_table_key(key)
        src_cols = collect_columns(api, source_ref, schema, table)
        tgt_cols = collect_columns(api, target_ref, schema, table)
        col_diff = diff_columns(src_cols, tgt_cols)
        entry = {"table": key, "column_diff": col_diff}
        if col_diff["identical"]:
            identical.append(key)
        else:
            different.append(entry)
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


def collect_edge_functions(api: SupabaseManagementAPI, project_ref: str, include_hashes: bool = True) -> dict:
    functions = api.list_functions(project_ref)
    result = {}
    for fn in functions:
        slug = fn["slug"]
        meta = api.get_function_meta(project_ref, slug)
        entry = {
            "slug": slug,
            "list_meta": fn,
            "meta": _function_meta_subset(meta),
            "source_hash": None,
        }
        if include_hashes:
            source_files = api.get_function_source_files(project_ref, slug)
            entry["source_hash"] = _function_source_hash(source_files)
        result[slug] = entry
    return result


def compare_edge_functions(api: SupabaseManagementAPI, source_ref: str, target_ref: str) -> dict:
    print("  Collecting Edge Functions from source...")
    source_fns = collect_edge_functions(api, source_ref)
    print("  Collecting Edge Functions from target...")
    target_fns = collect_edge_functions(api, target_ref)
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


def compare_table_data_summary(api: SupabaseManagementAPI, source_ref: str, target_ref: str,
                               table_keys: list) -> dict:
    matching = []
    different = []
    for key in table_keys:
        schema, table = _parse_table_key(key)
        pk_cols = collect_primary_key_columns(api, source_ref, schema, table)
        src_count = get_row_count(api, source_ref, schema, table)
        tgt_count = get_row_count(api, target_ref, schema, table)
        src_checksum = get_table_checksum(api, source_ref, schema, table, pk_cols)
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
    return {"matching": matching, "different": different}


def compare_table_data_deep(api: SupabaseManagementAPI, source_ref: str, target_ref: str,
                            table_keys: list, max_rows: int, explicit_tables: bool) -> dict:
    results = []
    for key in table_keys:
        schema, table = _parse_table_key(key)
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


def collect_last_write_estimates(api: SupabaseManagementAPI, project_ref: str, table_keys: list) -> dict:
    estimates = {}
    for key in table_keys:
        schema, table = _parse_table_key(key)
        estimates[key] = estimate_last_write(api, project_ref, schema, table)
    return estimates


# ---------------------------------------------------------------------------
# Report output
# ---------------------------------------------------------------------------

def _default_output_path(source_ref: str, target_ref: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    name = f"compare_{source_ref}_vs_{target_ref}_{ts}.json"
    return str(_default_report_root() / name)


def print_text_report(report: dict):
    print(f"\n Comparing databases")
    print(f"   Source: {report['source_ref']}")
    print(f"   Target: {report['target_ref']}")
    print(f"   Compared at: {report['compared_at']}\n")

    ts = report["tables"]
    print(" Tables")
    print(f"   Only in source: {len(ts['only_in_source'])}")
    if ts["only_in_source"]:
        print(f"     {', '.join(ts['only_in_source'])}")
    print(f"   Only in target: {len(ts['only_in_target'])}")
    if ts["only_in_target"]:
        print(f"     {', '.join(ts['only_in_target'])}")
    print(f"   Identical:      {len(ts['identical'])}")
    diff_names = [d["table"] for d in ts["different"]]
    print(f"   Different:      {len(ts['different'])}")
    if diff_names:
        print(f"     {', '.join(diff_names)}")
    print()

    if report.get("edge_functions") is not None:
        ef = report["edge_functions"]
        print(" Edge Functions")
        print(f"   Only in source: {len(ef['only_in_source'])}")
        if ef["only_in_source"]:
            print(f"     {', '.join(ef['only_in_source'])}")
        print(f"   Only in target: {len(ef['only_in_target'])}")
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
                    f"{d['source_row_count']} vs {d['target_row_count']} rows, "
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
            s_val = s.get("last_write_estimate") or s.get("method", "?")
            t_val = t.get("last_write_estimate") or t.get("method", "?")
            print(f"   {key}")
            print(f"     source: {s_val} ({s.get('method', '?')})")
            print(f"     target: {t_val} ({t.get('method', '?')})")
        print()


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
):
    print(f"\n Comparing projects")
    print(f"   Source: {source_ref}")
    print(f"   Target: {target_ref}\n")

    print("  Comparing table schemas...")
    table_diff = compare_table_schemas(api, source_ref, target_ref, schemas)

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
        print("  Comparing Edge Functions...")
        edge_diff = compare_edge_functions(api, source_ref, target_ref)

    data_diff = None
    if not skip_data and shared_tables:
        if deep:
            print(f"  Comparing table data (deep, max {max_rows} rows per table)...")
            data_diff = compare_table_data_deep(
                api, source_ref, target_ref, shared_tables, max_rows,
                explicit_tables=bool(tables_filter),
            )
        else:
            print("  Comparing table data (summary: row counts + checksums)...")
            data_diff = compare_table_data_summary(api, source_ref, target_ref, shared_tables)

    print("  Estimating last-write times...")
    last_write_keys = sorted(
        set(table_diff["only_in_source"])
        | set(table_diff["only_in_target"])
        | set(table_diff["identical"])
        | {d["table"] for d in table_diff["different"]}
    )
    last_write = {
        "source": collect_last_write_estimates(api, source_ref, last_write_keys),
        "target": collect_last_write_estimates(api, target_ref, last_write_keys),
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

    if output_path:
        out = Path(output_path)
        if not out.is_absolute():
            out = _default_report_root() / out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, default=str))
        print(f"\n  Report saved: {out.resolve()}")

    if fmt == "json":
        print(json.dumps(report, indent=2, default=str))
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

  python %(prog)s compare --source-ref sourceref --target-ref targetref --skip-data --format json

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
        help="Save JSON report to this path (default: ~/Documents/SupabaseTools/compare_<source>_vs_<target>_<ts>.json).",
    )
    cp.add_argument("--format", choices=["text", "json"], default="text", help="Output format (default: text).")

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
        if output is None and args.format == "text":
            output = _default_output_path(args.source_ref, args.target_ref)
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
        )


if __name__ == "__main__":
    main()
