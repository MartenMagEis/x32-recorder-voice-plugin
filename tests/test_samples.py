"""Unit tests for voice sample collection (voice_worker/samples.py and its use in the worker).
Run from the plugin folder:

    python -m unittest tests.test_samples      (needs numpy; the worker part also pymicro-wakeword)
"""
import datetime
import json
import os
import struct
import tempfile
import unittest
import wave

try:
    import numpy as np

    from voice_worker import samples
    from voice_worker.samples import (KIND_NEAR_MISS, KIND_RECOGNIZED, AudioRing, NearMissTracker,
                                      SampleCollector, enforce_disk_limit, write_clip)
except ImportError:  # inside x32-recorder's Django test run: no numpy there, and not on the path
    raise unittest.SkipTest('worker tests run standalone from the plugin folder (need numpy)')

RATE = samples.RATE


class RingTests(unittest.TestCase):
    def test_wraps_and_returns_the_latest_audio(self):
        ring = AudioRing(seconds=1.0)
        ring.append(np.arange(10000, dtype=np.int16))
        ring.append(np.arange(10000, 20000, dtype=np.int16))
        self.assertEqual(ring.total, 20000)
        np.testing.assert_array_equal(ring.get(19990, 20000), np.arange(19990, 20000, dtype=np.int16))
        # older than the buffer holds: clipped to what's left
        self.assertEqual(len(ring.get(0, 20000)), RATE)
        self.assertEqual(ring.get(0, 20000)[0], 20000 - RATE)


class NearMissTests(unittest.TestCase):
    def test_episode_below_cutoff_is_a_near_miss_with_its_peak(self):
        t = NearMissTracker()
        events = [t.feed(p, 0.5, False, pos) for pos, p in enumerate([0.2, 0.6, 0.8, 0.7, 0.3])]
        self.assertEqual(events, [None, None, None, None, (0.8, 2)])

    def test_episode_that_fired_is_not_a_near_miss(self):
        t = NearMissTracker()
        events = [t.feed(p, 0.5, p > 0.9, pos) for pos, p in enumerate([0.6, 0.95, 0.7, 0.1])]
        self.assertEqual(events, [None] * 4)


class FakeClock:
    def __init__(self):
        self.now = datetime.datetime(2026, 10, 24, 20, 0, 0, tzinfo=datetime.timezone.utc)

    def __call__(self):
        return self.now


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.collector = SampleCollector(clock=self.clock)
        self.ring = AudioRing()
        self.ring.append(np.ones(5 * RATE, dtype=np.int16))

    def add(self, kind, command='marker'):
        return self.collector.add(self.ring, self.ring.total, kind, command, 'tapedeck_marker', 15, 0.7)

    def test_clip_waits_for_the_audio_after_the_moment(self):
        self.add(KIND_RECOGNIZED)
        self.collector.on_audio(self.ring)
        self.assertFalse(self.collector.clips[0].done)
        self.ring.append(np.ones(RATE, dtype=np.int16))
        self.collector.on_audio(self.ring)
        clip = self.collector.clips[0]
        self.assertTrue(clip.done)
        self.assertEqual(len(clip.audio), int((samples.PRE_S + samples.POST_S) * RATE))

    def test_recognition_soon_after_a_near_miss_marks_it_as_a_repeat(self):
        near = self.add(KIND_NEAR_MISS)
        self.clock.now += datetime.timedelta(seconds=4)
        self.add(KIND_RECOGNIZED)
        self.assertEqual(near['hints'], ['danach erkannt'])
        other = self.add(KIND_NEAR_MISS, command='next')
        self.clock.now += datetime.timedelta(seconds=30)
        self.add(KIND_RECOGNIZED, command='next')
        self.assertEqual(other['hints'], [])

    def test_memory_limit_drops_near_misses_first(self):
        self.add(KIND_RECOGNIZED)
        for _ in range(samples.MAX_CLIPS_IN_MEMORY):
            self.add(KIND_NEAR_MISS)
        kinds = [c.meta['kind'] for c in self.collector.clips]
        self.assertEqual(len(kinds), samples.MAX_CLIPS_IN_MEMORY)
        self.assertEqual(kinds[0], KIND_RECOGNIZED)

    def test_flush_writes_wav_and_sidecar_per_model(self):
        meta = self.add(KIND_RECOGNIZED)
        self.ring.append(np.ones(RATE, dtype=np.int16))
        self.collector.on_audio(self.ring)
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(self.collector.flush(folder), 1)
            self.assertEqual(self.collector.pending_count(), 0)
            files = sorted(os.listdir(os.path.join(folder, 'tapedeck_marker')))
            self.assertEqual(len(files), 2)
            self.assertTrue(files[0].endswith('_erkannt_marker_ch15.json'))
            with wave.open(os.path.join(folder, 'tapedeck_marker', files[1])) as w:
                self.assertEqual((w.getframerate(), w.getnchannels(), w.getnframes()), (RATE, 1, 4 * RATE))
            with open(os.path.join(folder, 'tapedeck_marker', files[0]), encoding='utf-8') as f:
                self.assertEqual(json.load(f), meta)


