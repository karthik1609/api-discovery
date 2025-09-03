
import os
import sys
import json
import time
import argparse
from urllib.parse import urljoin
import requests
from dotenv import load_dotenv

load_dotenv()

BASE_URL = os.getenv("API_DISCOVERY_SERVICENOW_BASE_URL", "").rstrip("/") + "/"
USER = os.getenv("API_DISCOVERY_SERVICENOW_USERNAME")
PASS = os.getenv("API_DISCOVERY_SERVICENOW_PASSWORD")

SESSION = requests.Session()
SESSION.auth = (USER, PASS)
SESSION.headers.update({
    "Accept": "application/json"
})
# If your instance uses self-signed certs, you could disable verify (not recommended):
# SESSION.verify = False

LIMIT = 10000  # large page size supported by SN Table API

def die(msg, code=1):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)

def check_env():
    missing = [k for k in ["API_DISCOVERY_SERVICENOW_BASE_URL",
                           "API_DISCOVERY_SERVICENOW_USERNAME",
                           "API_DISCOVERY_SERVICENOW_PASSWORD"]
               if not os.getenv(k)]
    if missing:
        die(f"Missing env var(s): {', '.join(missing)}")

def table_url(table: str) -> str:
    return urljoin(BASE_URL, f"api/now/table/{table}")

def fetch_all(table: str, fields: str, query: str = "", display_value: str = "false", exclude_ref_link: bool = True):
    """
    Generic paginator for SN Table API.
    Returns list of dict rows.
    """
    rows = []
    offset = 0
    while True:
        params = {
            "sysparm_fields": fields,
            "sysparm_limit": str(LIMIT),
            "sysparm_offset": str(offset),
            "sysparm_display_value": display_value,
        }
        if exclude_ref_link:
            params["sysparm_exclude_reference_link"] = "true"
        if query:
            params["sysparm_query"] = query

        resp = SESSION.get(table_url(table), params=params, timeout=60)
        if resp.status_code != 200:
            try:
                detail = resp.json()
            except Exception:
                detail = resp.text
            die(f"GET {table}: HTTP {resp.status_code} – {detail}")

        data = resp.json().get("result", [])
        rows.extend(data)
        # If fewer than LIMIT, we're done
        if len(data) < LIMIT:
            break
        offset += LIMIT
        # polite pacing for giant instances
        time.sleep(0.2)
    return rows

def probe_exists(path: str) -> bool:
    try:
        r = SESSION.options(urljoin(BASE_URL, path), timeout=15)
        return r.status_code not in (404, 410)
    except Exception:
        return False

