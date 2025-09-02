from __future__ import annotations

from pathlib import Path
import os
from typing import Optional

import typer
from rich import print  # noqa: A001

from .config import RunConfig, ServiceNowSettings
from .discovery.servicenow import discover_servicenow, list_namespaces, list_api_namespaces, list_api_versions
from .discovery.sn_browser import discover_catalog_via_browser, export_openapi_via_browser
from .synthesis.openapi import synthesize_servicenow_spec
from .validation.static import validate_openapi_spec
from .validation.runtime import probe_servicenow_tables
from .state import StateStore


app = typer.Typer(add_completion=False, no_args_is_help=True)
sn_app = typer.Typer(help="ServiceNow helpers")
sf_app = typer.Typer(help="Salesforce helpers (stubs)")
pega_app = typer.Typer(help="Pega helpers (stubs)")
app.add_typer(sn_app, name="sn")
app.add_typer(sf_app, name="sf")
app.add_typer(pega_app, name="pega")


@app.command()
def discover(
    platform: str = typer.Argument(..., help="Platform: servicenow|salesforce|pega"),
    base_url: Optional[str] = typer.Option(None, help="Base URL for the platform"),
    username: Optional[str] = typer.Option(None, help="Basic auth username"),
    password: Optional[str] = typer.Option(None, help="Basic auth password"),
    oauth_token: Optional[str] = typer.Option(None, help="OAuth bearer token"),
    allowlist: Optional[str] = typer.Option(None, help="Comma-separated allowlist values"),
    denylist: Optional[str] = typer.Option(None, help="Comma-separated denylist values"),
    state_dir: Optional[str] = typer.Option(None, help="Absolute state directory"),
    specs_dir: Optional[str] = typer.Option(None, help="Absolute specs directory"),
    resume: bool = typer.Option(False, help="Resume using cached dictionaries if present"),
    force: bool = typer.Option(False, help="Force re-fetch, ignoring caches"),
):
    default_root = Path(__file__).resolve().parents[2]
    run = RunConfig(
        state_dir=str(Path(state_dir) if state_dir else default_root / ".state"),
        specs_dir=str(Path(specs_dir) if specs_dir else default_root / "openapi_specs"),
    )
    print(f"Using state_dir: {run.state_dir}")
    if platform.lower() == "servicenow":
        sn_kwargs: dict[str, object] = {}
        sn_kwargs["base_url"] = base_url or os.getenv("API_DISCOVERY_SERVICENOW_BASE_URL", "")
        if username is not None or os.getenv("API_DISCOVERY_SERVICENOW_USERNAME"):
            sn_kwargs["username"] = username or os.getenv("API_DISCOVERY_SERVICENOW_USERNAME")
        if password is not None or os.getenv("API_DISCOVERY_SERVICENOW_PASSWORD"):
            sn_kwargs["password"] = password or os.getenv("API_DISCOVERY_SERVICENOW_PASSWORD")
        if oauth_token is not None or os.getenv("API_DISCOVERY_SERVICENOW_OAUTH_TOKEN"):
            sn_kwargs["oauth_token"] = oauth_token or os.getenv("API_DISCOVERY_SERVICENOW_OAUTH_TOKEN")
        if allowlist is not None:
            sn_kwargs["allowlist"] = allowlist
        if denylist is not None:
            sn_kwargs["denylist"] = denylist
        settings = ServiceNowSettings(**sn_kwargs)
        from .state import StateStore
        store = StateStore(run.state_dir, "servicenow")
        if resume and not force and not store.list_cached_tables():
            print(f"[yellow]No cached dictionaries found in {store.cache_dir}. Fetching fresh.[/yellow]")
        tables, dictionaries = discover_servicenow(settings, run, resume=resume, force=force)
        print(f"Discovered {len(tables)} tables")
        typer.echo("Done")
    else:
        raise typer.BadParameter("Only 'servicenow' is implemented in P0")


@app.command()
def synthesize(
    platform: str = typer.Argument(...),
    base_url: str = typer.Option(..., help="Base URL used in servers[0].variables.server_url.default"),
    out: str = typer.Option(..., help="Output OpenAPI JSON path"),
):
    if platform.lower() == "servicenow":
        # For now, require a cache/dictionaries path in the future. Use state dir for list, but we need dictionaries from last discovery call.
        # To keep P0 simple, we won't persist full dictionaries yet; this command expects to be called right after discover.
        raise typer.BadParameter("For P0, use the discover-and-synthesize command instead.")
    else:
        raise typer.BadParameter("Only 'servicenow' is implemented in P0")


