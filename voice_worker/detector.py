"""microWakeWord models, one per command, sharing one feature extractor.

A model reference is either the name of a model bundled with pymicro-wakeword ("okay_nabu",
"hey_jarvis", ...) or the base name of a custom model in the plugin's wakewords/ folder
(<name>.json + the .tflite file it points to, as produced by the microWakeWord trainer).
"""
import os

from pymicro_wakeword import MicroWakeWord, MicroWakeWordFeatures, Model

BUILTIN_MODELS = [m.value for m in Model]


def load_model(ref, wakewords_dir):
    if ref in BUILTIN_MODELS:
        return MicroWakeWord.from_builtin(Model(ref))
    config_path = os.path.join(wakewords_dir, ref + '.json')
    if not os.path.isfile(config_path):
        raise FileNotFoundError(f'Wake-Word-Modell "{ref}" nicht gefunden ({config_path})')
    return MicroWakeWord.from_config(config_path)


class CommandDetector:
    def __init__(self, mapping, wakewords_dir):
        """mapping: {command: model_ref} - commands without a model are simply not listened for."""
        self.features = MicroWakeWordFeatures()
        self.models = {cmd: load_model(ref, wakewords_dir) for cmd, ref in mapping.items() if ref}

    def reset(self):
        self.features.reset()
        for model in self.models.values():
            model.reset()

    def process(self, pcm16):
        """16 kHz mono int16 bytes -> [(command, probability), ...] for every model above its
        own cutoff (the cutoff shipped with the model, tuned by its trainer)."""
        hits = []
        for features in self.features.process_streaming(pcm16):
            for command, model in self.models.items():
                prob = model.process_streaming_prob(features)
                if prob is not None and prob > model.probability_cutoff:
                    hits.append((command, prob))
        return hits
