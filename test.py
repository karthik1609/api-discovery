
import os
import re
import hashlib
from pathlib import Path
import sys
import json
import time
import argparse
import sys as _sys
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

def ref(v):
    return v.get("value") if isinstance(v, dict) else (v or "")

def _get(url, params, timeout=60, retries=2):
    last = None
    for i in range(retries + 1):
        resp = SESSION.get(url, params=params, timeout=timeout)
        if resp.status_code not in (429, 502, 503, 504):
            return resp
        time.sleep(0.4 * (i + 1))
        last = resp
    return last if last is not None else resp

def fetch_all(table: str, fields: str, query: str = "", display_value: str = "false", exclude_ref_link: bool = True, strict: bool = False):
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

        resp = _get(table_url(table), params=params, timeout=60)
        if resp.status_code != 200:
            try:
                detail = resp.json()
            except Exception:
                detail = resp.text
            if strict:
                die(f"GET {table}: HTTP {resp.status_code} – {detail}")
            else:
                print(f"WARN: GET {table} returned {resp.status_code}; treating as EMPTY", file=_sys.stderr)
                return []

        data = resp.json().get("result", [])
        rows.extend(data)
        # If fewer than LIMIT, we're done
        if len(data) < LIMIT:
            break
        offset += LIMIT
        # polite pacing for giant instances
        time.sleep(0.2)
    return rows

PRESENT_STATUSES = {200, 204, 401, 403, 405}

def _probe(path: str) -> dict:
    result = {"path": path, "present": False, "method": None, "status": None}
    try:
        r = SESSION.options(urljoin(BASE_URL, path), timeout=15)
        result.update({"method": "OPTIONS", "status": r.status_code})
        if r.status_code in PRESENT_STATUSES:
            result["present"] = True
            return result
    except Exception:
        pass
    try:
        r = SESSION.head(urljoin(BASE_URL, path), timeout=15)
        result.update({"method": "HEAD", "status": r.status_code})
        if r.status_code in PRESENT_STATUSES:
            result["present"] = True
            return result
    except Exception:
        pass
    try:
        r = SESSION.get(urljoin(BASE_URL, path), params={"sysparm_limit": "1"}, timeout=15)
        result.update({"method": "GET", "status": r.status_code})
        if r.status_code in PRESENT_STATUSES:
            result["present"] = True
    except Exception:
        pass
    return result

# ---------------- Platform docs scraping (pure discovery) ----------------
DOC_ROOTS = [
    "https://www.servicenow.com/docs/bundle/{bundle}/page/",
]

def _http_get(url, timeout=25, retries=2):
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    })
    last = None
    for i in range(retries + 1):
        try:
            r = s.get(url, timeout=timeout)
            # Return on anything but 429 or 5xx (allow 3xx redirects)
            if (r.status_code < 500 and r.status_code != 429):
                return r
        except Exception:
            pass
        time.sleep(0.35 * (i + 1))
        last = r if 'r' in locals() else None
    return last

_API_NOW_RE = re.compile(r"""(/api/now(?:/v\d+)?(?:/[A-Za-z0-9_-]+)+(?:/\{?[A-Za-z0-9_]+\}?){0,2})""")

def _extract_now_paths(html: str) -> set[str]:
    return set(m.group(1) for m in _API_NOW_RE.finditer(html or ""))

def _cache_path_for(url: str, cache_dir: Path) -> Path:
    h = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    return cache_dir / f"doc_{h}.html"

async def _render_with_playwright(url: str, timeout_ms: int = 25000) -> str:
    try:
        from playwright.async_api import async_playwright
    except Exception:
        return ""
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context()
            page = await context.new_page()
            await page.goto(url, wait_until="networkidle", timeout=timeout_ms)
            content = await page.content()
            await browser.close()
            return content or ""
    except Exception:
        return ""

def _resolve_docs_targets(bundle: str) -> list[str]:
    targets = set()
    # 1) REST API index
    for base in DOC_ROOTS:
        b = base.format(bundle=bundle)
        targets.add(b + "build/applications/concept/api-rest.html")
        # 2) Inbound REST concept roots (vary by release)
        guesses = [
            "integrate/inbound-rest/concept/c_RESTAPI.html",
            "integrate/inbound-rest/concept/",
            # Common family concept pages across releases (scrape for /api/now/*; not enumerating families in code)
            "integrate/inbound-rest/concept/c_TableAPI.html",
            "integrate/inbound-rest/concept/c_AttachmentAPI.html",
            "integrate/inbound-rest/concept/c_ImportSetAPI.html",
            "integrate/inbound-rest/concept/c_AggregateAPI.html",
            "integrate/inbound-rest/concept/c_StatsAPI.html",
            "integrate/inbound-rest/concept/c_BatchAPI.html",
            # Developer guides hub (user-provided working URL family)
            "integrate/guides/concept/developer-guides.html",
        ]
        for g in guesses:
            targets.add(b + g)
        # 3) GraphQL concept
        targets.add(b + "integrate/graphql/concept/scripted-graph-ql.html")
    return list(targets)

