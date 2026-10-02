import tempfile
import unittest
from storage import Store


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.store = Store(self.folder.name)

    def tearDown(self):
        self.folder.cleanup()

    def test_transcripts_persist_and_paginate_without_gaps(self):
        for i in range(105):
            self.store.append(f"Sentence {i}", "中文")
        reopened = Store(self.folder.name)
        date = reopened.dates()[0]
        self.assertEqual(date["count"], 105)
        page = reopened.history(date["date"])
        older = reopened.history(date["date"], page["before"])
        ids = [r["id"] for r in older["rows"] + page["rows"]]
        self.assertEqual(ids, list(range(1, 106)))
        self.assertTrue(page["more"])
        self.assertFalse(older["more"])
        self.assertEqual(len(reopened.recent()), 12)
        self.assertTrue(page["rows"][0]["timestamp"].endswith("+08:00"))

    def test_words_deduplicate_and_review_persists(self):
        word = self.store.save_word(" Weekend ", "周末", "What about the weekend?")
        same = self.store.save_word("weekend", "周末时间", "This weekend.")
        self.assertEqual(word["id"], same["id"])
        self.assertEqual(len(self.store.words()), 1)
        self.store.review(word["id"], True)
        reopened = Store(self.folder.name)
        saved = reopened.words()[0]
        self.assertEqual(saved["reviewed"], 1)
        self.assertEqual(saved["mastered"], 1)
        self.assertEqual(saved["zh"], "周末时间")
        self.assertIsNone(reopened.review(999, False))

    def test_export_keeps_all_sources_and_manual_corrections(self):
        self.store.append("My sentence", "我的话", "microphone")
        other = self.store.append("Their sentence", "对方的话", "remote:abcdef12:2")
        self.assertEqual(other["speaker"], "对方 2")
        self.store.reassign(other["id"], "Alice")
        reopened = Store(self.folder.name)
        exported = "".join(reopened.export())
        self.assertIn("我（麦克风）", exported)
        self.assertIn("Alice", exported)
        self.assertIn("会话 abcdef12", exported)
        self.assertIn("My sentence", exported)
        self.assertIn("Their sentence", exported)