@app.command(name="discover-and-synthesize")
def discover_and_synthesize(
    platform: str = typer.Argument(...),
    base_url: Optional[str] = typer.Option(None, help="Base URL for discovery and servers var (or env)"),
    username: Optional[str] = typer.Option(None),
    password: Optional[str] = typer.Option(None),
    oauth_token: Optional[str] = typer.Option(None),
    allowlist: Optional[str] = typer.Option(None),
    denylist: Optional[str] = typer.Option(None),
    out: str = typer.Option("openapi_specs/servicenow_generated.json"),
    resume: bool = typer.Option(False, help="Resume using cached dictionaries if present"),
    force: bool = typer.Option(False, help="Force re-fetch, ignoring caches"),
    namespace: Optional[str] = typer.Option(None, help="Docs namespace"),
    api_name: Optional[str] = typer.Option(None, help="API name"),
    api_version: Optional[str] = typer.Option(None, help="API version"),
    state_dir: Optional[str] = typer.Option(None, help="Absolute state directory"),
    specs_dir: Optional[str] = typer.Option(None, help="Absolute specs directory"),
):
    default_root = Path(__file__).resolve().parents[2]
    run = RunConfig(
        state_dir=str(Path(state_dir) if state_dir else default_root / ".state"),
        specs_dir=str(Path(specs_dir) if specs_dir else default_root / "openapi_specs"),
    )
    print(f"Using state_dir: {run.state_dir}")
    if platform.lower() == "servicenow":
        sn_kwargs: dict[str, object] = {}
        sn_kwargs["base_url"] = base_url or os.getenv("API_DISCOVERY_SERVICENOW_BASE_URL", "")
        if username is not None or os.getenv("API_DISCOVERY_SERVICENOW_USERNAME"):
            sn_kwargs["username"] = username or os.getenv("API_DISCOVERY_SERVICENOW_USERNAME")
        if password is not None or os.getenv("API_DISCOVERY_SERVICENOW_PASSWORD"):
            sn_kwargs["password"] = password or os.getenv("API_DISCOVERY_SERVICENOW_PASSWORD")
        if oauth_token is not None or os.getenv("API_DISCOVERY_SERVICENOW_OAUTH_TOKEN"):
            sn_kwargs["oauth_token"] = oauth_token or os.getenv("API_DISCOVERY_SERVICENOW_OAUTH_TOKEN")
        if allowlist is not None:
            sn_kwargs["allowlist"] = allowlist
        if denylist is not None:
            sn_kwargs["denylist"] = denylist
        settings = ServiceNowSettings(**sn_kwargs)
        from .state import StateStore
        store = StateStore(run.state_dir, "servicenow", namespace=namespace, api_name=api_name, api_version=api_version)
        if resume and not force and not store.list_cached_tables():
            print(f"[yellow]No cached dictionaries found in {store.cache_dir}. Fetching fresh.[/yellow]")
        _, dictionaries = discover_servicenow(settings, run, resume=resume, force=force)
        out_path = synthesize_servicenow_spec(
            base_url=settings.base_url,
            dictionaries=dictionaries,
            output_path=out,
            namespace=namespace,
            api_name=api_name,
            api_version=api_version,
        )
        ok, msg = validate_openapi_spec(out_path)
        if not ok:
            raise typer.Exit(code=2)
        print(f"Spec written: {out_path}")
    else:
        raise typer.BadParameter("Only 'servicenow' is implemented in P0")


def main() -> None:  # pragma: no cover
    app()


@app.command()
def validate_spec(path: str = typer.Option(..., "--path", help="Path to OpenAPI spec JSON")) -> None:
    ok, msg = validate_openapi_spec(path)
    if not ok:
        print(f"[red]Invalid spec:[/red] {msg}")
        raise typer.Exit(code=2)
    print("[green]Spec is valid[/green]")


