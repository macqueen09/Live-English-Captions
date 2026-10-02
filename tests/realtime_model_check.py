"""Optional real GPU/CPU benchmark and paced audio pipeline check; temporary database."""
import json
import math
from pathlib import Path
import sys
import tempfile
import threading
import time
import wave
from unittest.mock import MagicMock, patch

import numpy as np
from scipy.signal import resample_poly

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from inference import configure_cuda_libraries
configure_cuda_libraries()
from faster_whisper import WhisperModel
from translation import ChineseTranslator, suspicious_output
from speech import MODEL_DIR as SPEECH_DIR
import app

with wave.open(str(ROOT / ".tools" / "sample.wav")) as audio:
    rate = audio.getframerate()
    clip = np.frombuffer(audio.readframes(audio.getnframes()), dtype=np.int16).astype(np.float32) / 32768
divisor = math.gcd(rate, 16000)
clip = resample_poly(clip, 16000 // divisor, rate // divisor).astype(np.float32)

with tempfile.TemporaryDirectory() as directory, patch.object(app, "store", app.Store(directory)):
    service = app.Service()
    service.load_models()
    assert service.asr_runtime.label == "GPU", service.asr_runtime.reason
    gpu = service.model
    cpu = WhisperModel(str(ROOT / "models" / SPEECH_DIR), device="cpu", compute_type="int8")
    times = {}
    for mode, model in (("GPU", gpu), ("CPU", cpu)):
        list(model.transcribe(clip, language="en", beam_size=1, vad_filter=True)[0])
        durations = []
        for _ in range(3):
            started = time.perf_counter()
            result = list(model.transcribe(clip, language="en", beam_size=1, vad_filter=True)[0])
            durations.append(time.perf_counter() - started)
        times[mode] = round(float(np.median(durations)), 3)
    translator = ChineseTranslator(ROOT / "models" / "nllb-600m-int8")
    chinese = translator.translate("I believe we can make the captions faster.")
    assert translator.runtime.label == "GPU", translator.runtime.reason
    assert not suspicious_output(chinese)

    translated = threading.Event()
    release = threading.Event()

    def slow_translate(text, context=()):
        translated.set()
        release.wait(timeout=10)
        return translator.translate(text, context=context)

    stream = MagicMock()
    blocks = [clip[index:index+1600] for index in range(0, len(clip), 1600)]
    blocks += [np.zeros(1600, dtype=np.float32)] * 8
    position = 0

    def read(*args, **kwargs):
        global position
        time.sleep(.1)
        if position >= len(blocks):
            service.stop.set()
            return np.zeros(1600, dtype=np.float32).tobytes()
        block = blocks[position]
        position += 1
        return np.pad(block, (0, 1600-len(block))).tobytes()

    stream.read.side_effect = read
    host = MagicMock()
    host.__enter__.return_value = host
    host.get_device_info_by_index.return_value = {"defaultSampleRate": 16000, "maxInputChannels": 1}
    host.open.return_value.__enter__.return_value = stream
    first_preview = None
    preview_updates = 0
    previous = ""
    started = time.perf_counter()
    with patch.object(app, "AudioHost", return_value=host), patch.object(service, "translate", side_effect=slow_translate):
        service.thread = threading.Thread(target=service.run, args=(1, 2))
        # Test only mic: avoid two simulated streams consuming the same sample.
        # Output remains silent while microphone receives the paced English sample.
        def info(device):
            return {"isLoopbackDevice": device == 1, "defaultSampleRate": 16000, "maxInputChannels": 1}
        host.get_device_info_by_index.side_effect = info
        silent = MagicMock()
        def silent_read(*args, **kwargs):
            time.sleep(.1)
            return np.zeros(1600, dtype=np.float32).tobytes()
        silent.read.side_effect = silent_read
        def open_stream(**kwargs):
            context = MagicMock()
            context.__enter__.return_value = stream if kwargs["input_device_index"] == 2 else silent
            return context
        host.open.side_effect = open_stream
        service.thread.start()
        while service.thread.is_alive() and time.perf_counter() - started < 20:
            with service.lock:
                text = service.previews.get("microphone", {}).get("en", "")
            if text and text != previous:
                preview_updates += 1
                previous = text
                if first_preview is None:
                    first_preview = round(time.perf_counter() - started, 3)
            time.sleep(.02)
        service.stop.set()
        service.thread.join(timeout=5)
        assert not service.error, service.error
        assert first_preview is not None and preview_updates >= 2, (first_preview, preview_updates)
        assert translated.wait(timeout=3)
        rows = app.store.recent()
        assert rows and rows[0]["en"] and rows[0]["zh"] == "", rows
        english_before_translation = round(time.perf_counter() - started, 3)
        release.set()
        service.translation_jobs.join()
        rows = app.store.recent()
        assert rows[0]["zh"] and rows[0]["source"] == "microphone"
    print(json.dumps({"asr_median_seconds": times, "gpu_translation": chinese,
        "first_preview_seconds": first_preview, "preview_updates": preview_updates,
        "final_english_before_chinese_seconds": english_before_translation,
        "final_english": rows[0]["en"]}, ensure_ascii=True))