def main():
    check_env()
    parser = argparse.ArgumentParser()
    parser.add_argument("--include-inactive", action="store_true",
                        help="include inactive API definitions")
    parser.add_argument("--out", default="apis_by_namespace.json",
                        help="output JSON path (default: apis_by_namespace.json)")
    args = parser.parse_args()

    # 1) Pull all Scripted REST API definitions
    def_query = "" if args.include_inactive else "active=true"
    def_fields = ",".join([
        "sys_id", "name", "version", "api_id", "base_path",
        "sys_scope", "active", "consumes", "produces"
    ])
    definitions = fetch_all("sys_ws_definition", def_fields, def_query)

    if not definitions:
        print("No Scripted REST API definitions found.")
        with open(args.out, "w") as f:
            json.dump({}, f, indent=2)
        return

    # 2) Pull all versions and operations (we'll join by version)
    ver_fields = ",".join(["sys_id", "web_service", "version", "active", "in_url"]) 
    versions_rows = fetch_all("sys_ws_version", ver_fields, "")
    vers_by_def = {}
    for v in versions_rows:
        def_id = str(v.get("web_service") or "")
        if not def_id:
            continue
        vers_by_def.setdefault(def_id, []).append({
            "sys_id": str(v.get("sys_id")),
            "version": v.get("version") or "",
            "active": str(v.get("active")).lower() in ("true", "1"),
            "in_url": v.get("in_url") or "",
        })

    # 3) Pull operations
    op_fields = ",".join([
        "sys_id", "name", "http_method", "relative_path", "path",
        "web_service", "web_service_version", "requires_authentication", "produces", "consumes"
    ])
    operations = fetch_all("sys_ws_operation", op_fields, "")

    # 3) Resolve namespaces (technical scope) for the sys_scope ids present
    scope_ids = sorted({str(d.get("sys_scope")) for d in definitions if d.get("sys_scope")})
    scope_ids = [s for s in scope_ids if s]
    scope_map = {}  # sys_id -> {"scope":"x_yourco_app","name":"Your App"}
    if scope_ids:
        # SN Table API lacks direct "IN" with huge lists; chunk if necessary
        chunk = 100
        for i in range(0, len(scope_ids), chunk):
            sub = scope_ids[i:i+chunk]
            # sys_idINa,b,c
            q = "sys_idIN" + ",".join(sub)
            sc_fields = "sys_id,scope,name"
            for row in fetch_all("sys_scope", sc_fields, q, display_value="false"):
                scope_map[row["sys_id"]] = {
                    "scope": row.get("scope") or "global",
                    "name": row.get("name") or "Global"
                }

    # 4) Index operations by definition sys_id
    ops_by_def = {}
    ops_by_ver = {}
    for op in operations:
        def_id = str(op.get("web_service") or "")
        ver_id = str(op.get("web_service_version") or "")
        op_row = {
            "operation_sys_id": op.get("sys_id"),
            "operation_name": op.get("name"),
            "http_method": op.get("http_method"),
            "relative_path": op.get("relative_path") or op.get("path") or "",
            "requires_authentication": str(op.get("requires_authentication")).lower() in ("true", "1"),
            "produces": op.get("produces") or "",
            "consumes": op.get("consumes") or "",
        }
        if ver_id:
            ops_by_ver.setdefault(ver_id, []).append(op_row)
        elif def_id:
            ops_by_def.setdefault(def_id, []).append(op_row)

    # 5) Build namespace -> apis -> versions -> operations
    inventory = {}
    for d in definitions:
        # sysparm_display_value=false returns a plain sys_id string for reference fields
        scope_id = str(d.get("sys_scope") or "")
        scope_info = scope_map.get(scope_id, {"scope": "global", "name": "Global"})
        ns_key = scope_info["scope"]

        inv_ns = inventory.setdefault(ns_key, {
            "namespace": ns_key,
            "namespace_display": scope_info["name"],
            "apis": {}
        })

        api_sys_id = str(d.get("sys_id"))
        api_name = d.get("name") or ""
        api_id = d.get("api_id") or ""
        base_path = d.get("base_path") or ""
        # Active flag from definition
        active = str(d.get("active")).lower() in ("true", "1")
        # Prefer explicit version rows; fallback to definition.version
        definition_versions = vers_by_def.get(api_sys_id, [])
        if not definition_versions:
            definition_versions = [{
                "sys_id": "",
                "version": d.get("version") or "v1",
                "active": active,
                "in_url": d.get("base_path") or "",
            }]

        api_entry = inv_ns["apis"].setdefault(api_sys_id, {
            "api_sys_id": api_sys_id,
            "api_name": api_name,
            "api_id": api_id,
            "base_path": base_path,
            "versions": {}
        })

        for v in definition_versions:
            v_id = v.get("sys_id")
            v_name = v.get("version") or "v1"
            ver_entry = api_entry["versions"].setdefault(v_name, {
                "definition_sys_id": api_sys_id,
                "version": v_name,
                "consumes": d.get("consumes") or "",
                "produces": d.get("produces") or "",
                "active": v.get("active", active),
                "operations": []
            })
            if v_id and v_id in ops_by_ver:
                ver_entry["operations"].extend(ops_by_ver[v_id])
            else:
                ver_entry["operations"].extend(ops_by_def.get(api_sys_id, []))

    # 6) Sort operations by name/method for determinism
    for ns in inventory.values():
        for api in ns["apis"].values():
            for ver in api["versions"].values():
                ver["operations"].sort(key=lambda x: (x["operation_name"] or "", x["http_method"] or "", x["relative_path"] or ""))

    # 7) Programmatically detect core Now APIs (no hardcoding into catalog without probe)
    ns_now = inventory.setdefault("now", {"namespace": "now", "namespace_display": "Now Platform", "apis": {}})
    core_checks = {
        "Table API": "/api/now/table/sys_user",
        "Attachment API": "/api/now/attachment",
        "Aggregate API": "/api/now/aggregate/sys_user",
        "Import Set API": "/api/now/import",
    }
    for api_name, path in core_checks.items():
        if probe_exists(path):
            entry = ns_now["apis"].setdefault(api_name, {
                "api_sys_id": api_name,
                "api_name": api_name,
                "api_id": "",
                "base_path": "",
                "versions": {"v1": {"definition_sys_id": api_name, "version": "v1", "consumes": "", "produces": "", "active": True, "operations": []}}
            })

    # 8) Write output
    with open(args.out, "w") as f:
        json.dump(inventory, f, indent=2)
    print(f"Wrote {args.out}")
    # Optional: print quick summary
    total_apis = sum(len(ns["apis"]) for ns in inventory.values())
    total_ops = sum(len(ver["operations"]) for ns in inventory.values()
                    for api in ns["apis"].values()
                    for ver in api["versions"].values())
    print(f"Namespaces: {len(inventory)} | APIs: {total_apis} | Operations: {total_ops}")

if __name__ == "__main__":
    main()
