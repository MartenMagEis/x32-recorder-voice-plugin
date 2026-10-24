"""Collects voice samples for training: a short clip around every recognized command and around
every near miss (a model came close to its threshold but didn't reach it).

Clips are cut from a per-channel ring buffer of the 16 kHz audio the detector already gets, kept in
memory, and only written to disk while nothing is recording or playing back - so collecting never
competes with a recording for the disk. Each clip is a 16 kHz mono WAV with a JSON sidecar
describing what happened (see Clip.meta); the review page and training/label_clips.py add labels
to that sidecar later.

Nothing here knows about Django or the recorder API - the worker feeds audio and events in.
"""
import datetime
import json
import os
import wave

import numpy as np

RATE = 16000
PRE_S = 3.0   # audio kept before the moment of recognition (the phrase is already said by then)
POST_S = 1.0  # and after it
MAX_CLIPS_IN_MEMORY = 60  # ~8 MB; near misses are dropped first when it fills up
REPEAT_WINDOW_S = 10.0  # a near miss followed by a recognition this soon was probably a repeat

KIND_RECOGNIZED = 'erkannt'
KIND_NEAR_MISS = 'beinahe'


class AudioRing:
    """The last `seconds` of a channel's 16 kHz audio, addressed by absolute sample position."""

    def __init__(self, seconds=PRE_S + POST_S + 2.0):
        self.buf = np.zeros(int(seconds * RATE), dtype=np.int16)
        self.total = 0  # samples ever written

    def append(self, pcm):
        pcm = np.asarray(pcm, dtype=np.int16)
        n = len(pcm)
        if n >= len(self.buf):
            self.buf[:] = pcm[-len(self.buf):]
        else:
            start = self.total % len(self.buf)
            first = min(n, len(self.buf) - start)
            self.buf[start:start + first] = pcm[:first]
            self.buf[:n - first] = pcm[first:]
        self.total += n

    def get(self, start, end):
        """Samples [start, end) - clipped to what is still in the buffer."""
        start = max(start, self.total - len(self.buf), 0)
        end = min(end, self.total)
        if end <= start:
            return np.zeros(0, dtype=np.int16)
        idx = np.arange(start, end) % len(self.buf)
        return self.buf[idx].copy()


class NearMissTracker:
    """Watches one model's probabilities on one channel. An episode starts when the probability
    reaches `threshold` and ends when it drops below again; feed() returns (peak, position) for an
    episode that ended without the model firing."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.peak = None
        self.peak_pos = None
        self.fired = False

    def feed(self, prob, threshold, fired, position):
        if prob >= threshold:
            if self.peak is None or prob > self.peak:
                self.peak, self.peak_pos = prob, position
            self.fired = self.fired or fired
            return None
        if self.peak is None:
            return None
        event = None if self.fired else (self.peak, self.peak_pos)
        self.reset()
        return event


class Clip:
    def __init__(self, ring, position, meta):
        self.ring = ring
        self.position = position  # sample position of the recognition (or the near miss's peak)
        self.meta = meta
        self.audio = None  # filled once enough audio after `position` has arrived

    @property
    def done(self):
        return self.audio is not None

    def try_cut(self):
        if self.audio is None and self.ring.total >= self.position + int(POST_S * RATE):
            self.audio = self.ring.get(self.position - int(PRE_S * RATE), self.position + int(POST_S * RATE))
        return self.done


class SampleCollector:
    def __init__(self, clock=None):
        self.clips = []
        self.clock = clock or (lambda: datetime.datetime.now(datetime.timezone.utc))

    def add(self, ring, position, kind, command, model, channel_no, probability, **extra):
        now = self.clock()
        meta = {
            'time': now.isoformat(timespec='milliseconds'),
            'kind': kind,
            'command': command,
            'model': model,
            'channel_no': channel_no,
            'probability': round(float(probability), 3),
            'label': None,  # 'positiv' / 'negativ' / 'unklar' - set on review
            'hints': [],
            **extra,
        }
        if kind == KIND_RECOGNIZED:
            # An earlier near miss of the same command shortly before: probably the same phrase,
            # said again because the first try wasn't recognized.
            for clip in self.clips:
                m = clip.meta
                if (m['kind'] == KIND_NEAR_MISS and m['command'] == command
                        and 0 <= (now - datetime.datetime.fromisoformat(m['time'])).total_seconds() <= REPEAT_WINDOW_S
                        and 'danach erkannt' not in m['hints']):
                    m['hints'].append('danach erkannt')
        self.clips.append(Clip(ring, position, meta))
        self._enforce_memory_limit()
        return meta

    def on_audio(self, ring):
        for clip in self.clips:
            if clip.ring is ring:
                clip.try_cut()

    def _enforce_memory_limit(self):
        while len(self.clips) > MAX_CLIPS_IN_MEMORY:
            victim = next((c for c in self.clips if c.meta['kind'] == KIND_NEAR_MISS), self.clips[0])
            self.clips.remove(victim)

    def pending_count(self):
        return len(self.clips)

    def flush(self, folder):
        """Writes every finished clip to <folder>/<model>/ and forgets it. Returns how many."""
        written = 0
        for clip in [c for c in self.clips if c.done]:
            if len(clip.audio):
                write_clip(folder, clip.meta, clip.audio)
                written += 1
            self.clips.remove(clip)
        return written

    def finish(self):
        """Before shutting down: cut what can be cut from the audio there is."""
        for clip in self.clips:
            if not clip.done:
                clip.audio = clip.ring.get(clip.position - int(PRE_S * RATE), clip.ring.total)


def clip_basename(meta):
    stamp = datetime.datetime.fromisoformat(meta['time']).astimezone().strftime('%Y%m%d-%H%M%S-%f')[:-3]
    return f"{stamp}_{meta['kind']}_{meta['command']}_ch{meta['channel_no']:02d}"


def write_clip(folder, meta, audio):
    target = os.path.join(folder, meta['model'] or meta['command'])
    os.makedirs(target, exist_ok=True)
    base = os.path.join(target, clip_basename(meta))
    with wave.open(base + '.wav.tmp', 'wb') as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(RATE)
        out.writeframes(np.asarray(audio, dtype='<i2').tobytes())
    os.replace(base + '.wav.tmp', base + '.wav')
    with open(base + '.json.tmp', 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    os.replace(base + '.json.tmp', base + '.json')
    return base


def enforce_disk_limit(folder, max_bytes):
    """Deletes the oldest clips beyond `max_bytes` - near misses before recognitions, and never a
    clip someone already labeled (those are the valuable ones)."""
    clips = []
    total = 0
    for root, _, files in os.walk(folder):
        for name in files:
            if not name.endswith('.wav'):
                continue
            wav = os.path.join(root, name)
            size = os.path.getsize(wav)
            total += size
            meta = _read_meta(wav[:-4] + '.json')
            if meta.get('label'):
                continue
            clips.append((meta.get('kind') != KIND_NEAR_MISS, meta.get('time', ''), wav, size))
    clips.sort()
    removed = 0
    for _, _, wav, size in clips:
        if total <= max_bytes:
            break
        for path in (wav, wav[:-4] + '.json'):
            try:
                os.remove(path)
            except FileNotFoundError:
                pass
        total -= size
        removed += 1
    return removed


def _read_meta(path):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}
