"""Local-only Windows playback subtitles."""

import math
import os
import subprocess
import sys
import queue
import threading
from collections import deque
from pathlib import Path

import numpy as np
import pyaudiowpatch as pa
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from scipy.signal import resample_poly
from storage import Store, CST
from datetime import datetime
from datetime import timedelta
from uuid import uuid4
from speakers import VoiceTracker, MODEL_NAME
from translation import ChineseTranslator, MODEL_DIR, ENGINE
from version import VERSION

ROOT = Path(__file__).resolve().parent
app = FastAPI(title="Live English Captions", version=VERSION)
overlay_process = None
overlay_lock = threading.Lock()


@app.post("/api/overlay")
def open_overlay():
    global overlay_process
    with overlay_lock:
        if overlay_process is None or overlay_process.poll() is not None:
            with (ROOT / "data" / "overlay.log").open("a", encoding="utf-8") as log:
                overlay_process = subprocess.Popen(
                    [sys.executable, str(ROOT / "overlay.py")],
                    cwd=ROOT,
                    stdout=log,
                    stderr=log,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
    return {"ok": True}


store = Store(os.environ.get("SUBTITLES_DATA_DIR", ROOT / "data"))

# PortAudio initialization/termination is not safe across concurrent HTTP threads.
audio_lock = threading.RLock()
audio_instance = None


class AudioHost:
    def __init__(self, refresh=False):
        self.refresh = refresh

    def __enter__(self):
        global audio_instance
        with audio_lock:
            if (
                self.refresh
                and audio_instance is not None
                and not (service.thread and service.thread.is_alive())
            ):
                audio_instance.terminate()
                audio_instance = None
            if audio_instance is None:
                audio_instance = pa.PyAudio()
        return self

    def __exit__(self, *args):
        # Keep one host alive for the lifetime of the service.
        pass

    def __getattr__(self, name):
        def call(*args, **kwargs):
            with audio_lock:
                return getattr(audio_instance, name)(*args, **kwargs)

        return call


class StartRequest(BaseModel):
    device: int
    microphone: int | None = None


class Service:
    def __init__(self):
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.thread = None
        self.status = "尚未开始"
        self.error = ""
        self.level = 0.0
        self.mic_level = 0.0
        self.rows = deque(maxlen=200)
        self.sequence = 0
        self.model = None
        self.translator = None
        self.translation_lock = threading.RLock()
        self.tracker = None
        self.rows.extend(store.recent())
        self.sequence = self.rows[-1]["id"] if self.rows else 0

    def emit(self, english, chinese, source="output", timestamp=None):
        with self.lock:
            row = store.append(english, chinese, source, timestamp)
            self.sequence = row["id"]
            self.rows.append(row)

    def translate(self, text):
        with self.translation_lock:
            if self.translator is None:
                self.translator = ChineseTranslator(ROOT / "models" / MODEL_DIR)
            return self.translator.translate(text)

    def load_models(self):
        from faster_whisper import WhisperModel

        self.status = "正在加载离线模型…"
        if self.model is None:
            model_path = ROOT / "models" / "whisper-base.en"
            if not (model_path / "model.bin").exists():
                raise RuntimeError("语音模型未安装，请先运行 setup.ps1。")
            self.model = WhisperModel(
                str(model_path), device="cpu", compute_type="int8"
            )
        self.translate("Hello")

    def run(self, device, microphone=None):
        chunks = queue.Queue(maxsize=64)
        capture_error = []
        capture_threads = []

        def capture(input_device, source):
            try:
                with AudioHost() as audio:
                    info = audio.get_device_info_by_index(input_device)
                    if source == "output" and not info.get("isLoopbackDevice"):
                        raise RuntimeError("请选择播放设备的回环输入。")
                    rate = int(info["defaultSampleRate"])
                    channels = int(info["maxInputChannels"])
                    block = int(rate * 0.1)
                    with audio.open(
                        format=pa.paFloat32,
                        channels=channels,
                        rate=rate,
                        input=True,
                        input_device_index=input_device,
                        frames_per_buffer=block,
                    ) as stream:
                        frames, silence, duration = [], 0, 0
                        started = None
                        preroll = deque(maxlen=3)

                        def enqueue():
                            clip = np.concatenate(frames)
                            divisor = math.gcd(rate, 16000)
                            clip = resample_poly(
                                clip, 16000 // divisor, rate // divisor
                            ).astype(np.float32)
                            try:
                                chunks.put_nowait((clip, source, started))
                            except queue.Full:
                                raise RuntimeError(
                                    "处理速度跟不上，音频积压已满，已停止捕获。请缩短通话或改用更快模型。"
                                )

                        while not self.stop.is_set():
                            data = stream.read(block, exception_on_overflow=False)
                            mono = (
                                np.frombuffer(data, dtype=np.float32)
                                .reshape(-1, channels)
                                .mean(axis=1)
                            )
                            level = float(np.sqrt(np.mean(mono * mono)))
                            if source == "microphone":
                                self.mic_level = level
                            else:
                                self.level = level
                            voiced = level > 0.004
                            if not frames:
                                if not voiced:
                                    preroll.append(mono)
                                    continue
                                frames.extend(preroll)
                                preroll.clear()
                                started = datetime.now(CST)
                            frames.append(mono)
                            duration += 0.1
                            silence = 0 if voiced else silence + 0.1
                            if (silence >= 0.6 and duration >= 0.6) or duration >= 7:
                                enqueue()
                                frames, silence, duration = [], 0, 0
                        if frames and duration >= 0.3:
                            enqueue()
            except Exception as exc:
                capture_error.append(
                    f"{'麦克风' if source == 'microphone' else '耳机'}：{exc}"
                )
                self.stop.set()

        try:
            self.load_models()
            if self.stop.is_set():
                return
            self.tracker = VoiceTracker(ROOT / "models" / MODEL_NAME, uuid4().hex[:8])
            listening = (
                "正在监听耳机和麦克风"
                if microphone is not None
                else "正在监听耳机播放音频"
            )
            self.status = listening
            sources = [(device, "output")]
            if microphone is not None:
                sources.append((microphone, "microphone"))
            for input_device, source in sources:
                thread = threading.Thread(
                    target=capture, args=(input_device, source), daemon=True
                )
                capture_threads.append(thread)
                thread.start()
            while (
                not self.stop.is_set()
                or any(t.is_alive() for t in capture_threads)
                or not chunks.empty()
            ):
                try:
                    clip, source, timestamp = chunks.get(timeout=0.2)
                except queue.Empty:
                    continue
                self.status = (
                    "停止捕获，正在保存剩余对话…"
                    if self.stop.is_set()
                    else "正在识别和翻译…"
                )
                segments, _ = self.model.transcribe(
                    clip,
                    language="en",
                    beam_size=1,
                    vad_filter=True,
                    condition_on_previous_text=False,
                    word_timestamps=True,
                )
                segments = list(segments)
                if source == "microphone":
                    text = " ".join(
                        s.text.strip() for s in segments if s.no_speech_prob < 0.6
                    ).strip()
                    if text:
                        self.emit(text, self.translate(text), source, timestamp)
                else:
                    for group in self.tracker.label_segments(clip, segments):
                        if group["text"]:
                            self.emit(
                                group["text"],
                                self.translate(group["text"]),
                                group["source"],
                                timestamp + timedelta(seconds=group["offset"]),
                            )
                if not self.stop.is_set():
                    self.status = listening
        except Exception as exc:
            self.error = str(exc)
        finally:
            self.stop.set()
            for thread in capture_threads:
                thread.join(timeout=3)
            if capture_error:
                self.error = capture_error[0]
            self.level = 0
            self.mic_level = 0
            self.status = "已停止" if not self.error else "启动或处理失败"


service = Service()


@app.get("/")
def index():
    return FileResponse(ROOT / "index.html")


@app.get("/app.js")
def javascript():
    return FileResponse(ROOT / "app.js", media_type="text/javascript")


@app.get("/style.css")
def stylesheet():
    return FileResponse(ROOT / "style.css", media_type="text/css")


@app.get("/api/devices")
def devices():
    try:
        with audio_lock, AudioHost(refresh=True) as audio:
            try:
                default = int(audio.get_default_wasapi_loopback()["index"])
            except Exception:
                default = None
            wasapi = audio.get_host_api_info_by_type(pa.paWASAPI)
            microphones = []
            outputs = []
            for i in range(audio.get_device_count()):
                try:
                    d = audio.get_device_info_by_index(i)
                except (OSError, ValueError):
                    # Disconnected/virtual Windows devices may leave invalid entries.
                    continue
                if d.get("isLoopbackDevice") and d["maxInputChannels"] > 0:
                    outputs.append(dict(id=i, name=d["name"]))
                if (
                    d["hostApi"] == wasapi["index"]
                    and d["maxInputChannels"] > 0
                    and not d.get("isLoopbackDevice")
                ):
                    microphones.append(dict(id=i, name=d["name"]))
            return {
                "default": default,
                "devices": outputs,
                "microphones": microphones,
                "default_microphone": int(wasapi["defaultInputDevice"]),
            }
    except Exception as exc:
        raise HTTPException(500, str(exc))


@app.post("/api/start")
def start(request: StartRequest):
    with service.lock:
        if service.thread and service.thread.is_alive():
            raise HTTPException(409, "正在运行或停止中，请稍后再试。")
        device_list = devices()
        available = {d["id"] for d in device_list["devices"]}
        if request.device not in available:
            raise HTTPException(400, "播放设备不可用，请刷新设备。")
        if request.microphone is not None and request.microphone not in {
            d["id"] for d in device_list.get("microphones", [])
        }:
            raise HTTPException(400, "麦克风不可用，请刷新设备。")
        service.stop.clear()
        service.error = ""
        service.thread = threading.Thread(
            target=service.run, args=(request.device, request.microphone), daemon=True
        )
        service.thread.start()
    return {"ok": True}


@app.post("/api/stop")
def stop():
    service.stop.set()
    return {"ok": True}


@app.get("/api/state")
def state(after: int = 0):
    with service.lock:
        return dict(
            version=VERSION,
            translation_engine=ENGINE,
            status=service.status,
            error=service.error,
            level=service.level,
            mic_level=service.mic_level,
            running=bool(service.thread and service.thread.is_alive()),
            rows=[r for r in service.rows if r["id"] > after]
            if after
            else list(service.rows)[-12:],
        )


@app.get("/api/history/dates")
def history_dates():
    return store.dates()


@app.get("/api/export")
def export_all():
    return StreamingResponse(
        store.export(),
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="full-conversation.txt"'},
    )


@app.get("/api/history/{date}")
def history(date: str, before: int | None = None):
    from datetime import date as Date

    try:
        Date.fromisoformat(date)
    except ValueError:
        raise HTTPException(400, "日期格式应为 YYYY-MM-DD")
    return store.history(date, before)


class WordRequest(BaseModel):
    term: str


class SaveWordRequest(BaseModel):
    term: str
    zh: str
    context: str = ""


class ReviewRequest(BaseModel):
    mastered: bool


class SpeakerNameRequest(BaseModel):
    name: str


class RenameSpeakerRequest(SpeakerNameRequest):
    source: str


@app.post("/api/speakers/name")
def name_speaker(request: RenameSpeakerRequest):
    import re

    name = request.name.strip()
    if (
        not name
        or len(name) > 60
        or not re.fullmatch(r"remote:[0-9a-f]{8}:\d{1,2}", request.source)
    ):
        raise HTTPException(400, "请选择自动识别的人物，并输入 1–60 个字符的名称。")
    with service.lock:
        store.rename_speaker(request.source, name)
        for row in service.rows:
            if row["source"] == request.source:
                row["speaker"] = name
    return {"source": request.source, "name": name}


@app.post("/api/transcripts/{transcript_id}/speaker")
def correct_speaker(transcript_id: int, request: SpeakerNameRequest):
    name = request.name.strip()
    if not name or len(name) > 60:
        raise HTTPException(400, "人物名称应为 1–60 个字符。")
    with service.lock:
        row = store.reassign(transcript_id, name)
        if row is None:
            raise HTTPException(404, "字幕不存在")
        for i, item in enumerate(service.rows):
            if item["id"] == transcript_id:
                service.rows[i] = row
                break
    return row


def clean_term(term):
    term = " ".join(term.split())
    if (
        not term
        or len(term) > 120
        or not any(c.isascii() and c.isalpha() for c in term)
    ):
        raise HTTPException(400, "请选择 1–120 个字符的英文单词或短语。")
    return term


@app.post("/api/translate-word")
def translate_word(request: WordRequest):
    term = clean_term(request.term)
    try:
        return {"term": term, "zh": service.translate(term)}
    except Exception as exc:
        raise HTTPException(503, str(exc))


@app.post("/api/words")
def save_word(request: SaveWordRequest):
    term = clean_term(request.term)
    if not request.zh.strip() or len(request.zh) > 2000 or len(request.context) > 4000:
        raise HTTPException(400, "请先获取有效翻译。")
    return store.save_word(term, request.zh.strip(), request.context)


@app.get("/api/words")
def words():
    return store.words()


@app.post("/api/words/{word_id}/review")
def review(word_id: int, request: ReviewRequest):
    result = store.review(word_id, request.mastered)
    if result is None:
        raise HTTPException(404, "单词不存在")
    return result


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8765)
