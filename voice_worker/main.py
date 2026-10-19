"""The voice-control worker: listens to one input channel and turns spoken commands into recorder
actions. Started (and stopped) by the plugin's Django side (supervisor.py) in the plugin's own
Python environment - see README.md.

Every few seconds it re-reads what to do from the recorder's API:
- which template counts: the running recording's, otherwise the last one selected in the UI;
- whether voice control is on for that template and which channel to listen to;
- which wake-word model stands for which command (plugin settings).
It then keeps the controller's audio tap for that channel alive and processes the audio.
"""
import datetime
import json
import logging
import os
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
TAP_HEADER = 16
MAX_RECENT = 10


def _template_id(url_or_id):
    if url_or_id in (None, ''):
        return None
    if isinstance(url_or_id, int):
        return url_or_id
    return int(str(url_or_id).rstrip('/').split('/')[-1])


class Worker:
    def __init__(self, api, plugin_name, wakewords_dir, status_file):
        self.api = api
        self.plugin = plugin_name
        self.wakewords_dir = wakewords_dir
        self.status_file = status_file
        self.config = {}
        self.mapping = {}
        self.detector = None
        self.gate = CommandGate()
        self.decimator = Decimator()
        self.sock = None
        self.port = None
        self.target = None  # {template_id, template_name, channel_no, device_index, recording}
        self.recent = []
        self.state = 'startet'
        self.error = ''
        self.last_seq = None
        self.refresh_due = 0.0

    # --- status ------------------------------------------------------------------------------

    def write_status(self):
        status = {
            'updated': datetime.datetime.now().isoformat(timespec='seconds'),
            'state': self.state,
            'error': self.error,
            'template': (self.target or {}).get('template_name'),
            'channel_no': (self.target or {}).get('channel_no'),
            'recent': self.recent,
        }
        tmp = self.status_file + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(status, f, ensure_ascii=False)
        os.replace(tmp, self.status_file)

    def remember(self, command, prob, result):
        self.recent.insert(0, {
            'time': datetime.datetime.now().strftime('%H:%M:%S'),
            'command': command, 'probability': round(prob, 2), 'result': result,
        })
        del self.recent[MAX_RECENT:]
        logger.info('%s (%.2f): %s', command, prob, result)
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
            self.detector = CommandDetector(mapping, self.wakewords_dir) if any(mapping.values()) else None
            logger.info('Wake-word models: %s', mapping)

        port = int(self.config.get('udp_port') or 47100)
        if port != self.port:
            if self.sock:
                self.sock.close()
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.bind(('127.0.0.1', port))
            self.sock.settimeout(0.2)
            self.port = port

        recording = self.api.active_recording()
        if recording and recording.get('source') == 'soundcheck':
            recording = None  # voice control is for real recordings, not in-ear soundchecks
        if recording:
            template_id = _template_id(recording.get('template'))
        else:
            template_id = _template_id(self.api.get('/recorder-settings/').get('last_template'))
        target = None
        if template_id:
            values = self.api.template_config(self.plugin, template_id) or {}
            if values.get('enabled') and values.get('channel_no'):
                template = self.api.get(f'/templates/{template_id}/')
                target = {
                    'template_id': template_id,
                    'template': template,
                    'template_name': template['name'],
                    'channel_no': int(values['channel_no']),
                    'recording': recording,
                    'device_index': None,
                }
                if not recording and self.config.get('listen_while_idle', True):
                    target['device_index'] = self._idle_device()
        self.target = target

        if not self.config.get('enabled') or target is None or self.detector is None:
            self._release_tap()
            self.state = ('aus' if not self.config.get('enabled')
                          else 'keine Wake-Word-Modelle gewählt' if self.detector is None
                          else 'Vorlage ohne Sprachsteuerung')
        else:
            self.api.put(f'/audio-taps/{self.plugin}/', {
                'channel_no': target['channel_no'], 'udp_port': self.port, 'device_index': target['device_index'],
            })
            self.state = 'hört zu (Aufnahme läuft)' if recording else 'hört zu'
        self.error = ''

    def _idle_device(self):
        """Index of the interface the last recording used - resolved by name, since PortAudio
        indices can change when devices are re-plugged."""
        latest = self.api.latest_recording()
        if not latest or not latest.get('audiodevice_name'):
            return None
        for dev in self.api.get('/audiodevice/'):
            if dev.get('name') == latest['audiodevice_name']:
                return dev.get('index')
        return None

    def _release_tap(self):
        try:
            self.api.delete(f'/audio-taps/{self.plugin}/')
        except ApiError:
            pass

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

    def handle_packet(self, data):
        if len(data) <= TAP_HEADER or data[:4] != b'XTAP' or self.detector is None:
            return
        seq = int.from_bytes(data[8:12], 'little')
        if self.last_seq is not None and seq != self.last_seq + 1:
            # Gap (or a new tap): start the models from a clean state instead of stitching
            # together audio that doesn't belong together.
            self.decimator.reset()
            self.detector.reset()
        self.last_seq = seq
        samples = np.frombuffer(data[TAP_HEADER:], dtype='<f4')
        for command, prob in self.detector.process(to_pcm16(self.decimator.process(samples))):
            verdict = self.gate.feed(command)
            if verdict == FIRE:
                try:
                    self.remember(command, prob, self.act(command))
                except ApiError as e:
                    self.remember(command, prob, f'Fehler: {e}')
                self.detector.reset()
                self.refresh_due = 0.0  # pick up the new recording state right away
            elif verdict == AWAIT_CONFIRM:
                self.remember(command, prob, 'zur Bestätigung nochmal sagen')

    def run(self, should_run):
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
            if self.sock is None:
                time.sleep(0.5)
                continue
            try:
                data = self.sock.recv(4096)
            except socket.timeout:
                continue
            self.handle_packet(data)
        self._release_tap()
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
