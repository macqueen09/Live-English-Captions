import unittest
from unittest.mock import Mock
from translation import ChineseTranslator, suspicious_output
import threading


class TranslationTests(unittest.TestCase):
    def test_rejects_private_use_and_wrong_script_without_erasing_them(self):
        self.assertTrue(suspicious_output("и\ue0f6獺", "I believe"))
        self.assertTrue(suspicious_output("你好\ufffd"))
        self.assertFalse(suspicious_output("我相信。"))
        self.assertFalse(suspicious_output("他使用 AI。"))
        self.assertFalse(suspicious_output("这个字符是 и", "The character is и"))

    def translator(self, results):
        translator = ChineseTranslator.__new__(ChineseTranslator)
        translator.lock = threading.RLock()
        translator.cache = {}
        translator.infer = Mock(side_effect=results)
        return translator

    def test_retries_and_caches_valid_translation(self):
        t = self.translator(["и\ue0f6獺", "我相信"])
        self.assertEqual(t.translate("I believe"), "我相信")
        self.assertEqual(t.translate("I believe"), "我相信")
        self.assertEqual(t.infer.call_count, 2)

    def test_unrecoverable_output_is_explicitly_marked(self):
        t = self.translator(["\ue0f6", "\ufffd"])
        self.assertEqual(t.translate("Hello"), "［译文异常，请参考英文原文］")
