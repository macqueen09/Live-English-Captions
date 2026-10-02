import unittest
from unittest.mock import Mock, patch
from inference import AdaptiveModel


class InferenceTests(unittest.TestCase):
    def test_lazy_cuda_failure_retries_same_input_on_cpu(self):
        gpu, cpu = Mock(), Mock()
        factory = Mock(side_effect=[gpu, cpu])
        changed = Mock()
        with patch("ctranslate2.get_cuda_device_count", return_value=1):
            runtime = AdaptiveModel(factory, changed)
        operation = Mock(side_effect=[RuntimeError("CUDA out of memory"), "same clip transcribed", "next clip transcribed"])
        self.assertEqual(runtime.run(operation), "same clip transcribed")
        self.assertEqual(runtime.label, "CPU")
        self.assertIn("memory", runtime.reason)
        self.assertEqual(factory.call_args_list[1].args, ("cpu", "int8"))
        self.assertEqual(operation.call_args_list[1].args, (cpu,))
        self.assertEqual(runtime.run(operation), "next clip transcribed")
        self.assertEqual(factory.call_count, 2)
        changed.assert_called_once()

    def test_cuda_initialization_failure_falls_back(self):
        factory = Mock(side_effect=[RuntimeError("missing DLL"), Mock()])
        with patch("ctranslate2.get_cuda_device_count", return_value=1):
            runtime = AdaptiveModel(factory)
        self.assertEqual(runtime.label, "CPU")
        self.assertEqual(runtime.reason, "missing DLL")

    def test_cpu_failure_is_reported_without_looping(self):
        with patch("ctranslate2.get_cuda_device_count", return_value=0):
            runtime = AdaptiveModel(Mock(return_value=Mock()))
        with self.assertRaisesRegex(RuntimeError, "bad input"):
            runtime.run(Mock(side_effect=RuntimeError("bad input")))
