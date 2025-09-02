from __future__ import annotations

from typing import Dict, List, Optional, Tuple
import subprocess
import sys
from pathlib import Path


async def _ensure_playwright():
    try:
        from playwright.async_api import async_playwright  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            "Playwright is not installed. Install it with 'uv pip install playwright' and run 'playwright install chromium'"
        ) from exc


async def _install_browsers_if_needed() -> None:
    try:
        # Try to run playwright --version quickly
        subprocess.run([sys.executable, "-m", "playwright", "--version"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass
    # Ensure chromium is available
    subprocess.run([sys.executable, "-m", "playwright", "install", "chromium", "--with-deps"], check=False)


async def _login_servicenow(page, base_url: str, username: Optional[str], password: Optional[str], timeout_ms: int) -> None:
    if not (username and password):
        return
    try:
        await page.goto(base_url.rstrip("/") + "/login.do", timeout=timeout_ms)
        await page.wait_for_load_state("domcontentloaded")
        user = await page.query_selector("#user_name")
        pwd = await page.query_selector("#user_password")
        btn = await page.query_selector("#sysverb_login")
        if user and pwd and btn:
            await user.fill(username)
            await pwd.fill(password)
            await btn.click()
            await page.wait_for_load_state("networkidle")
    except Exception:
        pass


async def discover_catalog_via_browser(
    *, base_url: str, username: Optional[str], password: Optional[str], oauth_token: Optional[str], timeout_ms: int = 60000, debug_dir: Optional[str] = None
) -> Tuple[List[str], Dict[str, List[str]], Dict[Tuple[str, str], List[str]]]:
    await _ensure_playwright()
    await _install_browsers_if_needed()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        context = await browser.new_context()
        page = await context.new_page()

        await _login_servicenow(page, base_url, username, password, timeout_ms)

        start_paths = [
            "/sn_rpexplorer.do",
            "/rest_api_explorer.do",
            "/now/nav/ui/classic/params/target/rest_api_explorer.do",
            "/now/nav/ui/classic/params/target/%24restapi.do",
        ]
        namespaces: List[str] = []
        namespace_to_apis: Dict[str, List[str]] = {}
        api_versions: Dict[Tuple[str, str], List[str]] = {}

        async def get_explorer_frame() -> Optional[object]:  # object to avoid type import
            # Prefer the classic frame
            try:
                await page.wait_for_selector('iframe#gsft_main', timeout=timeout_ms)
                fr = page.frame(name='gsft_main')
                if fr:
                    return fr
            except Exception:
                pass
            # Fallback: find by URL hint
            for fr in page.frames:
                try:
                    if any(hint in (fr.url or '') for hint in [
                        'rest_api_explorer.do', '%24restapi.do', 'restapi', 'explorer'
                    ]):
                        return fr
                except Exception:
                    continue
            return None

        for path in start_paths:
            try:
                await page.goto(base_url.rstrip("/") + path, timeout=timeout_ms)
                await page.wait_for_load_state('domcontentloaded')
                fr = await get_explorer_frame()
                # Wait a moment for dynamic population
                await page.wait_for_timeout(1000)

                # selectors to try (page and frames)
                ns_selectors = [
                    'select[aria-label*="Namespace" i]',
                    'select[id*="namespace" i]',
                    'select[name*="namespace" i]',
                ]
                api_selectors = [
                    'select[aria-label*="API" i]',
                    'select[id*="api" i]',
                    'select[name*="api" i]',
                ]
                ver_selectors = [
                    'select[aria-label*="Version" i]',
                    'select[id*="version" i]',
                    'select[name*="version" i]',
                ]

                async def read_options(selectors: List[str]) -> List[str]:
                    # Prefer explorer frame if available
                    if fr:
                        for sel in selectors:
                            el = await fr.query_selector(sel)
                            if el:
                                return [opt.get("value") or (await opt.text_content() or "").strip() for opt in await el.query_selector_all("option")]
                    # Try on page as fallback
                    for sel in selectors:
                        el = await page.query_selector(sel)
                        if el:
                            return [opt.get("value") or (await opt.text_content() or "").strip() for opt in await el.query_selector_all("option")]
                    # Try other frames
                    for frame in page.frames:
                        for sel in selectors:
                            el = await frame.query_selector(sel)
                            if el:
                                return [opt.get("value") or (await opt.text_content() or "").strip() for opt in await el.query_selector_all("option")]
                    return []

                ns_opts = [v for v in await read_options(ns_selectors) if v]
                if not ns_opts:
                    # capture debug once if requested
                    if debug_dir:
                        dbg = Path(debug_dir)
                        dbg.mkdir(parents=True, exist_ok=True)
                        (dbg / "explorer.html").write_text(await page.content())
                        try:
                            await page.screenshot(path=str(dbg / "explorer.png"))
                        except Exception:
                            pass
                        # dump frame urls
                        (dbg / "frames.txt").write_text("\n".join([f.url for f in page.frames if f.url]))
                    continue
                namespaces = list(dict.fromkeys(ns_opts))

                # iterate apis and versions by selecting
                for ns in namespaces:
                    # Select namespace on explorer frame, page, or frames
                    selected = False
                    if fr:
                        for sel in ns_selectors:
                            el = await fr.query_selector(sel)
                            if el:
                                try:
                                    await el.select_option(ns)
                                    selected = True
                                    break
                                except Exception:
                                    pass
                    for sel in ns_selectors:
                        el = await page.query_selector(sel)
                        if el:
                            try:
                                await el.select_option(ns)
                                selected = True
                                break
                            except Exception:
                                pass
                    if not selected:
                        for frame in page.frames:
                            for sel in ns_selectors:
                                el = await frame.query_selector(sel)
                                if el:
                                    try:
                                        await el.select_option(ns)
                                        selected = True
                                        break
                                    except Exception:
                                        pass
                            if selected:
                                break
                    await page.wait_for_timeout(300)
                    api_opts = [v for v in await read_options(api_selectors) if v]
                    namespace_to_apis[ns] = list(dict.fromkeys(api_opts))
                    for api_name in namespace_to_apis[ns]:
                        # select api on page or frames
                        selected_api = False
                        if fr:
                            for sel in api_selectors:
                                el = await fr.query_selector(sel)
                                if el:
                                    try:
                                        await el.select_option(api_name)
                                        selected_api = True
                                        break
                                    except Exception:
                                        pass
                        for sel in api_selectors:
                            el = await page.query_selector(sel)
                            if el:
                                try:
                                    await el.select_option(api_name)
                                    selected_api = True
                                    break
                                except Exception:
                                    pass
                        if not selected_api:
                            for frame in page.frames:
                                for sel in api_selectors:
                                    el = await frame.query_selector(sel)
                                    if el:
                                        try:
                                            await el.select_option(api_name)
                                            selected_api = True
                                            break
                                        except Exception:
                                            pass
                                if selected_api:
                                    break
                        await page.wait_for_timeout(300)
                        ver_opts = [v for v in await read_options(ver_selectors) if v]
                        api_versions[(ns, api_name)] = list(dict.fromkeys(ver_opts))

                break
            except Exception:
                continue
        await context.close()
        await browser.close()

    return namespaces, namespace_to_apis, api_versions


async def export_openapi_via_browser(
    *, base_url: str, namespace: str, api_name: str, api_version: str, username: Optional[str], password: Optional[str], timeout_ms: int = 30000
) -> Optional[str]:
    await _ensure_playwright()
    await _install_browsers_if_needed()
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        context = await browser.new_context()
        page = await context.new_page()
        await _login_servicenow(page, base_url, username, password, timeout_ms)
        start_paths = [
            "/sn_rpexplorer.do",
            "/rest_api_explorer.do",
            "/now/nav/ui/classic/params/target/rest_api_explorer.do",
            "/now/nav/ui/classic/params/target/%24restapi.do",
        ]
        for path in start_paths:
            try:
                await page.goto(base_url.rstrip("/") + path, timeout=timeout_ms)
                await page.wait_for_timeout(1000)
                # select dropdowns similar to discover and click Export JSON link
                async def select_value(sel_parts: List[str], value: str) -> None:
                    # try on page first
                    for sel in sel_parts:
                        el = await page.query_selector(sel)
                        if el:
                            try:
                                await el.select_option(value)
                                return
                            except Exception:
                                pass
                    # then frames
                    for frame in page.frames:
                        for sel in sel_parts:
                            el = await frame.query_selector(sel)
                            if el:
                                try:
                                    await el.select_option(value)
                                    return
                                except Exception:
                                    pass

                await select_value(['select[aria-label*="Namespace" i]', 'select[id*="namespace" i]'], namespace)
                await page.wait_for_timeout(200)
                await select_value(['select[aria-label*="API" i]', 'select[id*="api" i]'], api_name)
                await page.wait_for_timeout(200)
                await select_value(['select[aria-label*="Version" i]', 'select[id*="version" i]'], api_version)
                await page.wait_for_timeout(200)

                # try to find the export JSON link (page and frames)
                async def find_export() -> Optional[str]:
                    candidates = [
                        'a:has-text("Export OpenAPI Specification (JSON)")',
                        'a:has-text("Export OpenAPI Specification (Yaml)")',
                        'a:has-text("Export")',
                    ]
                    for sel in candidates:
                        el = await page.query_selector(sel)
                        if el:
                            href = await el.get_attribute("href")
                            if href:
                                return href
                    for frame in page.frames:
                        for sel in candidates:
                            el = await frame.query_selector(sel)
                            if el:
                                href = await el.get_attribute("href")
                                if href:
                                    return href
                    return None

                href = await find_export()
                if href and href.startswith("http"):
                    resp = await context.request.get(href, timeout=timeout_ms)
                    if resp.ok:
                        return await resp.text()
            except Exception:
                continue
        await context.close()
        await browser.close()
    return None