def discover_platform_apis_from_docs(bundle: str, timeout: int = 25) -> dict:
    try:
        pages = _resolve_docs_targets(bundle)
        if not pages:
            raise RuntimeError("No documentation targets resolved")
        discovered: dict[str, dict] = {}
        seen = set()
        for url in pages:
            try:
                r = _http_get(url, timeout=timeout)
            except Exception as e:
                continue
            if not r or r.status_code != 200 or not r.text:
                continue
            paths = _extract_now_paths(r.text)
            # If suspected JS-rendered page (no matches), mark for fallback
            if not paths:
                discovered.setdefault(url, {"patterns": set(), "source": url, "js_render_needed": True})
                continue
            for p in paths:
                if p.count("/") < 3:
                    continue
                p_norm = p.replace("&amp;", "&")
                key = f"{url}::{p_norm}"
                if key in seen:
                    continue
                seen.add(key)
                discovered.setdefault(url, {"patterns": set(), "source": url})
                discovered[url]["patterns"].add(p_norm)
        for k in list(discovered.keys()):
            discovered[k]["patterns"] = sorted(discovered[k]["patterns"])
        return discovered
    except Exception as e:
        raise RuntimeError(f"Platform docs discovery failed: {e}")

def _family_label_from_url(url: str) -> str:
    m = re.search(r"/concept/([a-zA-Z0-9_-]+)\.html", url)
    if m:
        raw = m.group(1)
        name = re.sub(r"[_-]+", " ", raw)
        name = re.sub(r"(?<=.)([A-Z])", r" \1", name).strip()
        return name.replace("Api", "API")
    if "/graphql/" in url:
        return "GraphQL"
    return url

def _strip_placeholder(p: str) -> str:
    return re.sub(r"/\{[^/]+\}$", "", p)

def _probe_platform_family(patterns: list[str]) -> dict:
    candidates = set()
    for p in patterns:
        base = _strip_placeholder(p)
        candidates.add(base)
        if "{" in p and "}" in p:
            # Replace any placeholders with a safe table token
            filled = re.sub(r"\{[^}]+\}", "sys_user", p)
            candidates.add(filled)
    results = []
    for c in candidates:
        r = _probe(c)
        results.append(r)
        if r.get("present"):
            return {"present": True, "probe": r, "checked": list(candidates)}
    return {"present": False, "probe": results[-1] if results else None, "checked": list(candidates)}

