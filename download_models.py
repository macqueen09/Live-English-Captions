from pathlib import Path
from huggingface_hub import snapshot_download
import urllib.request
from speakers import MODEL_NAME, MODEL_URL
from translation import MODEL_REPO, MODEL_DIR, MODEL_REVISION
from version import VERSION
from speech import MODEL_REPO as SPEECH_REPO, MODEL_DIR as SPEECH_DIR, MODEL_REVISION as SPEECH_REVISION

root = Path(__file__).resolve().parent
print("Downloading English speech recognition model...", flush=True)
snapshot_download(
    SPEECH_REPO,
    revision=SPEECH_REVISION,
    local_dir=root / "models" / SPEECH_DIR,
)
print("Downloading English to Chinese translation model...", flush=True)
snapshot_download(
    MODEL_REPO,
    revision=MODEL_REVISION,
    local_dir=root / "models" / MODEL_DIR,
    allow_patterns=[
        "model.bin",
        "config.json",
        "tokenizer.json",
        "tokenizer_config.json",
        "special_tokens_map.json",
        "sentencepiece.bpe.model",
        "shared_vocabulary.txt",
    ],
)
print("Models ready.", flush=True)
speaker_path = root / "models" / MODEL_NAME
if not speaker_path.exists():
    print("Downloading speaker recognition model...", flush=True)
    temporary = speaker_path.with_suffix(".part")
    urllib.request.urlretrieve(MODEL_URL, temporary)
    temporary.replace(speaker_path)
(root / "models" / ".ready").write_text(VERSION + "\n", encoding="utf-8")
