"""GPU-first CTranslate2 models with per-model, same-request CPU fallback."""
import os
from pathlib import Path
import sys

_dll_handles = []


def configure_cuda_libraries():
    if sys.platform != "win32":
        return
    for package in ("cuda_nvrtc", "cublas", "cudnn"):
        directory = Path(sys.prefix) / "Lib" / "site-packages" / "nvidia" / package / "bin"
        if directory.exists() and str(directory) not in os.environ.get("PATH", "").split(os.pathsep):
            os.environ["PATH"] = str(directory) + os.pathsep + os.environ.get("PATH", "")
            _dll_handles.append(os.add_dll_directory(str(directory)))


class AdaptiveModel:
    def __init__(self, factory, on_change=None):
        configure_cuda_libraries()
        import ctranslate2

        self.factory = factory
        self.on_change = on_change
        self.device = "cpu"
        self.reason = ""
        self.model = None
        try:
            if ctranslate2.get_cuda_device_count() > 0:
                self.model = factory("cuda", "int8_float16")
                self.device = "cuda"
        except Exception as exc:
            self.reason = str(exc)
        if self.model is None:
            self.model = factory("cpu", "int8")

    def run(self, operation):
        # Consume lazy generators inside operation so delayed CUDA errors are caught.
        try:
            return operation(self.model)
        except Exception as exc:
            if self.device != "cuda":
                raise
            self.reason = str(exc)
            self.device = "cpu"
            self.model = None  # release GPU weights before allocating CPU replacement
            self.model = self.factory("cpu", "int8")
            if self.on_change:
                self.on_change()
            return operation(self.model)

    @property
    def label(self):
        return "GPU" if self.device == "cuda" else "CPU"
