"""Real offline-model regression: install models before running this script."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from translation import ChineseTranslator, MODEL_DIR, suspicious_output

translator = ChineseTranslator(
    Path(__file__).resolve().parents[1] / "models" / MODEL_DIR
)
examples = [("I believe", "相信"), ("I don't know.", "不知道"), ("weekend", "周末")]
for en, expected in examples:
    zh = translator.translate(en)
    assert expected in zh, (en, zh)
    assert not suspicious_output(zh, en)
text = "We're gonna bring the sensor. I believe I don't know. How is this guy typing that fast? Back sick. You sure he's not using AI? No, I don't think so."
zh = translator.translate(text)
assert not suspicious_output(zh, text)
assert "师曰" not in zh and "后病卧" not in zh
assert "传感器" in zh and "人工智能" in zh
context = [("My phone has no battery.", "我的手机没电了。")]
zh = translator.translate("Can I charge it here?", context=context)
assert "充电" in zh, zh
assert "我的手机没电了" not in zh, zh
assert not suspicious_output(zh)
print(
    "Real model checks passed: short fragments, Chinese vocabulary and reported example."
)