class DiskLimitTests(unittest.TestCase):
    def test_oldest_unlabeled_near_misses_go_first_labeled_stay(self):
        with tempfile.TemporaryDirectory() as folder:
            audio = np.zeros(RATE, dtype=np.int16)  # ~32 KB per clip
            def clip(minute, kind, label=None):
                meta = {'time': f'2026-10-24T20:{minute:02d}:00+00:00', 'kind': kind, 'command': 'marker',
                        'model': 'm', 'channel_no': 1, 'label': label}
                return write_clip(folder, meta, audio)
            labeled = clip(0, KIND_NEAR_MISS, label='negativ')
            old_near = clip(1, KIND_NEAR_MISS)
            old_hit = clip(2, KIND_RECOGNIZED)
            new_near = clip(3, KIND_NEAR_MISS)
            size = os.path.getsize(labeled + '.wav')
            removed = enforce_disk_limit(folder, 2 * size + 10)
            self.assertEqual(removed, 2)
            left = {p for p in (labeled, old_near, old_hit, new_near) if os.path.exists(p + '.wav')}
            self.assertEqual(left, {labeled, old_hit})


class ScriptedDetector:
    """Stands in for CommandDetector: returns a prepared result list per process() call."""

    def __init__(self, script):
        self.script = list(script)

    def process(self, pcm):
        return self.script.pop(0) if self.script else []

    def reset(self):
        pass


class SilentApi:
    def post(self, path, data=None):
        return {'created': [{'id': 99, 'marker_type': 1, 'name': ''}]}


def packet(seq, n=480):
    return b'XTAP' + struct.pack('<BBHII', 1, 0, 15, seq, 48000) + np.zeros(n, '<f4').tobytes()


class WorkerCollectionTests(unittest.TestCase):
    def setUp(self):
        try:
            from voice_worker import main
        except ImportError:
            raise unittest.SkipTest('needs pymicro-wakeword')
        self.worker = main.Worker(SilentApi(), 'voice', '.', 'status.json')
        self.worker.config = {'collect_samples': True, 'near_miss_percent': 50}
        self.worker.mapping = {'marker': 'tapedeck_marker'}
        self.worker.target = {'recording': {'id': 128}}
        self.worker.write_status = lambda: None
        listener = main.Listener.__new__(main.Listener)
        listener.channel_no, listener.last_seq = 15, None
        listener.decimator = main.Decimator()
        listener.ring = AudioRing()
        listener.trackers = {'marker': NearMissTracker()}
        self.listener = listener
        self.worker.listeners = [listener]

    def feed(self, script, packets=120):
        self.listener.detector = ScriptedDetector(script)
        for seq in range(packets):
            self.worker.handle_packet(self.listener, packet(seq))

    def test_recognition_and_near_miss_become_clips(self):
        self.feed([[('marker', 0.6, False)], [('marker', 0.2, False)], [('marker', 0.95, True)]])
        metas = [c.meta for c in self.worker.collector.clips]
        self.assertEqual([(m['kind'], m['recording_id']) for m in metas],
                         [(KIND_NEAR_MISS, 128), (KIND_RECOGNIZED, 128)])
        self.assertEqual(metas[1]['marker_ids'], [99])
        self.assertEqual(metas[0]['hints'], ['danach erkannt'])
        self.assertTrue(all(c.done for c in self.worker.collector.clips))  # 120 packets = 1.2 s after

    def test_nothing_collected_when_switched_off(self):
        self.worker.config['collect_samples'] = False
        self.feed([[('marker', 0.6, False)], [('marker', 0.2, False)], [('marker', 0.95, True)]])
        self.assertEqual(self.worker.collector.pending_count(), 0)

    def test_not_written_while_busy(self):
        self.feed([[('marker', 0.95, True)]])
        with tempfile.TemporaryDirectory() as folder:
            self.worker.config['samples_path'] = folder
            self.worker.busy = True
            self.worker.flush_samples()
            self.assertEqual(os.listdir(folder), [])
            self.worker.busy = False
            self.worker.flush_samples()
            self.assertEqual(len(os.listdir(os.path.join(folder, 'tapedeck_marker'))), 2)


if __name__ == '__main__':
    unittest.main()
