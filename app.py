"""Local-only Windows playback subtitles."""

import math
import os
import subprocess
import sys
import queue
import threading
import time
from dataclasses import dataclass
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
from inference import AdaptiveModel
from speech import MODEL_NAME as SPEECH_NAME, MODEL_DIR as SPEECH_DIR
from streaming import StableEnglish, reconcile_groups
from caption_layout import LiveParagraphs
from audio_devices import preferred_microphone

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


@dataclass
class TranslationJob:
    id: int
    en: str
    source: str
    timestamp: str
    session: str = ""


class Service:
    def __init__(self):
        self.lock = threading.RLock()
        self.changed = threading.Condition(self.lock)
        self.revision = 0
        self.previews = {}
        self.preview_jobs = {}
        self.active_utterances = {}
        self.stabilizers = {}
        self.layout = LiveParagraphs()
        self.asr_runtime = None
        self.translation_jobs = queue.Queue()
        self.translation_thread = None
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
        self.inputs = {"device": None, "microphone": None}
        self.rows.extend(store.recent())
        self.sequence = self.rows[-1]["id"] if self.rows else 0

    def emit(self, english, chinese, source="output", timestamp=None, **live_fields):
        with self.lock:
            row = store.append(english, chinese, source, timestamp)
            self.sequence = row["id"]
            self.revision += 1
            row["revision"] = self.revision
            row.update(live_fields)
            self.rows.append(row)
            self.changed.notify_all()
            return row

    def notify(self):
        with self.changed:
            self.revision += 1
            self.changed.notify_all()

    def hardware(self):
        translation = self.translator.runtime if self.translator else None
        return {
            "asr": self.asr_runtime.label if self.asr_runtime else "--",
            "translation": translation.label if translation else "--",
            "speaker": "CPU",
            "asr_model": SPEECH_NAME,
            "fallback": {name: runtime.reason for name, runtime in
                         (("asr", self.asr_runtime), ("translation", translation)) if runtime and runtime.reason},
        }

    def ensure_translation_worker(self):
        with self.lock:
            if self.translation_thread and self.translation_thread.is_alive():
                return
            for row in store.pending_translations():
                self.translation_jobs.put(TranslationJob(row["id"], row["en"], row["source"], row["timestamp"]))
            self.translation_thread = threading.Thread(target=self.translate_pending, daemon=True)
            self.translation_thread.start()

    def translate_pending(self):
        deferred = None
        recent = deque(maxlen=2)
        context_session = None
        while True:
            first = deferred or self.translation_jobs.get()
            deferred = None
            batch = [first]
            text = first.en
            # Allow adjacent, short fragments from a confirmed same speaker to
            # arrive. Never group legacy rows, different people, sessions or dates.
            if first.session and first.source != "output":
                deadline = time.monotonic() + 1.8
                while len(batch) < 4 and (len(text.split()) < 8 or not text.rstrip().endswith((".", "?", "!"))):
                    try:
                        following = self.translation_jobs.get(timeout=max(0.01, deadline - time.monotonic()))
                    except queue.Empty:
                        break
                    gap = (datetime.fromisoformat(following.timestamp) - datetime.fromisoformat(batch[-1].timestamp)).total_seconds()
                    if (following.session != first.session or following.source != first.source or
                            following.timestamp[:10] != first.timestamp[:10] or not 0 <= gap <= 8 or len(text) + len(following.en) > 600):
                        deferred = following
                        break
                    batch.append(following)
                    text += " " + following.en
                    if time.monotonic() >= deadline:
                        break
            try:
                if first.session != context_session:
                    recent.clear()
                    context_session = first.session
                try:
                    chinese = self.translate(text, context=list(recent)) if recent else self.translate(text)
                except Exception:
                    chinese = "［翻译暂不可用，请参考英文原文］"
                if first.session and not chinese.startswith("［"):
                    recent.append((text, chinese))
                with self.lock:
                    for updated in store.update_translation_group([job.id for job in batch], chinese):
                        self.revision += 1
                        updated["revision"] = self.revision
                        for index, row in enumerate(self.rows):
                            if row["id"] == updated["id"]:
                                for field in ("utterance", "capture_source"):
                                    if field in row:
                                        updated[field] = row[field]
                                self.rows[index] = updated
                                break
                    self.changed.notify_all()
            finally:
                for _ in batch:
                    self.translation_jobs.task_done()

    def emit_final(self, english, source, timestamp, **live_fields):
        row = self.emit(english, "", source, timestamp, **live_fields)
        self.translation_jobs.put(TranslationJob(row["id"], english, source, row["timestamp"], self.tracker.session if self.tracker else ""))

    def transcribe(self, clip, preview=False):
        def infer(model):
            segments, _ = model.transcribe(
                clip, language="en", beam_size=1, vad_filter=True,
                condition_on_previous_text=False, word_timestamps=not preview,
            )
            return list(segments)
        if self.asr_runtime:
            result = self.asr_runtime.run(infer)
            self.model = self.asr_runtime.model
            return result
        return infer(self.model)

    def translate(self, text, context=()):
        with self.translation_lock:
            if self.translator is None:
                self.translator = ChineseTranslator(ROOT / "models" / MODEL_DIR, on_change=self.notify)
                self.notify()
            return self.translator.translate(text, context=context)

    def load_models(self):
        from faster_whisper import WhisperModel

        self.status = "正在加载离线模型…"
        if self.model is None:
            model_path = ROOT / "models" / SPEECH_DIR
            if not (model_path / "model.bin").exists():
                raise RuntimeError("语音模型未安装，请先运行 setup.ps1。")
            self.asr_runtime = AdaptiveModel(
                lambda device, compute: WhisperModel(str(model_path), device=device, compute_type=compute),
                on_change=self.notify,
                gpu_compute="float16",
            )
            # Force a real encoder call: CUDA libraries load lazily, even if model loading succeeds.
            self.asr_runtime.run(lambda model: list(model.transcribe(
                np.zeros(16000, dtype=np.float32), language="en", beam_size=1, vad_filter=False,
            )[0]))
            self.model = self.asr_runtime.model
            self.notify()

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
                        last_preview = 0
                        utterance = None
                        started = None
                        preroll = deque(maxlen=3)

                        def audio_clip():
                            clip = np.concatenate(frames)
                            divisor = math.gcd(rate, 16000)
                            clip = resample_poly(
                                clip, 16000 // divisor, rate // divisor
                            ).astype(np.float32)
                            return clip

                        def enqueue():
                            with self.lock:
                                self.preview_jobs.pop(source, None)
                                self.active_utterances[source] = None
                            try:
                                chunks.put_nowait((audio_clip(), source, started, utterance))
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
                                utterance = uuid4().hex
                                with self.lock:
                                    self.active_utterances[source] = utterance
                            frames.append(mono)
                            duration += 0.1
                            silence = 0 if voiced else silence + 0.1
                            if (silence >= 0.6 and duration >= 0.6) or duration >= 7:
                                enqueue()
                                frames, silence, duration = [], 0, 0
                                last_preview = 0
                            elif duration - last_preview >= (1.0 if self.asr_runtime and self.asr_runtime.device == "cuda" else 1.8):
                                last_preview = duration
                                with self.lock:
                                    # Coalesce previews: obsolete snapshots never build up behind final audio.
                                    self.preview_jobs[source] = (audio_clip(), source, started, utterance)
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
            self.ensure_translation_worker()
            listening = (
                "正在监听耳机和麦克风"
                if microphone is not None
                else "正在监听耳机播放音频"
            )
            self.status = listening
            self.notify()
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
                    clip, source, timestamp, utterance = chunks.get_nowait()
                    preview = False
                except queue.Empty:
                    with self.lock:
                        source = next(iter(self.preview_jobs), None)
                        job = self.preview_jobs.pop(source) if source else None
                    if job is None:
                        self.stop.wait(0.05) if not self.stop.is_set() else threading.Event().wait(0.02)
                        continue
                    clip, source, timestamp, utterance = job
                    preview = True
                self.status = (
                    "停止捕获，正在保存剩余对话…"
                    if self.stop.is_set()
                    else "正在识别英文…"
                )
                segments = self.transcribe(clip, preview=preview)
                if preview:
                    text = " ".join(s.text.strip() for s in segments if s.no_speech_prob < 0.6).strip()
                    with self.lock:
                        if text and self.active_utterances.get(source) == utterance:
                            stable = self.stabilizers.setdefault(utterance, StableEnglish()).update(text)
                            before = self.previews.get(source, {})
                            if before.get("en") != stable["en"] or before.get("stable_en") != stable["stable_en"] or before.get("utterance") != utterance:
                                self.previews[source] = {"source": source, "utterance": utterance, **stable,
                                    "timestamp": timestamp.isoformat(), "time": timestamp.strftime("%H:%M:%S"), "date": timestamp.date().isoformat(),
                                    "speaker": "我（麦克风）" if source == "microphone" else "对方（实时预览）"}
                                self.notify()
                    continue
                if source == "microphone":
                    text = " ".join(
                        s.text.strip() for s in segments if s.no_speech_prob < 0.6
                    ).strip()
                    groups = [{"text": text, "source": source, "offset": 0}] if text else []
                else:
                    groups = self.tracker.label_segments(clip, segments)
                # Finish the editable tail while retaining the reader's confirmed prefix.
                hypothesis = " ".join(group["text"] for group in groups)
                with self.lock:
                    stabilizer = self.stabilizers.pop(utterance, None)
                    if not groups and stabilizer and stabilizer.stable:
                        hypothesis = " ".join(stabilizer.stable)
                        groups = [{"text": hypothesis, "source": source if source == "microphone" else self.tracker.classify(clip), "offset": 0}]
                    final_text = stabilizer.update(hypothesis, final=True)["en"] if stabilizer and hypothesis else hypothesis
                    groups = reconcile_groups(groups, final_text)
                    if self.previews.get(source, {}).get("utterance") == utterance:
                        self.previews.pop(source, None)
                    for group in groups:
                        english = group["text"]
                        if english:
                            self.emit_final(
                                english,
                                group["source"],
                                timestamp + timedelta(seconds=group["offset"]),
                                utterance=utterance, capture_source=source,
                            )
                    self.notify()
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
            with self.lock:
                self.previews.clear()
                self.preview_jobs.clear()
                self.active_utterances.clear()
                self.stabilizers.clear()
                self.notify()


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
                "default_microphone": preferred_microphone(microphones, int(wasapi["defaultInputDevice"]),
                    next((item["name"] for item in outputs if item["id"] == default), "")),
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
        service.inputs = {"device": request.device, "microphone": request.microphone}
        service.error = ""
        service.thread = threading.Thread(
            target=service.run, args=(request.device, request.microphone), daemon=True
        )
        service.thread.start()
        service.notify()
    return {"ok": True}


@app.post("/api/stop")
def stop():
    service.stop.set()
    service.notify()
    return {"ok": True}


@app.get("/api/state")
def state(after: int = 0, revision: int = -1):
    with service.lock:
        return dict(
            version=VERSION,
            revision=service.revision,
            hardware=service.hardware(),
            inputs=service.inputs,
            partials=list(service.previews.values()),
            paragraphs=service.layout.apply(list(service.rows), list(service.previews.values()))[-40:],
            pending_translations=service.translation_jobs.unfinished_tasks,
            updates=[r for r in service.rows if r["id"] <= after and r.get("revision", 0) > revision] if revision >= 0 else [],
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


@app.get("/api/live")
def live(after: int = 0, revision: int = -1):
    # Long polling wakes on changes rather than repeatedly rebuilding either UI.
    with service.changed:
        if revision >= 0 and revision == service.revision:
            service.changed.wait_for(lambda: service.revision != revision, timeout=15)
        return state(after, revision)


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
