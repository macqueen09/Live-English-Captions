import unittest
from streaming import StableEnglish, reconcile_groups
from caption_layout import LiveParagraphs


class StreamingTests(unittest.TestCase):
    def test_agreement_freezes_prefix_and_revises_tail(self):
        stream = StableEnglish(tail_words=3)
        stream.update("I believe we should meet beside the main door")
        first = stream.update("I believe we should meet beside the main door")
        self.assertEqual(first["stable_en"], "I believe we should meet beside")
        updated = stream.update("I think we should meet beside the side door")
        self.assertEqual(updated["en"], "I believe we should meet beside the side door")
        final = stream.update("I think we should meet beside the side door tomorrow", final=True)
        self.assertTrue(final["en"].startswith(first["stable_en"]))
        self.assertTrue(final["en"].endswith("tomorrow"))

    def test_unaligned_candidate_does_not_destroy_confirmed_text(self):
        stream = StableEnglish(tail_words=2)
        stream.update("These are the words that we already read")
        before = stream.update("These are the words that we already read")
        after = stream.update("Something unrelated and different")
        self.assertEqual(before["en"], after["en"])

    def test_short_unconfirmed_tail_can_delete_words(self):
        stream = StableEnglish()
        stream.update("We can can go tomorrow")
        self.assertEqual(stream.update("We can go tomorrow")["en"], "We can go tomorrow")

    def test_spelling_expansion_keeps_speaker_boundaries(self):
        groups = [{"text":"We're gonna meet", "source":"one", "offset":0},
                  {"text":"Yes I agree", "source":"two", "offset":2}]
        revised = reconcile_groups(groups, "We are gonna meet Yes I agree")
        self.assertEqual(revised[0]["text"], "We are gonna meet")
        self.assertEqual(revised[1]["text"], "Yes I agree")
        self.assertEqual([g["source"] for g in revised], ["one", "two"])


class LayoutTests(unittest.TestCase):
    def row(self, row_id, text, source="microphone", token=None):
        return {"id":row_id, "en":text, "zh":"", "speaker":source, "source":source,
                "capture_source":"microphone" if source=="microphone" else "output", "utterance":token,
                "timestamp":f"2026-10-02T12:00:{row_id:02d}+08:00", "time":"12:00", "date":"2026-10-02"}

    def test_preview_appends_then_promotes_in_same_paragraph(self):
        layout = LiveParagraphs()
        row = self.row(1, "Earlier words.")
        first = layout.apply([row], [])
        key = first[0]["key"]
        preview = {"utterance":"next", "source":"microphone", "speaker":"Me", "en":"New words"}
        before = layout.apply([row], [preview])
        self.assertEqual(len(before), 1)
        self.assertEqual(before[0]["en"], "Earlier words. New words")
        final = self.row(2, "New words", token="next")
        after = layout.apply([row, final], [])
        self.assertEqual(after[0]["key"], key)
        self.assertEqual(after[0]["en"], before[0]["en"])
        self.assertFalse(after[0]["pending"])

    def test_confirmed_person_change_splits_only_new_fragment(self):
        layout = LiveParagraphs()
        row = self.row(1, "Person one.", "remote:session:1")
        layout.apply([row], [])
        preview = {"utterance":"next", "source":"output", "speaker":"Other", "en":"Person two."}
        layout.apply([row], [preview])
        final = self.row(2, "Person two.", "remote:session:2", "next")
        after = layout.apply([row, final], [])
        self.assertEqual([p["en"] for p in after], ["Person one.", "Person two."])
