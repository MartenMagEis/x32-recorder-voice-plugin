"""Unit tests for the Django-free worker parts. Run from the plugin folder:

    python -m unittest tests.test_worker      (needs numpy)
"""
import datetime
import unittest

try:
    import numpy as np

    from voice_worker.gate import AWAIT_CONFIRM, FIRE, IGNORED, CommandGate
    from voice_worker.names import expand_pattern
    from voice_worker.resample import Decimator, to_pcm16
except ImportError:  # inside x32-recorder's Django test run: no numpy there, and not on the path
    raise unittest.SkipTest('worker tests run standalone from the plugin folder (need numpy)')


def tone(freq, seconds=1.0, rate=48000):
    t = np.arange(int(rate * seconds)) / rate
    return (0.5 * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def rms_db(x):
    return 20 * np.log10(np.sqrt(np.mean(np.square(x))) + 1e-12)


class DecimatorTests(unittest.TestCase):
    def test_speech_band_passes_and_rate_is_a_third(self):
        out = Decimator().process(tone(440))
        self.assertEqual(out.size, 16000)
        self.assertAlmostEqual(rms_db(out[200:]), rms_db(tone(440)), delta=0.5)

    def test_cymbal_range_does_not_fold_back(self):
        # 12 kHz would alias to 4 kHz by plain sample dropping - the low-pass must kill it.
        out = Decimator().process(tone(12000))
        self.assertLess(rms_db(out[200:]) - rms_db(tone(12000)), -40)

    def test_streaming_in_10ms_packets_equals_one_shot(self):
        x = tone(440) + tone(3000) * 0.3
        one_shot = Decimator().process(x)
        d = Decimator()
        streamed = np.concatenate([d.process(x[i:i + 480]) for i in range(0, x.size, 480)])
        np.testing.assert_allclose(streamed, one_shot, atol=1e-6)

    def test_odd_packet_sizes_keep_the_sample_grid(self):
        x = tone(1000)
        one_shot = Decimator().process(x)
        d = Decimator()
        parts, i = [], 0
        for size in [100, 7, 333, 480, 1] * 200:
            if i >= x.size:
                break
            parts.append(d.process(x[i:i + size]))
            i += size
        np.testing.assert_allclose(np.concatenate(parts), one_shot[:sum(p.size for p in parts)], atol=1e-6)

    def test_pcm16_conversion_clips(self):
        pcm = np.frombuffer(to_pcm16(np.array([0.0, 1.5, -2.0], dtype=np.float32)), dtype='<i2')
        self.assertEqual(list(pcm), [0, 32767, -32767])


class GateTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        self.gate = CommandGate(dedup_s=1.5, confirm_commands=('stop',), confirm_window_s=5.0,
                                clock=lambda: self.now)

    def test_one_utterance_fires_once(self):
        self.assertEqual(self.gate.feed('marker'), FIRE)
        self.now = 0.3
        self.assertEqual(self.gate.feed('marker'), IGNORED)
        self.now = 2.0
        self.assertEqual(self.gate.feed('marker'), FIRE)

    def test_stop_needs_a_second_utterance_in_time(self):
        self.assertEqual(self.gate.feed('stop'), AWAIT_CONFIRM)
        self.now = 0.5
        self.assertEqual(self.gate.feed('stop'), IGNORED)  # same utterance, not a confirmation
        self.now = 3.0
        self.assertEqual(self.gate.feed('stop'), FIRE)

    def test_late_confirmation_starts_over(self):
        self.assertEqual(self.gate.feed('stop'), AWAIT_CONFIRM)
        self.now = 9.0
        self.assertEqual(self.gate.feed('stop'), AWAIT_CONFIRM)
        self.now = 10.0
        self.assertEqual(self.gate.feed('stop'), IGNORED)
        self.now = 11.0
        self.assertEqual(self.gate.feed('stop'), FIRE)


class NamePatternTests(unittest.TestCase):
    def test_builtins_and_wildcards(self):
        now = datetime.datetime(2026, 10, 11, 19, 5)  # a Sunday
        name = expand_pattern('{Probe} {Datum} {Wochentag} {Uhrzeit} {Vorlage} {Ort}', 'PhoeniX',
                              custom_wildcards=[{'token': 'Ort', 'value': 'Bandraum'}],
                              global_wildcards=[{'token': 'Probe', 'value': 'Probe'}], now=now)
        self.assertEqual(name, 'Probe 26-10-11 Sonntag 19-05 PhoeniX Bandraum')

    def test_empty_pattern(self):
        self.assertEqual(expand_pattern('', 'X'), '')


if __name__ == '__main__':
    unittest.main()