def main():
    check_env()
    parser = argparse.ArgumentParser()
    parser.add_argument("--include-inactive", action="store_true",
                        help="include inactive API definitions")
    parser.add_argument("--out", default="apis_by_namespace.json",
                        help="output JSON path (default: apis_by_namespace.json)")
    parser.add_argument("--include-ops", action="store_true",
                        help="include operations per API/version from sys_ws_operation")
    parser.add_argument("--include-empty-scopes", action="store_true",
                        help="emit all active scopes even if they have zero APIs")
    parser.add_argument("--enumerate-core", action="store_true",
                        help="enumerate core Now endpoints (table/attachment/aggregate/import/graphql) into a separate section")
    parser.add_argument("--discover-platform", action="store_true",
                        help="scrape official docs to derive platform REST families, probe instance, and merge confirmed APIs")
    parser.add_argument("--docs-release", default="washingtondc-api-reference",
                        help="ServiceNow docs bundle to scrape (e.g., 'zurich-api-reference', 'washingtondc-api-reference', 'yokohama-api-reference')")
    parser.add_argument("--docs-timeout", type=int, default=25,
                        help="timeout for docs HTTP fetch (seconds)")
    parser.add_argument("--platform-debug", action="store_true",
                        help="print discovery details for platform families")
    parser.add_argument("--render-js", action="store_true",
                        help="render docs pages with Playwright when static HTML is empty")
    parser.add_argument("--strict-acl", action="store_true",
                        help="fail hard on ACL errors when reading sys_* tables")
    parser.add_argument("--core-strict", action="store_true",
                        help="fail with exit code 2 if core Now endpoints are missing")
    parser.add_argument("--no-core-probe", action="store_true",
                        help="skip probing core Now endpoints entirely")
    parser.add_argument("--core-report", default="core_probe_report.json",
                        help="write probe results to this JSON sidecar (default: core_probe_report.json)")
    args = parser.parse_args()

    # 1) Pull all Scripted REST API definitions
    def_query = "" if args.include_inactive else "active=true"
    def_fields = ",".join([
        "sys_id", "name", "version", "api_id", "base_path",
        "sys_scope", "active", "consumes", "produces"
    ])
    definitions = fetch_all("sys_ws_definition", def_fields, def_query, strict=args.strict_acl)

    if not definitions:
        print("No Scripted REST API definitions found.")
        with open(args.out, "w") as f:
            json.dump({}, f, indent=2)
        return

    # 2) We will fetch versions per API definition on demand (no global join)

    # 3) Resolve namespaces (technical scope) for the sys_scope ids present
    scope_ids = sorted({ref(d.get("sys_scope")) for d in definitions if d.get("sys_scope")})
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
            for row in fetch_all("sys_scope", sc_fields, q, display_value="false", strict=args.strict_acl):
                scope_map[row["sys_id"]] = {
                    "scope": row.get("scope") or "global",
                    "name": row.get("name") or "Global"
                }

    # Optionally include empty scopes (all active scopes)
    if args.include_empty_scopes:
        for row in fetch_all("sys_scope", "sys_id,scope,name,active", "active=true", display_value="false", strict=args.strict_acl):
            if row.get("scope"):
                scope_map.setdefault(row["sys_id"], {
                    "scope": row.get("scope") or "global",
                    "name": row.get("name") or "Global"
                })

    # Seed inventory with all scopes (even if empty)
    inventory = {}
    for sc_id, sc in scope_map.items():
        ns_key = sc.get("scope") or "global"
        inventory.setdefault(ns_key, {
            "namespace": ns_key,
            "namespace_display": sc.get("name") or "Global",
            "apis": {}
        })

    # 3) We skip operations for the initial catalog listing

    # 5) Build namespace -> apis -> versions -> operations
    for d in definitions:
        # sysparm_display_value=false returns a plain sys_id string for reference fields
        scope_id = ref(d.get("sys_scope"))
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
        # Query versions directly for this definition to avoid joining on ACL-filtered fields
        ver_fields = ",".join(["sys_id", "version", "active", "in_url"]) 
        ver_query = f"web_service={api_sys_id}"
        definition_versions = fetch_all("sys_ws_version", ver_fields, ver_query, strict=False)
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
                "active": v.get("active", active)
            })
            # Operations intentionally omitted in list phase

    # Optionally include operations per version
    if args.include_ops:
        op_fields = ",".join([
            "sys_id", "name", "http_method", "relative_path", "path",
            "web_service", "web_service_version", "requires_authentication", "produces", "consumes"
        ])
        # Fetch all ops in one go (may be large but simplest)
        ops = fetch_all("sys_ws_operation", op_fields, strict=args.strict_acl)
        # Index
        ops_by_ver = {}
        ops_by_def = {}
        for op in ops:
            def_id = ref(op.get("web_service"))
            ver_id = ref(op.get("web_service_version"))
            rec = {
                "operation_sys_id": op.get("sys_id"),
                "operation_name": op.get("name"),
                "http_method": op.get("http_method"),
                "relative_path": op.get("relative_path") or op.get("path") or "",
                "requires_authentication": str(op.get("requires_authentication")).lower() in ("true", "1"),
                "produces": op.get("produces") or "",
                "consumes": op.get("consumes") or "",
            }
            if ver_id:
                ops_by_ver.setdefault(ver_id, []).append(rec)
            elif def_id:
                ops_by_def.setdefault(def_id, []).append(rec)

        # Build version map once to avoid N+1
        ver_map_by_api = {}
        for ns in inventory.values():
            for api in ns["apis"].values():
                api_def_id = api["api_sys_id"]
                v_rows = fetch_all("sys_ws_version", "sys_id,version", f"web_service={api_def_id}", strict=False)
                ver_map_by_api[api_def_id] = { (r.get("version") or "v1"): r.get("sys_id") for r in v_rows }

        # Attach into inventory
        for ns in inventory.values():
            for api in ns["apis"].values():
                api_def_id = api["api_sys_id"]
                for ver_name, ver in api["versions"].items():
                    ver_id = (ver_map_by_api.get(api_def_id) or {}).get(ver_name, "")
                    attached = False
                    if ver_id and ver_id in ops_by_ver:
                        ver["operations"] = sorted(ops_by_ver[ver_id], key=lambda x: (x["operation_name"] or "", x["http_method"] or "", x["relative_path"] or ""))
                        attached = True
                    elif api_def_id in ops_by_def:
                        ver["operations"] = sorted(ops_by_def[api_def_id], key=lambda x: (x["operation_name"] or "", x["http_method"] or "", x["relative_path"] or ""))
                        attached = True
                    if not attached:
                        ver["operations"] = []

    # 6) No operations to sort in list-only mode

    # --- Discover & merge platform families (no hardcoding) ---
    if args.discover_platform:
        docs = discover_platform_apis_from_docs(args.docs_release, timeout=args.docs_timeout)
        if args.platform_debug:
            total_patterns = sum(len(info.get("patterns", [])) for info in docs.values())
            print(f"Platform docs: pages={len(docs)} patterns={total_patterns}", file=_sys.stderr)
        # JS-render fallback on pages that flagged js_render_needed
        if args.render_js:
            cache_dir = Path(".state/platform_docs_cache")
            cache_dir.mkdir(parents=True, exist_ok=True)
            import asyncio
            for url, info in list(docs.items()):
                if not info.get("patterns") and info.get("js_render_needed"):
                    cache_file = _cache_path_for(url, cache_dir)
                    html = ""
                    if cache_file.exists():
                        try:
                            html = cache_file.read_text(encoding="utf-8", errors="ignore")
                        except Exception:
                            html = ""
                    if not html:
                        html = asyncio.run(_render_with_playwright(url, timeout_ms=args.docs_timeout * 1000))
                        if html:
                            try:
                                cache_file.write_text(html, encoding="utf-8")
                            except Exception:
                                pass
                    if html:
                        paths = _extract_now_paths(html)
                        if paths:
                            docs[url]["patterns"] = sorted(paths)
                            docs[url].pop("js_render_needed", None)
        now_ns = inventory.setdefault("now", {"namespace": "now", "namespace_display": "Now Platform", "apis": {}})
        for url, info in docs.items():
            fam_name = _family_label_from_url(url)
            patterns = info.get("patterns", [])
            if not patterns:
                continue
            probe_res = _probe_platform_family(patterns)
            if not probe_res.get("present"):
                if args.platform_debug:
                    print(f"DROP family={fam_name} patterns={len(patterns)} present=False", file=_sys.stderr)
                continue
            if args.platform_debug:
                pr = probe_res.get("probe", {})
                print(f"KEEP family={fam_name} via {pr.get('method')} {pr.get('status')}", file=_sys.stderr)

            api_id = f"platform::{fam_name}"
            api_entry = {
                "api_sys_id": api_id,
                "api_name": fam_name,
                "api_id": "",
                "base_path": "",
                "versions": {
                    "v1": {
                        "definition_sys_id": api_id,
                        "version": "v1",
                        "consumes": "",
                        "produces": "",
                        "active": True,
                        "operations": [],
                        "doc_source": url,
                        "patterns": patterns
                    }
                }
            }
            now_ns["apis"][api_id] = api_entry

    # Optionally enumerate core endpoints (non-mutating, separate section)
    core_inventory = {}
    if args.enumerate_core:
        core_inventory = {
            "table": "/api/now/table/{table}",
            "attachment": "/api/now/attachment",
            "aggregate": "/api/now/aggregate/{table}",
            "import_set": "/api/now/import/{table}",
            "graphql": "/api/now/graphql",
        }

    # 7) Write main output (authoritative sys_ws_* only)
    # Deterministic ordering for CI-friendly diffs
    for ns_key, ns in list(inventory.items()):
        ns["apis"] = dict(sorted(ns["apis"].items(), key=lambda kv: ((kv[1]["api_name"] or ""), kv[0])))
        for api in ns["apis"].values():
            api["versions"] = dict(sorted(api["versions"].items(), key=lambda kv: kv[0]))
            for ver in api["versions"].values():
                if "operations" in ver and ver["operations"]:
                    ver["operations"].sort(key=lambda x: ((x["operation_name"] or ""), (x["http_method"] or ""), (x["relative_path"] or "")))
    inventory = dict(sorted(inventory.items(), key=lambda kv: kv[0]))

    with open(args.out, "w") as f:
        json.dump({
            "namespaces": inventory,
            "core_endpoints": core_inventory
        }, f, indent=2)
    print(f"Wrote {args.out}")

    # 8) Probe core Now endpoints without mutating inventory (optional)
    if not args.no_core_probe:
        checks = {
            "Table API": "/api/now/table/sys_user",
            "Attachment API": "/api/now/attachment",
            "Aggregate API": "/api/now/aggregate/sys_user",
            "Import Set API": "/api/now/import",
            "GraphQL": "/api/now/graphql",
        }
        results = {name: _probe(path) for name, path in checks.items()}
        with open(args.core_report, "w") as rf:
            json.dump(results, rf, indent=2)
        missing = [k for k, v in results.items() if not v.get("present")]
        if missing:
            print(f"WARNING: core Now endpoints missing or unreachable: {', '.join(missing)}", file=_sys.stderr)
            if args.core_strict:
                _sys.exit(2)
    # removed duplicate print
    # Optional: print quick summary
    total_apis = sum(len(ns["apis"]) for ns in inventory.values())
    total_versions = sum(len(api["versions"]) for ns in inventory.values()
                         for api in ns["apis"].values())
    print(f"Namespaces: {len(inventory)} | APIs: {total_apis} | Versions: {total_versions}")

if __name__ == "__main__":
    main()
