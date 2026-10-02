"""Re-translate legacy captions after an atomic SQLite backup; never change English."""

import sqlite3
from datetime import datetime
from pathlib import Path
from storage import Store
from translation import ChineseTranslator, MODEL_DIR, ENGINE

root = Path(__file__).resolve().parent
store = Store(root / "data")
with store.connect() as db:
    legacy = [
        dict(row)
        for row in db.execute(
            "SELECT id,en,zh FROM transcripts WHERE translation_engine='legacy_argos' ORDER BY id"
        )
    ]
if not legacy:
    print("No legacy captions to repair.")
else:
    backups = root / "data" / "backups"
    backups.mkdir(exist_ok=True)
    path = backups / (
        "before-1.2.0-" + datetime.now().strftime("%Y%m%d-%H%M%S") + ".sqlite3"
    )
    with sqlite3.connect(store.path) as source, sqlite3.connect(path) as destination:
        source.backup(destination)
    translator = ChineseTranslator(root / "models" / MODEL_DIR)
    for index, row in enumerate(legacy, 1):
        zh = translator.translate(row["en"])
        with store.connect() as db:
            db.execute(
                "UPDATE transcripts SET zh=?,translation_engine=? WHERE id=? AND zh=?",
                (zh, ENGINE, row["id"], row["zh"]),
            )
        if index % 25 == 0:
            print(f"Repaired {index}/{len(legacy)}", flush=True)
    print(f"Repaired {len(legacy)} captions. Original database preserved at {path}")
