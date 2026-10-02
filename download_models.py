from pathlib import Path
from huggingface_hub import snapshot_download
import argostranslate.package
import urllib.request
from speakers import MODEL_NAME, MODEL_URL

root = Path(__file__).resolve().parent
print("Downloading English speech recognition model...", flush=True)
snapshot_download(
    "Systran/faster-whisper-base.en", local_dir=root / "models" / "whisper-base.en"
)
print("Downloading English to Chinese translation model...", flush=True)
installed = argostranslate.package.get_installed_packages()
if not any(p.from_code == "en" and p.to_code == "zh" for p in installed):
    argostranslate.package.update_package_index()
    package = next(
        p
        for p in argostranslate.package.get_available_packages()
        if p.from_code == "en" and p.to_code == "zh"
    )
    argostranslate.package.install_from_path(package.download())
print("Models ready.", flush=True)
speaker_path = root / "models" / MODEL_NAME
if not speaker_path.exists():
    print("Downloading speaker recognition model...", flush=True)
    temporary = speaker_path.with_suffix(".part")
    urllib.request.urlretrieve(MODEL_URL, temporary)
    temporary.replace(speaker_path)
(root / "models" / ".ready").write_text(
    "English to Chinese + speakers v2\n", encoding="utf-8"
)
