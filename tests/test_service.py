import threading
import unittest
import tempfile
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
        self.assertEqual(app.store.recent()[0]["en"], "Final words")
        self.assertEqual(app.store.recent()[0]["speaker"], "对方 1")
        self.assertEqual(self.service.error, "")


if __name__ == "__main__":
    unittest.main()
