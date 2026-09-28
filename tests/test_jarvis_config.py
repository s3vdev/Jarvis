from pathlib import Path
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'voice-line'))

from jarvis_config import find_hermes, load_config, public_hermes


class ConfigTests(unittest.TestCase):
    def test_defaults_come_from_repo_file(self):
        cfg = load_config()
        self.assertEqual(cfg['profile'], 'default')
        self.assertEqual(cfg['model'], 'gpt-6-astra')
        self.assertEqual(cfg['provider'], 'openai-codex')

    def test_env_overrides_are_sanitized(self):
        env = dict(os.environ)
        env['JARVIS_HERMES_MODEL'] = 'other-model'
        env['JARVIS_HERMES_PROVIDER'] = 'bad;rm -rf'
        with patch.dict(os.environ, env, clear=True):
            cfg = load_config()
        self.assertEqual(cfg['model'], 'other-model')
        self.assertEqual(cfg['provider'], 'openai-codex')

    def test_find_hermes_uses_newest_install_without_a_fixed_home(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            first = home / '.hermes' / 'installs' / 'aaa' / 'environments' / 'one' / 'venv' / 'bin' / 'hermes'
            second = home / '.hermes' / 'installs' / 'bbb' / 'environments' / 'two' / 'venv' / 'bin' / 'hermes'
            first.parent.mkdir(parents=True)
            second.parent.mkdir(parents=True)
            first.write_text('#!/bin/sh\n')
            second.write_text('#!/bin/sh\n')
            first.chmod(0o755)
            second.chmod(0o755)
            os.utime(first, (1, 1))
            os.utime(second, (2, 2))
            env = {key: value for key, value in os.environ.items() if key != 'JARVIS_HERMES'}
            env['PATH'] = '/usr/bin:/bin'
            with patch.dict(os.environ, env, clear=True), patch('jarvis_config.Path.home', return_value=home), patch('jarvis_config.shutil.which', return_value=None):
                self.assertEqual(find_hermes(), str(second))

    def test_public_hermes_keeps_safe_tokens(self):
        shown = public_hermes({'found': True, 'connected': False, 'model': 'gpt-6-astra'})
        self.assertTrue(shown['found'])
        self.assertEqual(shown['model'], 'gpt-6-astra')
        self.assertNotIn(';', shown['model'])


if __name__ == '__main__':
    unittest.main()
