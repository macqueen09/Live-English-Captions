"""Browser regression checks for compact layout and live scrolling (no personal writes)."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from playwright.sync_api import sync_playwright

root = Path(__file__).resolve().parents[1]
start = datetime(2026, 10, 2, 20, 0, tzinfo=timezone(timedelta(hours=8)))
rows = []


def add(text, source=None, gap=30):
    stamp = (
        start
        if not rows
        else datetime.fromisoformat(rows[-1]["timestamp"]) + timedelta(seconds=gap)
    )
    rows.append(
        dict(
            id=len(rows) + 1,
            timestamp=stamp.isoformat(),
            date=stamp.date().isoformat(),
            time=stamp.strftime("%H:%M:%S"),
            en=text,
            zh="这是用于检查字幕排版的例句。",
            source=source or ("microphone" if len(rows) % 2 else "remote:abcd1234:1"),
            speaker="我"
            if (source == "microphone" or (source is None and len(rows) % 2))
            else "Alice",
            session="abcd1234",
        )
    )


for i in range(24):
    add(f"This is sentence {i + 1}. We are practicing English together.")

with sync_playwright() as p:
    browser = p.chromium.launch(channel="msedge", headless=True)
    page = browser.new_page(viewport={"width": 1280, "height": 900})

    def state(route):
        after = int(route.request.url.split("after=")[-1])
        route.fulfill(
            json=dict(
                status="正在监听",
                error="",
                level=0,
                running=False,
                rows=[r for r in rows if r["id"] > after],
            )
        )

    page.route("**/api/state?*", state)
    page.goto("http://127.0.0.1:8765")
    page.wait_for_function("lastId===24")
    page.wait_for_function("followLatest")
    assert page.locator("h1").inner_text() == "Live English Captions"
    assert page.locator("#rows article").count() == 12
    # Scroll back: incoming speech must not shift/remove old captions.
    page.evaluate("document.getElementById('live-scroll').scrollTop=100")
    page.wait_for_function("!followLatest")
    first = page.locator("#rows article").first.get_attribute("data-id")
    position = page.locator("#live-scroll").evaluate("el=>el.scrollTop")
    add("Here comes a new sentence while you are reading earlier messages.")
    page.wait_for_function("lastId===25")
    assert page.locator("#rows article").first.get_attribute("data-id") == first
    assert abs(page.locator("#live-scroll").evaluate("el=>el.scrollTop") - position) < 2
    # Bottom resumes following, including when a short fragment merges with the last sentence.
    page.evaluate(
        "const sc=document.getElementById('live-scroll');sc.scrollTop=sc.scrollHeight"
    )
    page.wait_for_function("followLatest")
    add("And here is the rest of that thought.", rows[-1]["source"], gap=2)
    page.wait_for_function("lastId===26")
    assert "rest of that thought" in page.locator("#rows .spoken").last.inner_text()
    assert page.locator("#rows article").last.evaluate("el=>el.captionRows.length") == 2
    page.wait_for_function(
        "document.getElementById('live-scroll').scrollHeight-document.getElementById('live-scroll').scrollTop-document.getElementById('live-scroll').clientHeight<9"
    )
    page.screenshot(path=str(root / ".tools" / "layout-normal.png"))
    normal_height = page.locator("#live-scroll").bounding_box()["height"]
    page.locator("#compact").click()
    assert page.locator("nav").is_hidden()
    assert page.locator("#compact").inner_text() == "退出字幕模式"
    assert page.locator("#live-scroll").bounding_box()["height"] > normal_height + 150
    page.screenshot(path=str(root / ".tools" / "layout-caption-mode.png"))
    page.locator("#compact").click()
    assert page.locator("nav").is_visible()
    browser.close()
print(
    "Layout passed: dense rows, merge, paused scroll, resumed follow, distinct caption mode."
)
