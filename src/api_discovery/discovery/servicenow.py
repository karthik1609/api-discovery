from __future__ import annotations

from typing import Dict, Iterable, List, Tuple
import re
from bs4 import BeautifulSoup

from ..config import ServiceNowSettings, RunConfig
from ..http import HTTPClient, AuthConfig
from ..state import StateStore, Evidence


def _sn_auth(settings: ServiceNowSettings) -> AuthConfig:
    if settings.username and settings.password:
        return AuthConfig(username=settings.username, password=settings.password)
    if settings.oauth_token:
        return AuthConfig(bearer_token=settings.oauth_token)
    return AuthConfig()


def enumerate_tables(client: HTTPClient) -> List[Dict[str, str]]:
    # sys_db_object contains table metadata
    resp = client.get("/api/now/table/sys_db_object", params={"sysparm_fields": "name,label,super_class"})
    data = resp.json()
    return data.get("result", [])


def _fetch_explorer_html(client: HTTPClient) -> str:
    candidates = [
        "/sn_rpexplorer.do",
        "/rest_api_explorer.do",
        "/now/nav/ui/classic/params/target/rest_api_explorer.do",
    ]
    for path in candidates:
        try:
            resp = client.get(path)
            if resp.status_code == 200 and "<html" in resp.text.lower():
                return resp.text
        except Exception:  # noqa: BLE001
            continue
    return ""


def _extract_select_options(html: str, label_keywords: List[str]) -> List[str]:
    if not html:
        return []
    soup = BeautifulSoup(html, "lxml")
    # Try label-associated select
    for lab in soup.find_all("label"):
        text = (lab.get_text(strip=True) or "").lower()
        if any(k in text for k in label_keywords):
            sel = lab.find_next("select")
            if sel:
                vals = [opt.get_text(strip=True) for opt in sel.find_all("option") if (opt.get("value") or opt.get_text(strip=True))]
                return [v for v in vals if v]
    # Try selects with id/name contains keyword
    for sel in soup.find_all("select"):
        attr = " ".join(filter(None, [sel.get("id"), sel.get("name"), sel.get("aria-label"), sel.get("title")])).lower()
        if any(k in attr for k in label_keywords):
            vals = [opt.get_text(strip=True) for opt in sel.find_all("option") if (opt.get("value") or opt.get_text(strip=True))]
            return [v for v in vals if v]
    return []


def list_namespaces(client: HTTPClient) -> List[str]:
    html = _fetch_explorer_html(client)
    options = _extract_select_options(html, ["namespace"]) or []
    # Normalize and de-dup
    uniq: List[str] = []
    for v in options:
        if v and v not in uniq and v.lower() not in {"namespace", "select"}:
            uniq.append(v)
    # Fallback include 'now' if nothing found
    return uniq or ["now"]


def list_api_namespaces(client: HTTPClient, namespace: str) -> List[str]:
    html = _fetch_explorer_html(client)
    apis = _extract_select_options(html, ["api name", "api"]) or []
    cleaned: List[str] = []
    for a in apis:
        if a and a.lower() not in {"api", "api name", "select"} and a not in cleaned:
            cleaned.append(a)
    return cleaned


def list_api_versions(client: HTTPClient, namespace: str, api_name: str) -> List[str]:
    html = _fetch_explorer_html(client)
    versions = _extract_select_options(html, ["version", "api version"]) or []
    cleaned: List[str] = []
    for v in versions:
        if v and re.match(r"^v\d+", v) and v not in cleaned:
            cleaned.append(v)
    return cleaned or ["v1"]


def fetch_dictionary_for_table(client: HTTPClient, table_name: str) -> List[Dict[str, object]]:
    # sys_dictionary contains field-level metadata
    query = f"name={table_name}^internal_typeISNOTEMPTY"
    resp = client.get(
        "/api/now/table/sys_dictionary",
        params={
            "sysparm_fields": "element,column_label,mandatory,internal_type,max_length,reference,read_only,attributes",
            "sysparm_query": query,
            "sysparm_limit": 10000,
        },
    )
    data = resp.json()
    return data.get("result", [])


def discover_servicenow(
    settings: ServiceNowSettings,
    run: RunConfig,
    *,
    resume: bool = False,
    force: bool = False,
) -> Tuple[List[Dict[str, str]], Dict[str, List[Dict[str, object]]]]:
    auth = _sn_auth(settings)
    with HTTPClient(
        base_url=settings.base_url,
        verify=settings.verify_tls,
        timeout_seconds=settings.request_timeout_seconds,
        user_agent=settings.user_agent,
        rate_limit_per_second=settings.rate_limit_per_second,
        auth=auth,
    ) as client:
        tables = enumerate_tables(client)
        # Apply allow/deny filtering if configured
        allow: Iterable[str] = [t.strip() for t in settings.allowlist.split(",") if t.strip()] if settings.allowlist else []
        deny: Iterable[str] = [t.strip() for t in settings.denylist.split(",") if t.strip()] if settings.denylist else []
        filtered = [t for t in tables if (not allow or t.get("name") in allow) and (t.get("name") not in deny)]

        dictionaries: Dict[str, List[Dict[str, object]]] = {}
        store = StateStore(run.state_dir, "servicenow")
        state = store.load()

        for t in filtered:
            name = t.get("name")
            if not name:
                continue
            cached = store.read_dictionary_cache(name) if resume and not force else []
            if cached:
                fields = cached
            else:
                fields = fetch_dictionary_for_table(client, name)
                store.write_dictionary_cache(name, fields)
            dictionaries[name] = fields
            store.upsert_resource(
                state,
                name=name,
                kind="table",
                verified=False,
                evidence=Evidence(sources=["metadata:sys_db_object", "metadata:sys_dictionary"], confidence=0.7),
                meta={"label": t.get("label"), "super_class": t.get("super_class"), "field_count": len(fields)},
            )

        store.save(state)
        return filtered, dictionaries

