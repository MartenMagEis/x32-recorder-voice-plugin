"""Unit tests for the Django-free worker parts. Run from the plugin folder:

    python -m unittest tests.test_worker      (needs numpy)
"""
import datetime
import unittest

try:
    import numpy as np

    from voice_worker.gate import AWAIT_CONFIRM, FIRE, IGNORED, CommandGate
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


class FakeApi:
    def __init__(self, devices):
        self.devices = devices
        self.lookups = 0

    def latest_recording(self):
        return {'audiodevice_name': 'X-USB'}

    def get(self, path):
        assert path == '/audiodevice/'
        self.lookups += 1
        return self.devices


class IdleDeviceTests(unittest.TestCase):
    def setUp(self):
        from voice_worker import main
        self.main = main
        self.api = FakeApi([{'name': 'X-USB', 'index': 1}])
        self.worker = main.Worker(self.api, 'voice', '.', 'status.json')

    def expire(self):
        self.worker.idle_lookup_due = 0.0

    def test_lookup_is_cached_between_refreshes(self):
        self.assertEqual(self.worker._idle_device(), 1)
        self.assertEqual(self.worker._idle_device(), 1)
        self.assertEqual(self.api.lookups, 1)

    def test_keeps_index_while_device_is_busy_and_unlisted(self):
        self.worker._idle_device()
        self.api.devices = []  # controller holds the input open -> not in the list
        self.expire()
        self.assertEqual(self.worker._idle_device(), 1)

    def test_follows_device_to_a_new_index(self):
        self.worker._idle_device()
        self.api.devices = [{'name': 'X-USB', 'index': 3}]
        self.expire()
        self.assertEqual(self.worker._idle_device(), 3)

    def test_failed_lookup_keeps_index(self):
        self.worker._idle_device()

        def fail(path):
            raise self.main.ApiError('PortAudio not initialized')
        self.api.get = fail
        self.expire()
        self.assertEqual(self.worker._idle_device(), 1)


class TapApi:
    """Answers the calls Worker.refresh makes; records audio-tap requests."""

    def __init__(self, channels, active=None):
        self.channels = channels
        self.active = active
        self.taps = {}

    def plugin_config(self, plugin):
        return {'enabled': True, 'model_marker': 'okay_nabu', 'udp_port': 47910, 'listen_while_idle': False}

    def active_recording(self):
        return self.active

    def template_config(self, plugin, template_id):
        return {'enabled': True, 'channels': self.channels}

    def get(self, path):
        if path == '/recorder-settings/':
            return {'last_template': 7}
        if path.startswith('/templates/'):
            return {'name': 'Combo'}
        raise AssertionError(path)

    def put(self, path, data):
        self.taps[path.split('/')[2]] = data

    def delete(self, path):
        self.taps.pop(path.split('/')[2], None)


class ChannelTests(unittest.TestCase):
    def setUp(self):
        try:
            from voice_worker import main
        except ImportError:
            raise unittest.SkipTest('needs pymicro-wakeword')
        self.api = TapApi([15, 13])
        self.worker = main.Worker(self.api, 'voice', '.', 'status.json')

    def tearDown(self):
        self.worker._sync_listeners([])

    def test_one_tap_and_port_per_channel(self):
        self.worker.refresh()
        self.assertEqual(self.api.taps, {
            'voice': {'channel_no': 15, 'udp_port': 47910, 'device_index': None},
            'voice-2': {'channel_no': 13, 'udp_port': 47911, 'device_index': None},
        })
        self.assertEqual(self.worker.state, 'hört zu')

    def test_dropped_channel_gives_its_tap_back(self):
        self.worker.refresh()
        self.api.channels = [13]
        self.worker.refresh()
        self.assertEqual(self.api.taps, {'voice': {'channel_no': 13, 'udp_port': 47910, 'device_index': None}})
        self.assertEqual(len(self.worker.listeners), 1)

    def test_playback_pauses_commands(self):
        self.api.active = {'state': 4, 'template': 7}
        self.worker.refresh()
        self.assertIsNone(self.worker.target['recording'])
        self.assertTrue(self.worker.busy)
        self.assertEqual(self.worker.state, 'pausiert (Wiedergabe läuft)')


if __name__ == '__main__':
    unittest.main()


try:
    from voice_worker.detector import WARMUP_STEPS, CommandDetector
except ImportError:  # pymicro-wakeword not installed here
    CommandDetector = None


class AlwaysOn:
    """Stand-in model that is certain on every feature step."""
    probability_cutoff = 0.5

    def process_streaming_prob(self, features):
        return 1.0

    def reset(self):
        pass


@unittest.skipIf(CommandDetector is None, 'needs pymicro-wakeword')
class DetectorWarmupTests(unittest.TestCase):
    def detector(self):
        d = CommandDetector({}, wakewords_dir='')
        d.models = {'marker': AlwaysOn()}
        return d

    def pcm(self, seconds):
        return to_pcm16(Decimator().process(tone(440, seconds)))

    def test_no_hits_until_the_frontend_has_settled(self):
        d = self.detector()
        self.assertEqual(d.process(self.pcm(WARMUP_STEPS / 100 - 0.2)), [])
        self.assertTrue(any(hit for _, _, hit in d.process(self.pcm(1.0))))

    def test_reset_starts_the_warmup_again(self):
        d = self.detector()
        d.process(self.pcm(WARMUP_STEPS / 100 + 1.0))
        d.reset()
        self.assertEqual(d.process(self.pcm(WARMUP_STEPS / 100 - 0.2)), [])
