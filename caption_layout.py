"""Stable live paragraph identities shared by the browser and native overlay."""
from collections import defaultdict
from datetime import datetime


def capture_source(row):
    return row.get("capture_source") or ("microphone" if row["source"] == "microphone" else "output")


class LiveParagraphs:
    def __init__(self):
        self.blocks = []
        self.counter = 0
        self.last_id = 0

    def new_block(self, source=None, speaker="对方（实时预览）", capture="output", row=None):
        self.counter += 1
        row = row or {}
        return {"key": str(self.counter), "source": source, "speaker": speaker, "capture_source": capture,
                "time": row.get("time", ""), "date": row.get("date", ""),
                "timestamp": row.get("timestamp", ""), "fragments": [], "rows": []}

    def find(self, token):
        for block in self.blocks:
            for fragment in block["fragments"]:
                if fragment["key"] == token:
                    return block, fragment
        return None, None

    def append_row(self, row, index=None):
        last = self.blocks[index - 1] if index is not None and index > 0 else (self.blocks[-1] if index is None and self.blocks else None)
        gap = 999
        if last and last["timestamp"] and row.get("timestamp"):
            gap = (datetime.fromisoformat(row["timestamp"]) - datetime.fromisoformat(last["timestamp"])).total_seconds()
        if not (last and last["source"] == row["source"] and last["speaker"] == row["speaker"] and
                0 <= gap <= 12 and len(self.text(last)) + len(row["en"]) < 380):
            last = self.new_block(row["source"], row["speaker"], capture_source(row), row)
            if index is None:
                self.blocks.append(last)
            else:
                self.blocks.insert(index, last)
        last["fragments"].append({"key": f"row:{row['id']}", "en": row["en"], "pending": False})
        last["rows"].append(row)
        last["timestamp"] = row["timestamp"]
        return self.blocks.index(last) + 1

    @staticmethod
    def text(block):
        return " ".join(fragment["en"] for fragment in block["fragments"] if fragment["en"])

    def apply(self, rows, partials):
        new_groups = defaultdict(list)
        for row in rows:
            if row["id"] > self.last_id:
                new_groups[row.get("utterance") or f"row:{row['id']}"].append(row)
        for token, group in new_groups.items():
            block, fragment = self.find(token)
            same_person = all(row["source"] == group[0]["source"] and row["speaker"] == group[0]["speaker"] for row in group)
            if fragment and same_person and (block["source"] is None or block["source"] == group[0]["source"]):
                fragment.update(en=" ".join(row["en"] for row in group), pending=False)
                block["rows"].extend(group)
                block.update(source=group[0]["source"], speaker=group[0]["speaker"], timestamp=group[-1]["timestamp"])
                if not block["time"]:
                    block.update(time=group[0]["time"], date=group[0]["date"])
            else:
                index = None
                if fragment:
                    block["fragments"].remove(fragment)
                    index = self.blocks.index(block) + 1
                    if not block["fragments"]:
                        self.blocks.remove(block)
                        index -= 1
                for row in group:
                    index = self.append_row(row, index)
        if rows:
            self.last_id = max(self.last_id, max(row["id"] for row in rows))
        # Translation/speaker updates do not reconstruct English fragments.
        replacements = {row["id"]: row for row in rows}
        for block in self.blocks:
            block["rows"] = [dict(row, **replacements.get(row["id"], {})) for row in block["rows"]]
            if block["rows"]:
                block["source"] = block["rows"][0]["source"]
                block["speaker"] = block["rows"][0]["speaker"]
        active = {preview["utterance"] for preview in partials}
        for block in list(self.blocks):
            block["fragments"] = [fragment for fragment in block["fragments"] if not fragment["pending"] or fragment["key"] in active]
            if not block["fragments"]:
                self.blocks.remove(block)
        for preview in partials:
            block, fragment = self.find(preview["utterance"])
            if fragment is None:
                last = self.blocks[-1] if self.blocks else None
                if last and last["capture_source"] == preview["source"] and len(self.text(last)) < 380:
                    block = last
                else:
                    block = self.new_block(speaker=preview["speaker"], capture=preview["source"], row=preview)
                    self.blocks.append(block)
                fragment = {"key": preview["utterance"], "en": "", "pending": True}
                block["fragments"].append(fragment)
            fragment["en"] = preview["en"]
        self.blocks = self.blocks[-100:]
        return [{key: value for key, value in block.items() if key != "fragments"} |
                {"en": self.text(block), "pending": any(f["pending"] for f in block["fragments"])} for block in self.blocks]
