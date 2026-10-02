"""Exercise the actual Tk overlay with isolated audio/network state."""
import json
import queue
import time
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

import overlay


class OverlayTests(unittest.TestCase):
    def test_merge_highlight_follow_selection_and_save(self):
        inbox = queue.Queue()
        root = tk.Tk()
        requests = []

        class Worker:
            def __init__(self, target, **kwargs):
                self.target = target

            def start(self):
                if self.target.__name__ != "fetch":
                    self.target()

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def read(self):
                return json.dumps({"term": "Hello", "zh": "你好"}).encode()

        def urlopen(request, **kwargs):
            requests.append((request.full_url, json.loads(request.data)))
            return Response()

        def pump():
            deadline = time.monotonic() + .22
            while time.monotonic() < deadline:
                root.update()
                time.sleep(.01)

        def exercise():
            root.attributes("-topmost", False)
            root.geometry("480x340+0+0")
            text = next(w for w in root.winfo_children() if isinstance(w, tk.Text))
            chinese = next(w for w in root.winfo_children() if isinstance(w, tk.Text) and w is not text)
            bar = root.winfo_children()[0]
            follow = next(w for w in bar.winfo_children() if isinstance(w, tk.Button) and w.cget("text") == "跟随最新")

            def add(i, speaker="Other", en="Hello " * 12):
                inbox.put({"status": "Test", "rows": [{"id": i, "source": "remote:1", "speaker": speaker,
                    "timestamp": f"2026-10-02T12:00:{i:02d}", "time": "12:00", "en": en, "zh": "你好"}]})
                pump()

            add(1, en="Hello")
            old_tags = {t for t in text.tag_names("1.0") if t.startswith("fresh")}
            add(2, en="world")
            new_tags = {t for t in text.tag_names("1.6") if t.startswith("fresh")}
            self.assertTrue(old_tags and new_tags and old_tags.isdisjoint(new_tags))
            self.assertIn("Hello world", text.get("1.0", "end"))
            before = text.bbox("1.6")
            for tag in old_tags | new_tags:
                self.assertEqual(text.tag_cget(tag, "font"), "")
                text.tag_delete(tag)
            root.update()
            self.assertEqual(text.bbox("1.6"), before)
            inbox.put({"status": "Test", "rows": [], "updates": [{"id": 1, "zh": "第一条迟到的中文"}, {"id": 2, "zh": "第二条迟到的中文"}]})
            pump()
            self.assertIn("第一条迟到的中文", chinese.get("1.0", "end"))
            self.assertIn("第二条迟到的中文", chinese.get("1.0", "end"))
            self.assertEqual(text.bbox("1.6"), before)
            inbox.put({"status": "Test", "rows": [], "partials": [{"source": "output", "utterance": "a", "en": "Words before the pause", "speaker": "Other"}]})
            pump()
            self.assertIn("Words before the pause", text.get("1.0", "end"))
            inbox.put({"status": "Test", "rows": [], "partials": []})
            pump()
            self.assertNotIn("Words before the pause", text.get("1.0", "end"))
            inbox.put({"status":"Test", "rows":[], "partials":[{"source":"output", "utterance":"promote", "en":"Append here", "speaker":"Other"}]})
            pump()
            before_promote = text.bbox("1.0")
            self.assertIsNotNone(before_promote)
            inbox.put({"status":"Test", "rows":[{"id":3, "source":"remote:1", "speaker":"Other", "utterance":"promote", "capture_source":"output",
                "en":"Append here", "zh":"", "timestamp":"2026-10-02T12:00:03", "time":"12:00", "date":"2026-10-02"}], "partials":[]})
            pump()
            self.assertTrue(text.get("1.0", "end").startswith("Hello world Append here  12:00"))
            self.assertEqual(text.bbox("1.0"), before_promote)
            for i in range(4, 10):
                add(i, speaker=str(i))
            follow.invoke()
            for i in range(10, 13):
                add(i, speaker=str(i))
                self.assertGreaterEqual(text.yview()[1], .995)
            text.yview_moveto(0)
            text.event_generate("<MouseWheel>", delta=120)
            pump()
            add(13, speaker="13")
            self.assertLess(text.yview()[1], .99)
            text.tag_add("sel", "1.0", "1.5")
            text.event_generate("<ButtonRelease-1>", x=20, y=15)
            pump()
            popup = next(w for w in root.winfo_children() if isinstance(w, tk.Toplevel))
            translate = next(w for w in popup.winfo_children() if isinstance(w, tk.Button) and w.cget("text") == "单独翻译")
            save = next(w for w in popup.winfo_children() if isinstance(w, tk.Button) and w.cget("text") == "保存到生词本")
            self.assertEqual(save.cget("state"), "disabled")
            translate.invoke()
            pump()
            self.assertEqual(save.cget("state"), "normal")
            save.invoke()
            pump()
            self.assertEqual(requests[-1][1], {"term": "Hello", "zh": "你好", "context": "Hello world Append here"})
            follow.invoke()
            add(14, speaker="14")
            self.assertGreaterEqual(text.yview()[1], .995)
            root.destroy()

        try:
            with patch.object(overlay.tk, "Tk", return_value=root), patch.object(root, "mainloop", side_effect=exercise), \
                    patch.object(overlay.ctypes, "WinDLL", return_value=Mock()), patch.object(overlay.ctypes, "get_last_error", return_value=0), \
                    patch.object(overlay.queue, "Queue", return_value=inbox), patch.object(overlay.threading, "Thread", Worker), \
                    patch.object(overlay.urllib.request, "urlopen", side_effect=urlopen):
                overlay.main()
        finally:
            try:
                root.destroy()
            except tk.TclError:
                pass
