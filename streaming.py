"""Local agreement: freeze reliable words while keeping a short editable tail."""
import re
from difflib import SequenceMatcher


def normalized(words):
    return [re.sub(r"(^\W+|\W+$)", "", word).casefold() for word in words]


class StableEnglish:
    def __init__(self, tail_words=6):
        self.tail_words = tail_words
        self.stable = []
        self.previous = []

    def align(self, words):
        if not self.stable:
            return words
        fixed, incoming = normalized(self.stable), normalized(words)
        if incoming[:len(fixed)] == fixed:
            return self.stable + words[len(fixed):]
        # Acoustic re-decoding may change an earlier word. Anchor at the end of
        # the already-confirmed prefix; never replace words the reader has read.
        blocks = SequenceMatcher(None, fixed, incoming, autojunk=False).get_matching_blocks()
        anchors = [block for block in blocks if block.a + block.size == len(fixed) and block.size >= min(2, len(fixed))]
        if anchors:
            anchor = anchors[-1]
            return self.stable + words[anchor.b + anchor.size:]
        # No reliable alignment: keep the last safe hypothesis instead of duplicating it.
        return self.previous or self.stable

    def update(self, hypothesis, final=False):
        words = self.align(hypothesis.split())
        if not final:
            common = 0
            old, new = normalized(self.previous), normalized(words)
            while common < min(len(old), len(new)) and old[common] == new[common]:
                common += 1
            confirmed = max(len(self.stable), min(common, max(0, len(words) - self.tail_words)))
            self.stable = words[:confirmed]
        self.previous = words
        return {"en": " ".join(words), "stable_en": " ".join(self.stable),
                "tail_en": " ".join(words[len(self.stable):])}


def reconcile_groups(groups, text):
    """Keep acoustic speaker boundaries when a frozen spelling changes word count."""
    words, labels = [], []
    for group in groups:
        piece = group["text"].split()
        words.extend(piece)
        labels.extend((group["source"], group["offset"]) for _ in piece)
    corrected = text.split()
    if not words or words == corrected:
        return groups
    aligned = []
    for kind, left, right, start, end in SequenceMatcher(None, normalized(words), normalized(corrected), autojunk=False).get_opcodes():
        for index in range(start, end):
            source_index = left + (index - start if kind == "equal" else
                                   int((index - start) * max(1, right - left) / max(1, end - start)))
            source_index = min(source_index, len(labels) - 1)
            aligned.append((corrected[index], *labels[source_index]))
    result = []
    for word, source, offset in aligned:
        if result and result[-1]["source"] == source:
            result[-1]["text"] += " " + word
        else:
            result.append({"text": word, "source": source, "offset": offset})
    return result
