"""Turns raw wake-word detections into commands to execute.

- One spoken phrase is usually detected over several consecutive frames - detections of the same
  command within `dedup_s` count as that one utterance.
- Commands in `confirm_commands` (by default "stop": ending a recording by mistake is the one
  costly false trigger) only fire when said twice within `confirm_window_s`.
"""
import time

FIRE = 'fire'
AWAIT_CONFIRM = 'await_confirm'
IGNORED = 'ignored'


class CommandGate:
    def __init__(self, dedup_s=1.5, confirm_commands=('stop',), confirm_window_s=5.0, clock=time.monotonic):
        self.dedup_s = dedup_s
        self.confirm_commands = set(confirm_commands)
        self.confirm_window_s = confirm_window_s
        self.clock = clock
        self._last_utterance = {}
        self._armed = {}

    def feed(self, command):
        now = self.clock()
        last = self._last_utterance.get(command)
        if last is not None and now - last < self.dedup_s:
            return IGNORED
        self._last_utterance[command] = now

        if command not in self.confirm_commands:
            return FIRE
        armed_at = self._armed.pop(command, None)
        if armed_at is not None and now - armed_at <= self.confirm_window_s:
            return FIRE
        self._armed[command] = now
        return AWAIT_CONFIRM
