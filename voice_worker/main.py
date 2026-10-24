"""The voice-control worker: listens to one input channel and turns spoken commands into recorder
actions. Started (and stopped) by the plugin's Django side (supervisor.py) in the plugin's own
Python environment - see README.md.

Every few seconds it re-reads what to do from the recorder's API:
- which template counts: the running recording's, otherwise the last one selected in the UI;
- whether voice control is on for that template and which channels (up to 4) to listen to;
- which wake-word model stands for which command (plugin settings).
It then keeps one controller audio tap per channel alive and processes the audio. Each channel has
its own detector state; the command gate is shared, so one phrase picked up by two microphones
still counts once.
"""
import datetime
import json
import logging
import os
import select
import signal
import socket
import sys
import time

import numpy as np

from .detector import CommandDetector
from .gate import AWAIT_CONFIRM, FIRE, CommandGate
from .recorder_api import ApiError, RecorderApi
from .resample import Decimator, to_pcm16

logger = logging.getLogger('voice_worker')

COMMANDS = ('start', 'stop', 'marker', 'next')
REFRESH_INTERVAL_S = 3.0
# How often the idle device is looked up again by name. Each lookup makes the web process
# re-initialize PortAudio, far too heavy for every refresh.
DEVICE_LOOKUP_INTERVAL_S = 30.0
TAP_HEADER = 16
MAX_RECENT = 10
# The controller serves at most 4 audio taps (MAX_TAPS in its controller.c), one UDP port each.
MAX_CHANNELS = 4
RECORDING_STATES = (0, 1)  # Recording.NEW / RECORD - anything else active is a playback


def _channels(values):
    """The template's voice channels in order, without gaps or duplicates."""
    channels = []
    for ch in values.get('channels') or []:
        if ch not in (None, '') and int(ch) not in channels:
            channels.append(int(ch))
    return channels


def _template_id(url_or_id):
    if url_or_id in (None, ''):
        return None
    if isinstance(url_or_id, int):
        return url_or_id
    return int(str(url_or_id).rstrip('/').split('/')[-1])


class Listener:
    """One tap slot: its UDP socket and the audio state of the channel it currently receives."""

    def __init__(self, slot, consumer, port):
        self.slot = slot
        self.consumer = consumer
        self.port = port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(('127.0.0.1', port))
        self.sock.setblocking(False)
        self.channel_no = None
        self.detector = None
        self.decimator = Decimator()
        self.last_seq = None

    def assign(self, channel_no, mapping, wakewords_dir):
        """(Re)start listening to `channel_no` with the models in `mapping` - fresh audio state
        whenever either changes, never stitched to what came before."""
        self.channel_no = channel_no
        self.detector = CommandDetector(mapping, wakewords_dir) if any(mapping.values()) else None
        self.decimator = Decimator()
        self.last_seq = None

    def close(self):
        self.sock.close()


