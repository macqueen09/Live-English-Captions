import unittest
from unittest.mock import Mock
import numpy as np
from speakers import VoiceTracker


class VoiceTests(unittest.TestCase):
    def test_stable_ids_and_unknown_for_short_speech(self):
        extractor = Mock()
        extractor.is_ready.return_value = True
        extractor.compute.side_effect = [[1, 0], [0.99, 0.02], [0, 1], [0.01, 0.99]]
        tracker = VoiceTracker(None, "1234abcd", extractor)
        audio = np.ones(32000, dtype=np.float32)
        self.assertEqual(tracker.classify(audio), "remote:1234abcd:1")
        self.assertEqual(tracker.classify(audio), "remote:1234abcd:1")
        self.assertEqual(tracker.classify(audio), "remote:1234abcd:2")
        self.assertEqual(tracker.classify(audio), "remote:1234abcd:2")
        self.assertEqual(tracker.classify(audio[:4000]), "output")
