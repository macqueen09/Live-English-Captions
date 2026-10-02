"""Browser regression checks for compact layout and live scrolling (no personal writes)."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from playwright.sync_api import sync_playwright
import sys

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
from caption_layout import LiveParagraphs
layout = LiveParagraphs()
partials = []
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
        after = int(route.request.url.split("after=")[-1].split("&")[0])
        route.fulfill(
            json=dict(
                status="正在监听",
                error="",
                level=0,
                running=False,
                hardware={"asr": "GPU", "translation": "CPU", "fallback": {}},
                paragraphs=layout.apply(rows, partials),
                partials=partials,
                rows=[r for r in rows if r["id"] > after],
            )
        )

    page.route("**/api/state?*", state)
    page.route("**/api/live?*", state)
    page.goto("http://127.0.0.1:8765")
    page.wait_for_function("lastId===24")
    page.wait_for_function("followLatest")
    assert page.locator("h1").inner_text().startswith("Live English Captions")
    assert "ASR GPU / 中文 CPU" in page.locator("h1").inner_text()
    assert page.locator("#rows article").count() == 12
    # Scroll back: incoming speech must not shift/remove old captions.
    page.evaluate("document.getElementById('live-scroll').scrollTop=100")
    page.wait_for_function("!followLatest")
    first = page.locator("#rows article").first.get_attribute("data-id")
    position = page.locator("#live-scroll").evaluate("el=>el.scrollTop")
    add("Here comes a new sentence while you are reading earlier messages.")
    page.wait_for_function("lastId===25")
    assert page.locator("#rows article").last.locator(".spoken .caption-new").inner_text().startswith("Here comes")
    assert page.locator('#translation-scroll [data-id="25"] .caption-new').count() == 1
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
    assert page.locator("#rows .spoken").last.locator(".caption-new").last.inner_text().strip() == "And here is the rest of that thought."
    assert page.locator('#translation-scroll [data-id="26"] .caption-new').inner_text().strip() == rows[-1]["zh"]
    emphasized_box = page.locator("#rows article").last.bounding_box()
    page.wait_for_timeout(4700)
    assert page.locator("#rows .caption-new").count() == 0
    assert page.locator("#rows article").last.bounding_box() == emphasized_box
    page.wait_for_function(
        "document.getElementById('live-scroll').scrollHeight-document.getElementById('live-scroll').scrollTop-document.getElementById('live-scroll').clientHeight<9"
    )
    page.screenshot(path=str(root / ".tools" / "layout-normal.png"))
    launched = []

    def launch(route):
        launched.append(True)
        route.fulfill(json={"ok": True})

    page.route("**/api/overlay", launch)
    page.locator("#compact").click()
    page.wait_for_function(
        "document.getElementById('compact').textContent==='打开悬浮字幕'"
    )
    assert launched
    assert page.locator("nav").is_visible()
    # Delayed Chinese patches target the original span inside a merged paragraph.
    latest = rows[-1]
    page.evaluate("row => updateTranslation({...row, zh:'延后补上的中文'})", latest)
    page.evaluate("renderChinese()")
    assert page.locator(f'#translation-scroll [data-id="{latest["id"]}"] .translation-text').inner_text() == "延后补上的中文"
    partials.append({"source":"output", "utterance":"test", "en":"This appears before the sentence ends", "speaker":"Other"})
    page.wait_for_function("document.querySelector('#rows article:last-child .spoken').textContent.includes('before the sentence ends')")
    key = page.locator("#rows article").last.get_attribute("data-paragraph-key")
    partials[0]["en"] += " with more words"
    page.wait_for_function("document.querySelector('#rows article:last-child .spoken').textContent.endsWith('with more words')")
    assert page.locator("#rows .caption-new").last.inner_text() == " with more words"
    rectangle = page.locator("#rows article").last.locator(".spoken").bounding_box()
    add(partials[0]["en"], rows[-1]["source"], gap=2)
    rows[-1]["utterance"] = "test"
    rows[-1]["capture_source"] = "output"
    partials.clear()
    page.wait_for_function("lastId===27")
    assert page.locator("#rows article").last.get_attribute("data-paragraph-key") == key
    assert page.locator("#rows article").last.locator(".spoken").bounding_box() == rectangle
    browser.close()
print("Layout passed: dense rows, merge, scrolling and native overlay launch request.")