class Worker:
    def __init__(self, api, plugin_name, wakewords_dir, status_file):
        self.api = api
        self.plugin = plugin_name
        self.wakewords_dir = wakewords_dir
        self.status_file = status_file
        self.config = {}
        self.mapping = {}
        self.detector = None  # only tells whether any model is chosen; listeners have their own
        self.gate = CommandGate()
        self.listeners = []  # one per tap slot in use, see _sync_listeners
        self.base_port = None
        self.busy = False  # a recording or playback is running
        self.target = None  # {template_id, template_name, channels, device_index, recording}
        self.recent = []
        self.state = 'startet'
        self.error = ''
        self.refresh_due = 0.0
        self.idle_device_name = None
        self.idle_device_index = None
        self.idle_lookup_due = 0.0

    # --- status ------------------------------------------------------------------------------

    def write_status(self):
        status = {
            'updated': datetime.datetime.now().isoformat(timespec='seconds'),
            'state': self.state,
            'error': self.error,
            'template': (self.target or {}).get('template_name'),
            'channels': (self.target or {}).get('channels', []),
            'recent': self.recent,
        }
        tmp = self.status_file + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(status, f, ensure_ascii=False)
        os.replace(tmp, self.status_file)

    def remember(self, command, prob, result, channel_no):
        self.recent.insert(0, {
            'time': datetime.datetime.now().strftime('%H:%M:%S'),
            'command': command, 'probability': round(prob, 2), 'result': result, 'channel_no': channel_no,
        })
        del self.recent[MAX_RECENT:]
        logger.info('%s (%.2f, Kanal %s): %s', command, prob, channel_no, result)
        self.write_status()

    # --- configuration -----------------------------------------------------------------------

    def refresh(self):
        self.config = self.api.plugin_config(self.plugin)
        self.gate.dedup_s = self.config.get('dedup_ms', 1500) / 1000.0
        self.gate.confirm_window_s = self.config.get('confirm_window_s', 5)
        self.gate.confirm_commands = {'stop'} if self.config.get('stop_needs_confirmation', True) else set()

        mapping = {cmd: self.config.get(f'model_{cmd}') or '' for cmd in COMMANDS}
        if mapping != self.mapping:
            self.mapping = mapping
            # Loaded once here to fail early on a bad model file; listeners load their own.
            self.detector = CommandDetector(mapping, self.wakewords_dir) if any(mapping.values()) else None
            for listener in self.listeners:
                listener.assign(listener.channel_no, mapping, self.wakewords_dir)
            logger.info('Wake-word models: %s', mapping)

        base_port = int(self.config.get('udp_port') or 47100)
        if base_port != self.base_port:
            self._sync_listeners([])
            self.base_port = base_port

        active = self.api.active_recording()
        if active and active.get('source') == 'soundcheck':
            active = None  # voice control is for real recordings, not in-ear soundchecks
        recording = active if active and active.get('state') in RECORDING_STATES else None
        self.busy = active is not None
        if active:
            template_id = _template_id(active.get('template'))
        else:
            template_id = _template_id(self.api.get('/recorder-settings/').get('last_template'))
        target = None
        if template_id:
            values = self.api.template_config(self.plugin, template_id) or {}
            channels = _channels(values)
            if values.get('enabled') and channels:
                template = self.api.get(f'/templates/{template_id}/')
                target = {
                    'template_id': template_id,
                    'template': template,
                    'template_name': template['name'],
                    'channels': channels,
                    'recording': recording,
                    'device_index': None,
                }
                if not active and self.config.get('listen_while_idle', True):
                    target['device_index'] = self._idle_device()
        self.target = target

        if not self.config.get('enabled') or target is None or self.detector is None:
            self._sync_listeners([])
            self.state = ('aus' if not self.config.get('enabled')
                          else 'keine Wake-Word-Modelle gewählt' if self.detector is None
                          else 'Vorlage ohne Sprachsteuerung')
        else:
            self._sync_listeners(target['channels'])
            for listener in self.listeners:
                self.api.put(f'/audio-taps/{listener.consumer}/', {
                    'channel_no': listener.channel_no, 'udp_port': listener.port,
                    'device_index': target['device_index'],
                })
            self.state = ('hört zu (Aufnahme läuft)' if recording
                          else 'pausiert (Wiedergabe läuft)' if active else 'hört zu')
        self.error = ''

    def _consumer(self, slot):
        # The first slot keeps the plugin's own name, as before multi-channel support.
        return self.plugin if slot == 0 else f'{self.plugin}-{slot + 1}'

    def _sync_listeners(self, channels):
        """One listener per wanted channel; slots no longer needed give their tap back."""
        channels = channels[:MAX_CHANNELS]
        while len(self.listeners) > len(channels):
            listener = self.listeners.pop()
            self._release_tap(listener.consumer)
            listener.close()
        for slot, channel_no in enumerate(channels):
            if slot == len(self.listeners):
                self.listeners.append(Listener(slot, self._consumer(slot), self.base_port + slot))
                self.listeners[slot].assign(channel_no, self.mapping, self.wakewords_dir)
            elif self.listeners[slot].channel_no != channel_no:
                self.listeners[slot].assign(channel_no, self.mapping, self.wakewords_dir)

    def _idle_device(self):
        """Index of the interface the last recording used - resolved by name, since PortAudio
        indices can change when devices are re-plugged.

        The device list only shows an interface whose input can be opened, so it's missing for
        exactly as long as the controller listens on it for us. Forgetting the index then made the
        tap flip between the device and none every few seconds, and the controller open and close
        the interface just as often (found live 2026-10-19) - so the last index found for the same
        name is kept until a lookup finds it somewhere else."""
        latest = self.api.latest_recording()
        name = (latest or {}).get('audiodevice_name')
        if not name:
            return None
        now = time.monotonic()
        if name == self.idle_device_name and now < self.idle_lookup_due:
            return self.idle_device_index
        self.idle_lookup_due = now + DEVICE_LOOKUP_INTERVAL_S
        try:
            devices = self.api.get('/audiodevice/')
        except ApiError as e:
            logger.warning('device lookup failed: %s', e)
            devices = []
        index = next((d.get('index') for d in devices if d.get('name') == name), None)
        if index is not None or name != self.idle_device_name:
            self.idle_device_index = index
        self.idle_device_name = name
        return self.idle_device_index

    def _release_tap(self, consumer):
        try:
            self.api.delete(f'/audio-taps/{consumer}/')
        except ApiError:
            pass

    def _release_taps(self):
        """Every slot this plugin could hold - also ones a previous run left behind."""
        for slot in range(MAX_CHANNELS):
            self._release_tap(self._consumer(slot))

    # --- actions -----------------------------------------------------------------------------

    def act(self, command):
        recording = self.target['recording'] if self.target else None
        announcement = self.config.get('announcement_ms', 2500) / 1000.0
        if command == 'start':
            if recording:
                return 'ignoriert: Aufnahme läuft schon'
            return self._start_recording()
        if not recording:
            return 'ignoriert: keine Aufnahme aktiv'
        if command == 'stop':
            self.api.post(f"/recordings/{recording['id']}/stop/")
            return 'Aufnahme gestoppt'
        action = 'toggle' if command == 'marker' else 'next'
        result = self.api.post(f"/recordings/{recording['id']}/marker_action/",
                               {'action': action, 'announcement_seconds': announcement})
        names = ', '.join(('Start ' + (m['name'] or '(ohne Name)')) if m['marker_type'] == 1 else 'Ende'
                          for m in result['created'])
        return f'Marker: {names}'

    def _start_recording(self):
        """x32-recorder picks channels, device and name exactly like its UI would for the template
        (recordings/start_from_template/) - the worker only says which template."""
        rec = self.api.post('/recordings/start_from_template/', {'template_id': self.target['template_id']})
        return f"Aufnahme gestartet: {rec.get('name') or '(ohne Name)'}"

    # --- audio -------------------------------------------------------------------------------

    def handle_packet(self, listener, data):
        if len(data) <= TAP_HEADER or data[:4] != b'XTAP' or listener.detector is None:
            return
        seq = int.from_bytes(data[8:12], 'little')
        if listener.last_seq is not None and seq != listener.last_seq + 1:
            # Gap (or a new tap): start the models from a clean state instead of stitching
            # together audio that doesn't belong together.
            listener.decimator.reset()
            listener.detector.reset()
        listener.last_seq = seq
        samples = np.frombuffer(data[TAP_HEADER:], dtype='<f4')
        for command, prob in listener.detector.process(to_pcm16(listener.decimator.process(samples))):
            verdict = self.gate.feed(command)
            if verdict == FIRE:
                try:
                    self.remember(command, prob, self.act(command), listener.channel_no)
                except ApiError as e:
                    self.remember(command, prob, f'Fehler: {e}', listener.channel_no)
                for other in self.listeners:
                    if other.detector is not None:
                        other.detector.reset()
                self.refresh_due = 0.0  # pick up the new recording state right away
            elif verdict == AWAIT_CONFIRM:
                self.remember(command, prob, 'zur Bestätigung nochmal sagen', listener.channel_no)

    def run(self, should_run):
        self._release_taps()
        while should_run():
            now = time.monotonic()
            if now >= self.refresh_due:
                self.refresh_due = now + REFRESH_INTERVAL_S
                try:
                    self.refresh()
                except Exception as e:  # API down, bad model file, ... - report and keep trying
                    self.error = str(e)
                    self.state = 'Fehler'
                    logger.warning('refresh failed: %s', e)
                self.write_status()
            if not self.listeners:
                time.sleep(0.5)
                continue
            by_sock = {listener.sock: listener for listener in self.listeners}
            readable, _, _ = select.select(list(by_sock), [], [], 0.2)
            for sock in readable:
                while True:
                    try:
                        data = sock.recv(4096)
                    except (BlockingIOError, InterruptedError):
                        break
                    self.handle_packet(by_sock[sock], data)
        self._sync_listeners([])
        self.state = 'beendet'
        self.write_status()


def main():
    logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s %(name)s: %(message)s',
                        stream=sys.stdout)
    base = os.environ.get('RECORDER_API', 'http://127.0.0.1/api')
    plugin = os.environ.get('VOICE_PLUGIN_NAME', 'x32_recorder_voice_plugin')
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    worker = Worker(RecorderApi(base), plugin,
                    wakewords_dir=os.path.join(here, 'wakewords'),
                    status_file=os.environ.get('VOICE_STATUS_FILE', os.path.join(here, 'status.json')))

    running = [True]

    def stop(*_):
        running[0] = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    logger.info('Voice worker started (API %s)', base)
    worker.run(lambda: running[0])
    logger.info('Voice worker stopped')


if __name__ == '__main__':
    main()
