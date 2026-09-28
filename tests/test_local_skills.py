from datetime import datetime
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'voice-line'))

from local_skills import (
    execute_action, find_file, is_safe_file, match_skill, next_volume,
    public_confirm, safe_url, set_file_roots, clock_text,
)


class LocalSkillTests(unittest.TestCase):
    def test_clock_and_timer_and_repeat(self):
        self.assertEqual(match_skill('Wie spät ist es?')['kind'], 'clock')
        self.assertEqual(match_skill('welcher Tag ist heute')['what'], 'date')
        self.assertEqual(match_skill('nochmal')['kind'], 'repeat')
        timer = match_skill('stelle einen Timer auf 5 Minuten')
        self.assertEqual(timer, {'kind': 'timer', 'seconds': 300})
        self.assertEqual(match_skill('Timer aus')['kind'], 'timer_cancel')
        self.assertIsNone(match_skill('Wie wird das Wetter?'))

    def test_volume_steps_stay_in_range(self):
        self.assertEqual(next_volume('normal', 'lauter'), 'laut')
        self.assertEqual(next_volume('laut', 'lauter'), 'laut')
        self.assertEqual(next_volume('normal', 'leiser'), 'leise')
        self.assertEqual(next_volume('leise', 'Lautstärke laut'), 'laut')

    def test_only_allowlisted_apps_and_https_urls(self):
        self.assertEqual(match_skill('öffne Safari')['app'], 'Safari')
        self.assertIsNone(match_skill('öffne Calculator'))
        self.assertEqual(safe_url('wikipedia.de'), 'https://wikipedia.de')
        self.assertEqual(safe_url('file:///etc/passwd'), '')
        self.assertEqual(safe_url('http://127.0.0.1/'), '')
        self.assertTrue(match_skill('öffne wikipedia.de')['url'].startswith('https://'))

    def test_window_payload_never_includes_a_shell(self):
        shown = public_confirm({'kind': 'open_app', 'id': '1', 'app': 'Safari'})
        self.assertEqual(shown['title'], 'Safari öffnen?')
        self.assertNotIn('open', shown['title'].lower())
        self.assertIsNone(public_confirm({'kind': 'open_app', 'app': 'bash'}))

    def test_execute_uses_open_without_shell(self):
        with patch('local_skills.subprocess.run') as run:
            run.return_value.returncode = 0
            self.assertEqual(execute_action({'kind': 'open_app', 'app': 'Safari'}), 'Safari ist offen.')
            self.assertEqual(run.call_args.args[0], ['/usr/bin/open', '-a', 'Safari'])
            self.assertFalse(run.call_args.kwargs.get('shell'))
            execute_action({'kind': 'open_url', 'url': 'https://example.com'})
            self.assertEqual(run.call_args.args[0], ['/usr/bin/open', 'https://example.com'])
            self.assertEqual(execute_action({'kind': 'open_app', 'app': 'bash'}), '')
            self.assertEqual(run.call_count, 2)

    def test_local_file_open_stays_in_safe_folders(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            target = folder / 'notiz.txt'
            target.write_text('hallo')
            set_file_roots([folder])
            self.assertTrue(is_safe_file(target))
            self.assertEqual(find_file('notiz.txt'), str(target.resolve()))
            self.assertEqual(match_skill('öffne die Datei notiz.txt')['path'], str(target.resolve()))
            nested = folder / 'docs' / 'hermes-bridge-notes.md'
            nested.parent.mkdir()
            nested.write_text('notes')
            spoken = match_skill('die Hermes Bridge Notes.md Datei')
            self.assertEqual(spoken['path'], str(nested.resolve()))
            self.assertEqual(find_file('Hermes Bridge Notes.md'), str(nested.resolve()))
            self.assertIsNone(match_skill('eine Datei drin, die sollst du öffnen'))
            self.assertEqual(match_skill('öffne die Datei')['kind'], 'open_file_missing')
            self.assertIsNone(public_confirm({'kind': 'open_file', 'path': '/etc/passwd'}))
            shown = public_confirm({'kind': 'open_file', 'id': '1', 'path': str(target.resolve())})
            self.assertEqual(shown['detail'], 'notiz.txt')
            with patch('local_skills.subprocess.run') as run:
                run.return_value.returncode = 0
                self.assertEqual(
                    execute_action({'kind': 'open_file', 'path': str(target.resolve())}),
                    'Die Datei ist offen.')
                self.assertEqual(run.call_args.args[0], ['/usr/bin/open', str(target.resolve())])

    def test_clock_text_is_german(self):
        now = datetime(2026, 9, 28, 13, 11)
        self.assertEqual(clock_text(now, 'time'), 'Es ist 13 Uhr 11.')
        self.assertIn('Montag', clock_text(now, 'date'))


if __name__ == '__main__':
    unittest.main()
