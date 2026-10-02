import threading
import unittest
import tempfile
from types import SimpleNamespace
from unittest.mock import patch
from unittest.mock import MagicMock
import numpy as np
from fastapi import HTTPException
import app


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store_patch = patch.object(app, "store", app.Store(self.directory.name))
        self.store_patch.start()
        self.service = app.Service()
        self.patch = patch.object(app, "service", self.service)
        self.patch.start()

    def tearDown(self):
        self.service.stop.set()
        if self.service.thread:
            self.service.thread.join(timeout=2)
        self.service.translation_jobs.join()
        self.patch.stop()
        self.store_patch.stop()
        self.directory.cleanup()

    def test_history_is_bounded_and_ids_monotonic(self):
        for i in range(210):
            self.service.emit(str(i), "中文")
        self.assertEqual(len(self.service.rows), 200)
        self.assertEqual(self.service.rows[0]["id"], 11)
        self.assertEqual(app.state()["rows"][-1]["id"], 210)
        self.assertEqual(len(app.state()["rows"]), 12)
        self.assertEqual(len(app.state(after=207)["rows"]), 3)

    def test_invalid_device_is_rejected(self):
        with patch.object(app, "devices", return_value={"devices": [{"id": 7}]}):
            with self.assertRaises(HTTPException) as error:
                app.start(app.StartRequest(device=8))
            self.assertEqual(error.exception.status_code, 400)
        self.assertIsNone(self.service.thread)

    def test_start_stop_and_duplicate_start(self):
        entered = threading.Event()

        def run(device, microphone=None):
            entered.set()
            self.service.stop.wait(timeout=2)

        with (
            patch.object(self.service, "run", side_effect=run),
            patch.object(app, "devices", return_value={"devices": [{"id": 7}]}),
        ):
            app.start(app.StartRequest(device=7))
            self.assertTrue(entered.wait(timeout=1))
            self.assertTrue(app.state()["running"])
            with self.assertRaises(HTTPException) as error:
                app.start(app.StartRequest(device=7))
            self.assertEqual(error.exception.status_code, 409)
            app.stop()
            self.service.thread.join(timeout=1)
            self.assertFalse(app.state()["running"])

    def test_model_error_is_visible(self):
        with patch.object(
            self.service, "load_models", side_effect=RuntimeError("模型缺失")
        ):
            self.service.run(7)
        self.assertEqual(app.state()["error"], "模型缺失")
        self.assertTrue(self.service.stop.is_set())

    def test_stop_flushes_and_saves_final_audio(self):
        audio = MagicMock()
        audio.__enter__.return_value = audio
        audio.get_device_info_by_index.return_value = {
            "isLoopbackDevice": True,
            "defaultSampleRate": 16000,
            "maxInputChannels": 1,
        }
        stream = MagicMock()
        audio.open.return_value.__enter__.return_value = stream
        reads = 0

        def read(*args, **kwargs):
            nonlocal reads
            reads += 1
            if reads == 5:
                self.service.stop.set()
            return (np.ones(1600, dtype=np.float32) * 0.02).tobytes()

        stream.read.side_effect = read
        self.service.model = MagicMock()
        self.service.model.transcribe.return_value = ([], None)
        tracker = MagicMock()
        tracker.label_segments.return_value = [
            {"source": "remote:1234abcd:1", "text": "Final words", "offset": 0}
        ]
        with (
            patch.object(self.service, "load_models"),
            patch.object(self.service, "translate", return_value="最后一句"),
            patch.object(app, "AudioHost", return_value=audio),
            patch.object(app, "VoiceTracker", return_value=tracker),
        ):
            self.service.run(7)
            self.service.translation_jobs.join()
        self.assertEqual(app.store.recent()[0]["en"], "Final words")
        self.assertEqual(app.store.recent()[0]["speaker"], "对方 1")
        self.assertEqual(self.service.error, "")

    def test_overlapping_audio_is_transcribed_per_input_and_displayed_separately(self):
        barrier = threading.Barrier(2)
        host = MagicMock()
        host.__enter__.return_value = host
        host.get_device_info_by_index.side_effect = lambda device: {
            "isLoopbackDevice": device == 7, "defaultSampleRate":16000, "maxInputChannels":1}

        def open_stream(**kwargs):
            context, stream = MagicMock(), MagicMock()
            context.__enter__.return_value = stream
            count = 0
            value = .02 if kwargs["input_device_index"] == 7 else .04
            def read(*args, **options):
                nonlocal count
                barrier.wait(timeout=3)
                count += 1
                if count == 5:
                    self.service.stop.set()
                return np.full(1600, value, dtype=np.float32).tobytes()
            stream.read.side_effect = read
            return context

        host.open.side_effect = open_stream
        seen = []
        def recognize(clip, preview=False):
            value = round(float(np.mean(clip)), 2)
            seen.append(value)
            return [SimpleNamespace(text="My own words" if value == .04 else "Their words", no_speech_prob=0)]
        tracker = MagicMock()
        tracker.session = "overlap"
        tracker.label_segments.side_effect = lambda clip, segments: [
            {"source":"remote:overlap:1", "text":segments[0].text, "offset":0}]
        with patch.object(self.service, "load_models"), patch.object(self.service, "transcribe", side_effect=recognize), \
                patch.object(self.service, "translate", return_value="独立译文"), \
                patch.object(app, "AudioHost", return_value=host), patch.object(app, "VoiceTracker", return_value=tracker):
            self.service.run(7, 8)
            self.service.translation_jobs.join()
        self.assertEqual(self.service.error, "")
        self.assertCountEqual(seen, [.02, .04])
        rows = app.store.recent()
        self.assertEqual({row["source"]:row["en"] for row in rows},
                         {"microphone":"My own words", "remote:overlap:1":"Their words"})
        paragraphs = app.state()["paragraphs"]
        self.assertEqual(len(paragraphs), 2)
        self.assertCountEqual([p["en"] for p in paragraphs], ["My own words", "Their words"])

    def test_english_is_saved_before_translation_and_patch_reaches_client(self):
        entered, release = threading.Event(), threading.Event()

        def translate(text):
            entered.set()
            release.wait(timeout=2)
            return "后来补上中文"

        with patch.object(self.service, "translate", side_effect=translate):
            self.service.ensure_translation_worker()
            self.service.emit_final("English first", "microphone", None)
            try:
                self.assertTrue(entered.wait(timeout=1))
                first = app.state()
                self.assertEqual(first["rows"][0]["en"], "English first")
                self.assertEqual(first["rows"][0]["zh"], "")
                self.assertEqual(app.store.recent()[0]["zh"], "")
            finally:
                release.set()
            self.service.translation_jobs.join()
        patched = app.state(after=1, revision=first["revision"])
        self.assertEqual(patched["rows"], [])
        self.assertEqual(patched["updates"][0]["zh"], "后来补上中文")
        self.assertEqual(app.store.recent()[0]["zh"], "后来补上中文")

    def test_live_waiter_wakes_for_new_english(self):
        received = []
        revision = self.service.revision
        client = threading.Thread(target=lambda: received.append(app.live(after=0, revision=revision)))
        client.start()
        self.service.emit("Wake the waiting screen", "中文")
        client.join(timeout=1)
        self.assertFalse(client.is_alive())
        self.assertEqual(received[0]["rows"][0]["en"], "Wake the waiting screen")

    def test_restart_recovers_pending_chinese_without_duplicate_english(self):
        app.store.append("Previously saved English", "", "microphone")
        with patch.object(self.service, "translate", return_value="重启后翻译"):
            self.service.ensure_translation_worker()
            self.service.translation_jobs.join()
        rows = app.store.recent()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["zh"], "重启后翻译")

    def test_short_fragments_share_translation_and_next_person_gets_context(self):
        old = app.store.append("Old history", "旧记录保持原样", "microphone")
        self.service.tracker = SimpleNamespace(session="abcdef12")
        with patch.object(self.service, "translate", side_effect=["合并后的完整译文", "另一人物的译文"]) as translate:
            self.service.ensure_translation_worker()
            self.service.emit_final("Could you", "microphone", None)
            self.service.emit_final("bring the sensor tomorrow?", "microphone", None)
            self.service.translation_jobs.join()
            self.assertEqual(translate.call_count, 1)
            self.assertEqual(translate.call_args.args, ("Could you bring the sensor tomorrow?",))
            self.service.emit_final("Yes I can bring the sensor to you tomorrow.", "remote:abcdef12:1", None)
            self.service.translation_jobs.join()
            self.assertEqual(translate.call_args.kwargs["context"], [("Could you bring the sensor tomorrow?", "合并后的完整译文")])
        rows = app.store.recent()
        self.assertEqual(rows[0]["zh"], old["zh"])
        self.assertEqual(rows[1]["translation_group"], rows[1]["id"])
        self.assertEqual(rows[2]["translation_group"], rows[1]["id"])
        exported = "".join(app.store.export())
        self.assertEqual(exported.count("合并后的完整译文"), 1)
        self.assertIn("Could you", exported)
        self.assertIn("bring the sensor tomorrow?", exported)


if __name__ == "__main__":
    unittest.main()