# ServiceNow catalog discovery
@sn_app.command("list-namespaces")
def sn_list_namespaces(
    base_url: Optional[str] = typer.Option(None),
    username: Optional[str] = typer.Option(None),
    password: Optional[str] = typer.Option(None),
    oauth_token: Optional[str] = typer.Option(None),
    headless: bool = typer.Option(False, help="Use headless browser to enumerate dynamically rendered options"),
) -> None:
    sn_kwargs: dict[str, object] = {
        "base_url": base_url or os.getenv("API_DISCOVERY_SERVICENOW_BASE_URL", "")
    }
    if username is not None or os.getenv("API_DISCOVERY_SERVICENOW_USERNAME"):
        sn_kwargs["username"] = username or os.getenv("API_DISCOVERY_SERVICENOW_USERNAME")
    if password is not None or os.getenv("API_DISCOVERY_SERVICENOW_PASSWORD"):
        sn_kwargs["password"] = password or os.getenv("API_DISCOVERY_SERVICENOW_PASSWORD")
    if oauth_token is not None or os.getenv("API_DISCOVERY_SERVICENOW_OAUTH_TOKEN"):
        sn_kwargs["oauth_token"] = oauth_token or os.getenv("API_DISCOVERY_SERVICENOW_OAUTH_TOKEN")
    settings = ServiceNowSettings(**sn_kwargs)
    from .http import HTTPClient, AuthConfig

    auth = (
        AuthConfig(username=settings.username, password=settings.password)
        if settings.username and settings.password
        else (AuthConfig(bearer_token=settings.oauth_token) if settings.oauth_token else AuthConfig())
    )
    with HTTPClient(
        base_url=settings.base_url,
        verify=settings.verify_tls,
        timeout_seconds=settings.request_timeout_seconds,
        user_agent=settings.user_agent,
        rate_limit_per_second=settings.rate_limit_per_second,
        auth=auth,
    ) as client:
        if headless:
            import asyncio
            ns, _, _ = asyncio.run(
                discover_catalog_via_browser(
                    base_url=settings.base_url, username=settings.username, password=settings.password, oauth_token=settings.oauth_token
                )
            )
            for n in ns:
                print(n)
        else:
            namespaces = list_namespaces(client)
            for n in namespaces:
                print(n)


@sn_app.command("list-apis")
def sn_list_apis(
    base_url: Optional[str] = typer.Option(None),
    namespace: str = typer.Option(...),
    username: Optional[str] = typer.Option(None),
    password: Optional[str] = typer.Option(None),
    oauth_token: Optional[str] = typer.Option(None),
    headless: bool = typer.Option(False, help="Use headless browser to enumerate dynamically rendered options"),
) -> None:
    sn_kwargs: dict[str, object] = {
        "base_url": base_url or os.getenv("API_DISCOVERY_SERVICENOW_BASE_URL", "")
    }
    if username is not None or os.getenv("API_DISCOVERY_SERVICENOW_USERNAME"):
        sn_kwargs["username"] = username or os.getenv("API_DISCOVERY_SERVICENOW_USERNAME")
    if password is not None or os.getenv("API_DISCOVERY_SERVICENOW_PASSWORD"):
        sn_kwargs["password"] = password or os.getenv("API_DISCOVERY_SERVICENOW_PASSWORD")
    if oauth_token is not None or os.getenv("API_DISCOVERY_SERVICENOW_OAUTH_TOKEN"):
        sn_kwargs["oauth_token"] = oauth_token or os.getenv("API_DISCOVERY_SERVICENOW_OAUTH_TOKEN")
    settings = ServiceNowSettings(**sn_kwargs)
    from .http import HTTPClient, AuthConfig
    auth = (
        AuthConfig(username=settings.username, password=settings.password)
        if settings.username and settings.password
        else (AuthConfig(bearer_token=settings.oauth_token) if settings.oauth_token else AuthConfig())
    )
    with HTTPClient(
        base_url=settings.base_url,
        verify=settings.verify_tls,
        timeout_seconds=settings.request_timeout_seconds,
        user_agent=settings.user_agent,
        rate_limit_per_second=settings.rate_limit_per_second,
        auth=auth,
    ) as client:
        if headless:
            import asyncio
            _, ns_to_apis, _ = asyncio.run(
                discover_catalog_via_browser(
                    base_url=settings.base_url, username=settings.username, password=settings.password, oauth_token=settings.oauth_token
                )
            )
            for a in ns_to_apis.get(namespace, []):
                print(a)
        else:
            apis = list_api_namespaces(client, namespace)
            for a in apis:
                print(a)


