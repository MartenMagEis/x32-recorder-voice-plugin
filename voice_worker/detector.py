"""microWakeWord models, one per command, sharing one feature extractor.

A model reference is either the name of a model bundled with pymicro-wakeword ("okay_nabu",
"hey_jarvis", ...) or the base name of a custom model in the plugin's wakewords/ folder
(<name>.json + the .tflite file it points to, as produced by the microWakeWord trainer).
"""
import os

from pymicro_wakeword import MicroWakeWord, MicroWakeWordFeatures, Model

BUILTIN_MODELS = [m.value for m in Model]

# After a reset the feature frontend starts from an empty state, and for about half a second its
# output looks like nothing it ever saw in training: tapedeck_marker reached 0.99 there on band
# audio that scores 0.00 once the frontend has settled. Models keep running through this window
# (so their state fills up) but cannot fire. 2 s = 200 feature steps of 10 ms; harmless, since no one
# says the next command within 2 s of a gap in the audio or of the previous command.
WARMUP_STEPS = 200


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
        self.steps = 0

    def reset(self):
        self.features.reset()
        for model in self.models.values():
            model.reset()
        self.steps = 0

    def process(self, pcm16):
        """16 kHz mono int16 bytes -> [(command, probability, hit), ...] for every model step.
        `hit` means above the model's own cutoff (shipped with the model, tuned by its trainer);
        the probabilities below it are what near-miss sample collection looks at. Nothing is
        reported during the warm-up after a reset (see WARMUP_STEPS)."""
        results = []
        for features in self.features.process_streaming(pcm16):
            self.steps += 1
            for command, model in self.models.items():
                prob = model.process_streaming_prob(features)
                if self.steps <= WARMUP_STEPS or prob is None:
                    continue
                results.append((command, prob, prob > model.probability_cutoff))
        return results
