"""48 kHz -> 16 kHz for the wake-word models, streamed chunk by chunk.

Low-pass first, then every 3rd sample - just dropping samples would fold everything between 8 and
24 kHz (cymbals, hi-hats, sibilants - plenty of that in a rehearsal room) down into the speech
band as noise. A 63-tap windowed-sinc FIR, evaluated only for the kept samples' positions in
spirit (numpy convolves the whole chunk; at 48 kHz mono that's a few hundred µs per 10 ms packet).
"""
import numpy as np


class Decimator:
    def __init__(self, factor=3, taps=63, cutoff_hz=7000.0, rate_hz=48000):
        n = np.arange(taps) - (taps - 1) / 2.0
        fc = cutoff_hz / rate_hz
        h = 2 * fc * np.sinc(2 * fc * n) * np.hamming(taps)
        self.h = (h / h.sum()).astype(np.float32)
        self.factor = factor
        self.history = np.zeros(taps - 1, dtype=np.float32)
        self.next_index = 0  # position of the next kept sample within the coming chunk

    def reset(self):
        self.history[:] = 0.0
        self.next_index = 0

    def process(self, samples):
        """float32 samples at the input rate -> float32 samples at rate/factor."""
        x = np.asarray(samples, dtype=np.float32)
        if x.size == 0:
            return x
        buf = np.concatenate([self.history, x])
        y = np.convolve(buf, self.h, mode='valid')  # one output per input sample of this chunk
        self.history = buf[-(self.h.size - 1):]
        out = y[self.next_index::self.factor]
        self.next_index = (self.next_index - x.size) % self.factor
        return out.astype(np.float32)


def to_pcm16(samples):
    """float32 [-1, 1] -> little-endian int16 bytes (what microWakeWord's features expect)."""
    return (np.clip(samples, -1.0, 1.0) * 32767.0).astype('<i2').tobytes()