@sn_app.command("list-versions")
def sn_list_versions(
    base_url: Optional[str] = typer.Option(None),
    namespace: str = typer.Option(...),
    api_name: str = typer.Option(...),
    username: Optional[str] = typer.Option(None),
    password: Optional[str] = typer.Option(None),
    oauth_token: Optional[str] = typer.Option(None),
    headless: bool = typer.Option(False, help="Use headless browser to enumerate dynamically rendered options"),
) -> None:
    sn_kwargs: dict[str, object] = {
        "base_url": base_url or os.getenv("API_DISCOVERY_SERVICENOW_BASE_URL", "")
    }
    if username is not None or os.getenv("API_DISCOVERY_SERVICENOW_USERNAME"):
        sn_kwargs["username"] = username or os.getenv("API_DISCOVERY_SERVICENOW_USERNAME")
    if password is not None or os.getenv("API_DISCOVERY_SERVICENOW_PASSWORD"):
        sn_kwargs["password"] = password or os.getenv("API_DISCOVERY_SERVICENOW_PASSWORD")
    if oauth_token is not None or os.getenv("API_DISCOVERY_SERVICENOW_OAUTH_TOKEN"):
        sn_kwargs["oauth_token"] = oauth_token or os.getenv("API_DISCOVERY_SERVICENOW_OAUTH_TOKEN")
    settings = ServiceNowSettings(**sn_kwargs)
    from .http import HTTPClient, AuthConfig
    auth = (
        AuthConfig(username=settings.username, password=settings.password)
        if settings.username and settings.password
        else (AuthConfig(bearer_token=settings.oauth_token) if settings.oauth_token else AuthConfig())
    )
    with HTTPClient(
        base_url=settings.base_url,
        verify=settings.verify_tls,
        timeout_seconds=settings.request_timeout_seconds,
        user_agent=settings.user_agent,
        rate_limit_per_second=settings.rate_limit_per_second,
        auth=auth,
    ) as client:
        if headless:
            import asyncio
            _, _, api_versions = asyncio.run(
                discover_catalog_via_browser(
                    base_url=settings.base_url, username=settings.username, password=settings.password, oauth_token=settings.oauth_token
                )
            )
            for v in api_versions.get((namespace, api_name), []):
                print(v)
        else:
            versions = list_api_versions(client, namespace, api_name)
            for v in versions:
                print(v)


@sn_app.command("export-spec")
def sn_export_spec(
    base_url: Optional[str] = typer.Option(None),
    namespace: str = typer.Option(...),
    api_name: str = typer.Option(...),
    api_version: str = typer.Option(...),
    username: Optional[str] = typer.Option(None),
    password: Optional[str] = typer.Option(None),
) -> None:
    sn_kwargs: dict[str, object] = {
        "base_url": base_url or os.getenv("API_DISCOVERY_SERVICENOW_BASE_URL", "")
    }
    if username is not None or os.getenv("API_DISCOVERY_SERVICENOW_USERNAME"):
        sn_kwargs["username"] = username or os.getenv("API_DISCOVERY_SERVICENOW_USERNAME")
    if password is not None or os.getenv("API_DISCOVERY_SERVICENOW_PASSWORD"):
        sn_kwargs["password"] = password or os.getenv("API_DISCOVERY_SERVICENOW_PASSWORD")
    settings = ServiceNowSettings(**sn_kwargs)
    import asyncio
    text = asyncio.run(
        export_openapi_via_browser(
            base_url=settings.base_url,
            namespace=namespace,
            api_name=api_name,
            api_version=api_version,
            username=settings.username,
            password=settings.password,
        )
    )
    if text:
        out_dir = Path("openapi_specs") / namespace / api_name / api_version
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "exported.json"
        out_path.write_text(text)
        print(str(out_path))
    else:
        print("No spec available via export; use discover-and-synthesize to generate one.")


