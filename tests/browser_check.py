"""End-to-end checks against an isolated database, using installed Microsoft Edge."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from storage import Store
from playwright.sync_api import sync_playwright

root = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory() as folder:
    store = Store(folder)
    for i in range(15):
        store.append(
            f"I enjoy hiking on the weekend. Sentence {i + 1}.",
            "我喜欢周末去徒步。",
            "microphone" if i % 2 else "remote:abcd1234:1",
        )
    env = dict(os.environ, SUBTITLES_DATA_DIR=folder, PYTHONIOENCODING="utf-8")
    with open(root / ".tools" / "browser-server.log", "w", encoding="utf-8") as log:
        process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app:app", "--port", "8766"],
            cwd=root,
            env=env,
            stdout=log,
            stderr=log,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        try:
            for _ in range(100):
                try:
                    urllib.request.urlopen("http://127.0.0.1:8766/api/state", timeout=1)
                    break
                except Exception:
                    time.sleep(0.2)
            with sync_playwright() as p:
                browser = p.chromium.launch(channel="msedge", headless=True)
                page = browser.new_page(viewport={"width": 1280, "height": 900})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto("http://127.0.0.1:8766")
                page.wait_for_selector("#rows article")
                assert page.locator("#rows article").count() == 12
                page.wait_for_function(
                    "document.querySelectorAll('#microphone option').length>1"
                )
                sizes = page.evaluate(
                    "({en:parseFloat(getComputedStyle(document.querySelector('.en')).fontSize),zh:parseFloat(getComputedStyle(document.querySelector('.zh')).fontSize)})"
                )
                assert sizes["en"] > sizes["zh"]
                page.locator("#rows .spoken").last.evaluate(
                    "el=>{const range=document.createRange();const start=el.textContent.indexOf('weekend');const text=el.firstChild.nodeType===3?el.firstChild:el.firstChild.firstChild;range.setStart(text,start);range.setEnd(text,start+7);const s=getSelection();s.removeAllRanges();s.addRange(range);el.dispatchEvent(new MouseEvent('mouseup',{bubbles:true}))}"
                )
                assert page.locator("#lookup-term").input_value() == "weekend"
                async_state = {"injected": False}

                def new_caption(route):
                    response = route.fetch(url=route.request.url.replace('/api/live?', '/api/state?'))
                    data = response.json()
                    if not async_state["injected"]:
                        extra = dict(
                            store.recent()[-1],
                            id=16,
                            source="microphone",
                            speaker="我（麦克风）",
                            en="Here is another sentence.",
                        )
                        data["rows"].append(extra)
                        async_state["injected"] = True
                    route.fulfill(response=response, json=data)

                page.route("**/api/state?*", new_caption)
                page.route("**/api/live?*", new_caption)
                # Complete the outstanding long poll so the new route is exercised.
                page.evaluate("fetch('/api/stop',{method:'POST'})")
                # No full caption redraw during polling: the selected text stays selected.
                page.wait_for_timeout(2300)
                assert page.evaluate("getSelection().toString()") == "weekend"
                assert page.locator("#rows article").count() == 13
                page.locator("#lookup-translate").click()
                page.wait_for_function(
                    "!document.getElementById('lookup-save').disabled", timeout=60000
                )
                assert "周末" in page.locator("#lookup-result").inner_text()
                page.locator("#lookup-save").click()
                page.wait_for_function(
                    "document.getElementById('lookup-message').textContent.includes('已保存')"
                )
                page.locator("#lookup-close").click()
                page.locator("[data-tab=vocabulary]").click()
                page.wait_for_selector("#word-list article")
                assert page.locator("#word-list strong").inner_text() == "weekend"
                page.locator("#study-start").click()
                page.wait_for_function(
                    "document.getElementById('study-term').textContent==='weekend'"
                )
                page.locator("#reveal").click()
                assert "周末" in page.locator("#study-answer").inner_text()
                page.locator("#remember").click()
                page.wait_for_function(
                    "document.getElementById('word-count').textContent.includes('已掌握 1')"
                )
                page.locator("[data-tab=history]").click()
                page.wait_for_selector("#history-rows article")
                assert page.locator("#history-rows article").count() == 15
                page.once("dialog", lambda dialog: dialog.accept("Alice"))
                page.locator("#history-rows .speaker-name").first.click()
                page.wait_for_function(
                    "document.querySelector('#history-rows .speaker-name').textContent==='Alice'"
                )
                page.once("dialog", lambda dialog: dialog.accept("Bob"))
                page.locator("#history-rows .speaker-edit").first.click()
                page.wait_for_function(
                    "document.querySelector('#history-rows .speaker-name').textContent==='Bob'"
                )
                with page.expect_download() as info:
                    page.locator("#export-all").click()
                content = Path(info.value.path()).read_text(encoding="utf-8-sig")
                assert (
                    "我（麦克风）" in content
                    and "Alice" in content
                    and "Bob" in content
                )
                assert content.count("EN:") == 15
                page.locator("[data-tab=live]").click()
                page.screenshot(
                    path=str(root / ".tools" / "preview.png"), full_page=True
                )
                assert not errors, errors
                browser.close()
            assert store.words()[0]["mastered"] == 1
            print(
                "Browser checks passed: live, selection, lookup, saving, review, history, naming, full export."
            )
        finally:
            process.terminate()
            process.wait(timeout=10)
