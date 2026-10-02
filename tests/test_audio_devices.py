import unittest
from audio_devices import preferred_microphone


class AudioDeviceTests(unittest.TestCase):
    microphones = [{"id":25, "name":"立体声混音 (Realtek(R) Audio)"},
                   {"id":26, "name":"麦克风 (HECATE G2 Wireless 7.1)"},
                   {"id":27, "name":"麦克风 (UGREEN Camera Audio)"}]

    def test_mix_default_prefers_matching_headset(self):
        self.assertEqual(preferred_microphone(self.microphones, 25,
            "扬声器 (HECATE G2 Wireless 7.1) [Loopback]"), 26)

    def test_real_default_is_preserved(self):
        self.assertEqual(preferred_microphone(self.microphones, 27,
            "扬声器 (HECATE G2 Wireless 7.1) [Loopback]"), 27)

    def test_mix_without_real_input_disables_microphone(self):
        self.assertIsNone(preferred_microphone(self.microphones[:1], 25))