@sn_app.command("crawl-catalog")
def sn_crawl_catalog(
    base_url: Optional[str] = typer.Option(None),
    headless: bool = typer.Option(True, help="Use headless browser for dynamic explorer"),
    username: Optional[str] = typer.Option(None),
    password: Optional[str] = typer.Option(None),
    max_specs: int = typer.Option(200, help="Max number of specs to process in this run"),
    resume: bool = typer.Option(True, help="Reuse caches/state where possible"),
    force: bool = typer.Option(False, help="Force re-discovery even if cached"),
) -> None:
    sn_kwargs: dict[str, object] = {
        "base_url": base_url or os.getenv("API_DISCOVERY_SERVICENOW_BASE_URL", "")
    }
    if username is not None or os.getenv("API_DISCOVERY_SERVICENOW_USERNAME"):
        sn_kwargs["username"] = username or os.getenv("API_DISCOVERY_SERVICENOW_USERNAME")
    if password is not None or os.getenv("API_DISCOVERY_SERVICENOW_PASSWORD"):
        sn_kwargs["password"] = password or os.getenv("API_DISCOVERY_SERVICENOW_PASSWORD")
    settings = ServiceNowSettings(**sn_kwargs)

    # Discover catalog
    catalogs = []
    import asyncio
    if headless:
        ns, ns_to_apis, api_versions = asyncio.run(
            discover_catalog_via_browser(
                base_url=settings.base_url,
                username=settings.username,
                password=settings.password,
                oauth_token=settings.oauth_token,
            )
        )
        for namespace in ns:
            for api_name in ns_to_apis.get(namespace, []):
                for ver in api_versions.get((namespace, api_name), []):
                    catalogs.append((namespace, api_name, ver))
    else:
        from .http import HTTPClient, AuthConfig
        auth = (
            AuthConfig(username=settings.username, password=settings.password)
            if settings.username and settings.password
            else (AuthConfig(bearer_token=settings.oauth_token) if settings.oauth_token else AuthConfig())
        )
        with HTTPClient(
            base_url=settings.base_url,
            verify=settings.verify_tls,
            timeout_seconds=settings.request_timeout_seconds,
            user_agent=settings.user_agent,
            rate_limit_per_second=settings.rate_limit_per_second,
            auth=auth,
        ) as client:
            for namespace in list_namespaces(client):
                for api_name in list_api_namespaces(client, namespace):
                    for ver in list_api_versions(client, namespace, api_name):
                        catalogs.append((namespace, api_name, ver))

    # Persist catalog index
    run = RunConfig()
    catalog_path = Path(run.state_dir) / "servicenow" / "_catalog.json"
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    import json
    catalog_path.write_text(json.dumps([{"namespace": n, "api": a, "version": v} for (n, a, v) in catalogs], indent=2))
    print(f"Catalog entries: {len(catalogs)}")

    # Export or generate up to limit
    processed = 0
    for namespace, api_name, ver in catalogs:
        if processed >= max_specs:
            break
        # Try export first
        text = asyncio.run(
            export_openapi_via_browser(
                base_url=settings.base_url,
                namespace=namespace,
                api_name=api_name,
                api_version=ver,
                username=settings.username,
                password=settings.password,
            )
        )
        out_dir = Path(run.specs_dir) / namespace / api_name / ver
        out_dir.mkdir(parents=True, exist_ok=True)
        if text:
            (out_dir / "exported.json").write_text(text)
            processed += 1
            print(f"Exported {namespace}/{api_name}/{ver}")
            continue

        # If Table API or no export, generate via our discovery pipeline
        if api_name.lower().startswith("table"):
            # Narrow generation to reuse our current metadata-based generator (tables)
            _, dictionaries = discover_servicenow(settings, run, resume=resume, force=force)
            out_path = synthesize_servicenow_spec(
                base_url=settings.base_url,
                dictionaries=dictionaries,
                output_path=str(out_dir / "servicenow_generated.json"),
                namespace=namespace,
                api_name=api_name,
                api_version=ver,
            )
            ok, msg = validate_openapi_spec(out_path)
            if ok:
                print(f"Generated {namespace}/{api_name}/{ver}")
                processed += 1
            else:
                print(f"Validation failed for {namespace}/{api_name}/{ver}: {msg}")


@app.command()
def status(platform: str = typer.Argument(...)) -> None:
    run = RunConfig()
    store = StateStore(run.state_dir, platform)
    state = store.load()
    print(f"Known: {len(state.known)} | Unknown: {len(state.unknown)}")
    for name, rec in list(state.known.items())[:10]:
        print(f"- {name}: {'verified' if rec.verified else 'discovered'}")


@app.command(name="runtime-validate")
def runtime_validate(
    platform: str = typer.Argument(...),
    base_url: Optional[str] = typer.Option(None),
    username: Optional[str] = typer.Option(None),
    password: Optional[str] = typer.Option(None),
    oauth_token: Optional[str] = typer.Option(None),
) -> None:
    run = RunConfig()
    if platform.lower() == "servicenow":
        sn_kwargs: dict[str, object] = {}
        sn_kwargs["base_url"] = base_url or os.getenv("API_DISCOVERY_SERVICENOW_BASE_URL", "")
        if username is not None:
            sn_kwargs["username"] = username
        if password is not None:
            sn_kwargs["password"] = password
        if oauth_token is not None:
            sn_kwargs["oauth_token"] = oauth_token
        settings = ServiceNowSettings(**sn_kwargs)
        store = StateStore(run.state_dir, "servicenow")
        state = store.load()
        tables = list(state.known.keys()) or store.list_cached_tables()
        results = probe_servicenow_tables(settings, tables)
        verified = 0
        for table, ok, msg in results:
            if ok:
                store.set_verified(state, table)
                verified += 1
        store.save(state)
        print(f"Verified {verified}/{len(tables)} tables")
    else:
        raise typer.BadParameter("Only 'servicenow' is implemented in P0")

