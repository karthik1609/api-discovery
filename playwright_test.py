# pip install playwright bs4 lxml
# playwright install chrome
import asyncio, json, tempfile
from pathlib import Path
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

ARTICLE_SELECTORS = ["main article","article","[data-zoomin-content]","#doc-content,.doc-content","#content,.content","body"]

async def fetch_rendered_html(url: str, profile_dir: Path, headless: bool = False, timeout_ms: int = 30000) -> str:
    async with async_playwright() as p:
        browser = await p.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            channel="chrome",              # use system Chrome channel
            headless=headless,
            viewport={"width":1280, "height":900},
            locale="en-US",
            timezone_id="Asia/Kolkata",
            user_agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"),
            ignore_https_errors=False,
        )
        page = await browser.new_page()
        # Be slightly polite
        await page.set_extra_http_headers({"Accept-Language": "en-US,en;q=0.9"})
        resp = await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        if not resp or not resp.ok:
            await browser.close()
            raise RuntimeError(f"HTTP {resp.status if resp else 'no response'}")

        # Click cookie banner if present (selector varies across bundles)
        for sel in ["#onetrust-accept-btn-handler","button[aria-label='Accept all']",".osano-cm-accept-all"]:
            try:
                await page.locator(sel).click(timeout=2000)
                break
            except Exception:
                pass

        # Wait for content
        await page.wait_for_selector(",".join(ARTICLE_SELECTORS), state="attached", timeout=timeout_ms)
        html = await page.content()
        await browser.close()
        return html

def extract_to_markdown(html: str, base_url: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    root = None
    for sel in ARTICLE_SELECTORS:
        root = soup.select_one(sel)
        if root and root.get_text(strip=True):
            break
    if not root:
        root = soup

    # Title
    title = (root.find("h1").get_text(strip=True) if root.find("h1") else
             (soup.title.get_text(strip=True) if soup.title else ""))
    out = [f"# {title}\n"] if title else []

    # Extract paragraphs, lists, code, tables
    def add(txt=""): 
        if txt: out.append(txt)

    for el in root.find_all(["h2","h3","p","pre","ul","ol","table"]):
        if el.name in ("h2","h3"): add(f"## {el.get_text(' ', strip=True)}")
        elif el.name == "p": add(el.get_text(" ", strip=True))
        elif el.name == "pre":
            code = el.get_text("\n", strip=True)
            add("```"); add(code); add("```")
        elif el.name in ("ul","ol"):
            items = [li.get_text(" ", strip=True) for li in el.find_all("li", recursive=False)]
            for i, it in enumerate(items):
                bullet = f"{i+1}." if el.name=="ol" else "-"
                add(f"{bullet} {it}")
        elif el.name == "table":
            rows = [[c.get_text(" ", strip=True) for c in tr.find_all(["th","td"])] 
                    for tr in el.find_all("tr")]
            if rows:
                add("| " + " | ".join(rows[0]) + " |")
                add("| " + " | ".join(["---"]*len(rows[0])) + " |")
                for r in rows[1:]:
                    add("| " + " | ".join(r) + " |")
        add()

    # Pull /api/now patterns
    import re
    text_all = root.get_text("\n", strip=True)
    patterns = sorted(set(re.findall(r"/api/now(?:/v\\d+)?(?:/[A-Za-z0-9_-]+)+(?:/\\{?[A-Za-z0-9_]+\\}?){0,4}", text_all)))
    if patterns:
        out.insert(1, "")
        out.insert(1, "\n".join([f"- `{p}`" for p in patterns]))
        out.insert(1, "**Discovered API base paths:**")

    return "\n".join(out).strip()+"\n"

if __name__ == "__main__":
    import sys
    url = sys.argv[1] if len(sys.argv)>1 else "https://www.servicenow.com/docs/bundle/washingtondc-api-reference/page/integrate/inbound-rest/concept/c_TableAPI.html"
    prof = Path(tempfile.gettempdir())/ "sn_docs_profile"
    prof.mkdir(exist_ok=True)
    # First run once with headless=False (manual) if needed
    html = asyncio.run(fetch_rendered_html(url, prof, headless=False))
    md = extract_to_markdown(html, url)
    Path("servicenow_tableapi.md").write_text(md, encoding="utf-8")
    print("Wrote servicenow_tableapi.md")
