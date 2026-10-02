"""Durable local transcripts and vocabulary; dates use China standard time."""

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from translation import ENGINE

CST = timezone(timedelta(hours=8))


class Store:
    def __init__(self, folder):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.path = self.folder / "subtitles.sqlite3"
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS transcripts (
                    id INTEGER PRIMARY KEY, date TEXT NOT NULL,
                    timestamp TEXT NOT NULL, en TEXT NOT NULL, zh TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS transcript_date ON transcripts(date,id);
                CREATE TABLE IF NOT EXISTS speaker_names (source TEXT PRIMARY KEY, name TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS words (
                    id INTEGER PRIMARY KEY, term TEXT NOT NULL,
                    normalized TEXT NOT NULL UNIQUE, zh TEXT NOT NULL,
                    context TEXT NOT NULL, created TEXT NOT NULL,
                    reviewed INTEGER NOT NULL DEFAULT 0,
                    mastered INTEGER NOT NULL DEFAULT 0);
            """)
            columns = {r["name"] for r in db.execute("PRAGMA table_info(transcripts)")}
            if "source" not in columns:
                db.execute(
                    "ALTER TABLE transcripts ADD COLUMN source TEXT NOT NULL DEFAULT 'output'"
                )
            if "translation_engine" not in columns:
                db.execute(
                    "ALTER TABLE transcripts ADD COLUMN translation_engine TEXT NOT NULL DEFAULT 'legacy_argos'"
                )

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def append(self, en, zh, source="output", timestamp=None):
        now = timestamp or datetime.now(CST)
        with self.connect() as db:
            cursor = db.execute(
                "INSERT INTO transcripts(date,timestamp,en,zh,source,translation_engine) VALUES(?,?,?,?,?,?)",
                (
                    now.date().isoformat(),
                    now.isoformat(timespec="seconds"),
                    en,
                    zh,
                    source,
                    ENGINE,
                ),
            )
            row = db.execute(
                "SELECT * FROM transcripts WHERE id=?", (cursor.lastrowid,)
            ).fetchone()
        return self.caption(row)

    def caption(self, row):
        result = dict(row)
        result["time"] = result["timestamp"][11:19]
        source = result["source"]
        result["speaker"] = (
            "我（麦克风）" if source == "microphone" else "对方（待确认）"
        )
        result["session"] = ""
        if source.startswith("remote:"):
            _, session, number = source.split(":")
            result["speaker"] = f"对方 {number}"
            result["session"] = session
        elif source.startswith("manual:"):
            result["session"] = source.split(":")[1]
        with self.connect() as db:
            name = db.execute(
                "SELECT name FROM speaker_names WHERE source=?", (source,)
            ).fetchone()
        if name:
            result["speaker"] = name["name"]
        return result

    def rename_speaker(self, source, name):
        with self.connect() as db:
            db.execute(
                "INSERT INTO speaker_names(source,name) VALUES(?,?) ON CONFLICT(source) DO UPDATE SET name=excluded.name",
                (source, name),
            )

    def reassign(self, transcript_id, name):
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM transcripts WHERE id=?", (transcript_id,)
            ).fetchone()
            if row is None:
                return None
            parts = row["source"].split(":")
            session = parts[1] if len(parts) == 3 else ""
            source = f"manual:{session}:{transcript_id}"
            db.execute(
                "UPDATE transcripts SET source=? WHERE id=?", (source, transcript_id)
            )
            db.execute(
                "INSERT INTO speaker_names(source,name) VALUES(?,?) ON CONFLICT(source) DO UPDATE SET name=excluded.name",
                (source, name),
            )
            updated = dict(row)
            updated["source"] = source
        return self.caption(updated)

    def export(self):
        yield "\ufeff完整双语对话（北京时间）\n\n"
        with self.connect() as db:
            for row in db.execute("SELECT * FROM transcripts ORDER BY timestamp,id"):
                item = self.caption(row)
                session = f"（会话 {item['session']}）" if item["session"] else ""
                yield f"[{item['date']} {item['time']}] {item['speaker']}{session}\nEN: {item['en']}\n中文: {item['zh']}\n\n"

    def recent(self, limit=12):
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM transcripts ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self.caption(x) for x in reversed(rows)]

    def dates(self):
        with self.connect() as db:
            return [
                dict(x)
                for x in db.execute(
                    "SELECT date,COUNT(*) AS count FROM transcripts GROUP BY date ORDER BY date DESC"
                )
            ]

    def history(self, date, before=None, limit=100):
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM transcripts WHERE date=? AND id<? ORDER BY id DESC LIMIT ?",
                (
                    date,
                    before if before is not None else 9223372036854775807,
                    limit + 1,
                ),
            ).fetchall()
        more = len(rows) > limit
        visible = rows[:limit]
        return {
            "rows": [self.caption(x) for x in reversed(visible)],
            "more": more,
            "before": visible[-1]["id"] if visible else None,
        }

    def save_word(self, term, zh, context):
        normalized = " ".join(term.casefold().split())
        now = datetime.now(CST).isoformat(timespec="seconds")
        with self.connect() as db:
            db.execute(
                """INSERT INTO words(term,normalized,zh,context,created) VALUES(?,?,?,?,?)
                ON CONFLICT(normalized) DO UPDATE SET zh=excluded.zh,context=excluded.context""",
                (term, normalized, zh, context, now),
            )
            return dict(
                db.execute(
                    "SELECT * FROM words WHERE normalized=?", (normalized,)
                ).fetchone()
            )

    def words(self):
        with self.connect() as db:
            return [dict(x) for x in db.execute("SELECT * FROM words ORDER BY id DESC")]

    def review(self, word_id, mastered):
        with self.connect() as db:
            cursor = db.execute(
                "UPDATE words SET reviewed=reviewed+1,mastered=? WHERE id=?",
                (int(mastered), word_id),
            )
            if not cursor.rowcount:
                return None
            return dict(
                db.execute("SELECT * FROM words WHERE id=?", (word_id,)).fetchone()
            )
