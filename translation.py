"""Offline NLLB English → Simplified Chinese, with explicit language tokens."""

import threading
import unicodedata
from pathlib import Path
from inference import AdaptiveModel

MODEL_REPO = "JustFrederik/nllb-200-distilled-600M-ct2-int8"
MODEL_DIR = "nllb-600m-int8"
MODEL_REVISION = "302d78f00e6fdb50a1064059df7c392b735e9d05"
ENGINE = "nllb-600m-int8-v1"


def suspicious_output(text, source=""):
    if not text.strip():
        return True
    for char in text:
        category = unicodedata.category(char)
        if category in {"Co", "Cs", "Cn"} or char == "\ufffd":
            return True
        if category == "Cc" and char not in "\n\r\t":
            return True
        if category.startswith("L") and char not in source:
            name = unicodedata.name(char, "")
            if not any(script in name for script in ("LATIN", "CJK", "IDEOGRAPH")):
                return True
    return False


class ChineseTranslator:
    def __init__(self, directory, on_change=None):
        import ctranslate2
        from tokenizers import Tokenizer

        directory = Path(directory)
        if not (directory / "model.bin").exists():
            raise RuntimeError("NLLB 翻译模型未安装，请运行 setup.ps1 更新。")
        self.tokenizer = Tokenizer.from_file(str(directory / "tokenizer.json"))
        self.runtime = AdaptiveModel(
            lambda device, compute: ctranslate2.Translator(
                str(directory), device=device, compute_type=compute,
                inter_threads=1, intra_threads=4,
            ), on_change=on_change,
        )
        self.lock = threading.RLock()
        self.cache = {}

    def infer(self, text, beam=4, context=()):
        # The converted tokenizer's default postprocessor contains <unk> as its
        # source language. Never use it: supply explicit English and Chinese tags.
        tokens = self.tokenizer.encode(text, add_special_tokens=False).tokens
        if len(tokens) > 480:
            # Split long pasted text without silently truncating any source words.
            middle = len(text) // 2
            split = text.rfind(" ", 0, middle) or middle
            if split <= 0:
                split = middle
            return self.translate(text[:split]) + " " + self.translate(text[split:])
        # Short source context and its already-confirmed translation form a forced
        # target prefix. Decode only the new suffix; no delimiter guessing or LLM instructions.
        context_tokens, prefix_tokens = [], []
        for english, chinese in reversed(context[-2:]):
            source_piece = self.tokenizer.encode(english + " ", add_special_tokens=False).tokens
            target_piece = self.tokenizer.encode(chinese + " ", add_special_tokens=False).tokens
            if len(source_piece) + len(context_tokens) + len(tokens) > 440 or len(target_piece) + len(prefix_tokens) > 180:
                break
            context_tokens = source_piece + context_tokens
            prefix_tokens = target_piece + prefix_tokens
        source = ["eng_Latn", *context_tokens, *tokens, "</s>"]
        target_prefix = ["zho_Hans", *prefix_tokens]
        result = self.runtime.run(lambda model: model.translate_batch(
            [source],
            target_prefix=[target_prefix],
            beam_size=beam,
            max_decoding_length=512,
            repetition_penalty=1.1,
            return_scores=True,
        )[0])
        target = result.hypotheses[0]
        if prefix_tokens:
            if target[:len(target_prefix)] != target_prefix:
                return self.infer(text, beam=beam)
            target = target[len(target_prefix):]
        ids = [self.tokenizer.token_to_id(token) for token in target]
        if any(token is None for token in ids):
            raise RuntimeError("翻译模型词表不一致，请重新安装模型。")
        translated = unicodedata.normalize(
            "NFC", self.tokenizer.decode(ids, skip_special_tokens=True)
        ).strip()
        if prefix_tokens and (not translated or suspicious_output(translated, text)):
            return self.infer(text, beam=beam)
        return translated

    def translate(self, text, context=()):
        text = unicodedata.normalize("NFC", text).strip()
        if not text:
            return ""
        with self.lock:
            context = tuple((en, zh) for en, zh in context[-2:] if zh and not suspicious_output(zh, en) and not zh.startswith("［"))
            key = (text, context)
            if key in self.cache:
                return self.cache[key]
            translated = self.infer(text, context=context)
            if suspicious_output(translated, text):
                translated = self.infer(text, beam=6, context=context)
            if suspicious_output(translated, text):
                # Do not erase invalid characters and disguise broken output as a translation.
                translated = "［译文异常，请参考英文原文］"
            if len(self.cache) >= 500:
                self.cache.pop(next(iter(self.cache)))
            self.cache[key] = translated
            return translated
