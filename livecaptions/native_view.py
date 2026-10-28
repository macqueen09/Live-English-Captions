"""Incremental Tk paragraph rendering; Chinese never participates in English layout."""


class NativeParagraphs:
    def __init__(self, widget, fresh):
        self.widget = widget
        self.fresh = fresh
        self.blocks = {}

    def sync(self, paragraphs):
        text = self.widget
        keys = {p["key"] for p in paragraphs}
        oldest = min((int(key) for key in keys), default=0)
        for key in list(self.blocks):
            if key not in keys and int(key) >= oldest:
                block = self.blocks.pop(key)
                text.delete(block["start"], block["end"])
                for name in ("start", "en_end", "meta_start", "end"):
                    text.mark_unset(block[name])
        for index, paragraph in enumerate(paragraphs):
            key = paragraph["key"]
            english = paragraph["en"]
            meta = f"  {paragraph['time']} · {paragraph['speaker']}"
            block = self.blocks.get(key)
            if block is None:
                next_block = next((self.blocks[p["key"]] for p in paragraphs[index+1:] if p["key"] in self.blocks), None)
                at = text.index(next_block["start"] if next_block else "end-1c")
                block = {name: f"paragraph_{name}_{key}" for name in ("start", "en_end", "meta_start", "end")}
                text.mark_set(block["start"], at)
                text.mark_gravity(block["start"], "left")
                self.fresh(at, english, "en")
                after_english = text.index(f"{at}+{len(english)}c")
                text.insert(after_english, meta + "\n", "meta")
                text.mark_set(block["en_end"], after_english)
                text.mark_gravity(block["en_end"], "left")
                text.mark_set(block["meta_start"], after_english)
                text.mark_gravity(block["meta_start"], "right")
                text.mark_set(block["end"], f"{at}+{len(english + meta) + 1}c")
                text.mark_gravity(block["end"], "left")
                text.mark_gravity(block["start"], "right")
                block.update(en=english, meta=meta)
                self.blocks[key] = block
                continue
            if english != block["en"]:
                before = block["en"]
                common = 0
                while common < min(len(before), len(english)) and before[common] == english[common]:
                    common += 1
                at = text.index(block["start"])
                suffix = text.index(f"{at}+{common}c")
                selection = text.tag_ranges("sel")
                editing_selected = (selection and text.compare(selection[0], "<", block["en_end"]) and
                                    text.compare(selection[1], ">", suffix))
                if not editing_selected:
                    text.delete(suffix, block["en_end"])
                    self.fresh(suffix, english[common:], "en")
                    text.mark_set(block["start"], at)
                    text.mark_set(block["en_end"], f"{at}+{len(english)}c")
                    block["en"] = english
            if meta != block["meta"]:
                at = text.index(block["meta_start"])
                text.delete(block["meta_start"], f"{block['end']}-1c")
                text.insert(at, meta, "meta")
                text.mark_set(block["meta_start"], at)
                block["meta"] = meta


class NativeChinese:
    def __init__(self, widget, fresh):
        self.widget = widget
        self.fresh = fresh
        self.rows = {}
        self.rendered = {}

    def sync(self, rows, follow=True):
        for row in rows:
            self.rows[row["id"]] = dict(self.rows.get(row["id"], {}), **row)
        shown = [row for row in sorted(self.rows.values(), key=lambda r:r["id"])
                 if not row.get("translation_group") or row["translation_group"] == row["id"]][-16:]
        ids = {row["id"] for row in shown}
        text = self.widget
        position = text.index("@0,0")
        text.configure(state="normal")
        for row_id in list(self.rendered):
            if row_id not in ids:
                start, end, _ = self.rendered.pop(row_id)
                text.delete(start, end)
                text.mark_unset(start, end)
        for row in shown:
            row_id = row["id"]
            value = row["zh"] or "中文稍后补充…"
            previous = self.rendered.get(row_id)
            if previous and previous[2] == value:
                continue
            if previous:
                start, end, _ = previous
                at = text.index(start)
                text.delete(start, end)
            else:
                start, end = f"chinese_start_{row_id}", f"chinese_end_{row_id}"
                following = next((self.rendered[r["id"]][0] for r in shown if r["id"] > row_id and r["id"] in self.rendered), None)
                at = text.index(following or "end-1c")
                text.mark_set(start, at)
            text.mark_gravity(start, "left")
            if row["zh"]:
                self.fresh(at, value, "zh", widget=text)
            else:
                text.insert(at, value, "zh")
            meta = f"  {row['time']} · {row['speaker']}\n"
            text.insert(f"{at}+{len(value)}c", meta, "meta")
            text.mark_set(end, f"{at}+{len(value + meta)}c")
            text.mark_gravity(end, "left")
            text.mark_gravity(start, "right")
            self.rendered[row_id] = (start, end, value)
        text.configure(state="disabled")
        text.see("end") if follow else text.yview(position)
        if self.rows:
            floor = min(ids, default=max(self.rows))
            self.rows = {row_id: row for row_id, row in self.rows.items() if row_id >= floor}
