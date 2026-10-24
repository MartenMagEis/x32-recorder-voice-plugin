"""Tests for training/label_clips.py's decision rule (no Whisper needed):

    python -m unittest tests.test_label_clips
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'training'))

from label_clips import decide, normalize, phrase_for  # noqa: E402

OTHERS = ['tape deck record', 'tape deck finish', 'tape deck next song']


class DecideTests(unittest.TestCase):
    def label(self, text):
        return decide(phrase_for('tapedeck_marker'), normalize(text), OTHERS)[0]

    def test_phrase_and_its_spellings_are_positive(self):
        for text in ['Tape deck, marker.', 'Tapedeck marker', 'okay so tape deck marker now', 'tape deck market']:
            self.assertEqual(self.label(text), 'positiv', text)

    def test_other_commands_and_singing_are_negative(self):
        for text in ['tape deck next song', 'tape deck finish', 'and I lift your name on high']:
            self.assertEqual(self.label(text), 'negativ', text)

    def test_fragments_and_silence_stay_unclear(self):
        for text in ['', 'tape deck', 'take that marker']:
            self.assertEqual(self.label(text), 'unklar', text)


if __name__ == '__main__':
    unittest.main()
