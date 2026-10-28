"""Local voice embeddings, conservatively clustered within each conversation."""

import numpy as np

MODEL_NAME = "3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx"
MODEL_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/"
    + MODEL_NAME
)


class VoiceTracker:
    def __init__(self, model_path, session, extractor=None):
        if extractor is None:
            import sherpa_onnx

            config = sherpa_onnx.SpeakerEmbeddingExtractorConfig(
                model=str(model_path), num_threads=2, provider="cpu"
            )
            extractor = sherpa_onnx.SpeakerEmbeddingExtractor(config)
        self.extractor = extractor
        self.session = session
        self.profiles = []

    def classify(self, audio):
        if len(audio) < 16000 * 0.8:
            return "output"
        stream = self.extractor.create_stream()
        stream.accept_waveform(16000, audio)
        stream.input_finished()
        if not self.extractor.is_ready(stream):
            return "output"
        vector = np.asarray(self.extractor.compute(stream), dtype=np.float32)
        norm = np.linalg.norm(vector)
        if norm < 1e-8:
            return "output"
        vector /= norm
        similarities = [float(vector @ profile) for profile in self.profiles]
        if similarities and max(similarities) >= 0.55:
            index = int(np.argmax(similarities))
            # Avoid changing a known voice on weak or short matches.
            if similarities[index] >= 0.7 and len(audio) >= 24000:
                merged = self.profiles[index] * 0.9 + vector * 0.1
                self.profiles[index] = merged / np.linalg.norm(merged)
        elif len(audio) >= 24000 and len(self.profiles) < 12:
            index = len(self.profiles)
            self.profiles.append(vector)
        else:
            return "output"
        return f"remote:{self.session}:{index + 1}"

    def label_segments(self, clip, segments):
        """Align voice labels to recognized words; merge adjacent matching labels."""
        pending, groups = [], []
        for segment in segments:
            if segment.no_speech_prob >= 0.6:
                continue
            if not segment.words:
                groups.append((segment.start, segment.end, segment.text.strip()))
                continue
            for word in segment.words:
                pending.append(word)
                if pending[-1].end - pending[0].start >= 2.0:
                    groups.append(
                        (
                            pending[0].start,
                            pending[-1].end,
                            "".join(w.word for w in pending).strip(),
                        )
                    )
                    pending = []
        if pending:
            groups.append(
                (
                    pending[0].start,
                    pending[-1].end,
                    "".join(w.word for w in pending).strip(),
                )
            )
        result = []
        for start, end, text in groups:
            # A little context helps embeddings for short final words.
            lo, hi = max(0, start - 0.15), min(len(clip) / 16000, end + 0.15)
            source = self.classify(clip[int(lo * 16000) : int(hi * 16000)])
            if result and result[-1]["source"] == source:
                result[-1]["text"] += " " + text
            else:
                result.append(dict(source=source, text=text, offset=start))
        return result
