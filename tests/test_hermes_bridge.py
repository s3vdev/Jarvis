import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'voice-line'))


class FakeClient:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def ask(self, text):
        self.calls.append(text)
        if isinstance(self.payload, Exception):
            raise self.payload
        from hermes_bridge import BridgeError
        if not self.payload.get('ok') or not str(self.payload.get('text') or '').strip():
            raise BridgeError(self.payload.get('error') or 'keine Antwort')
        return self.payload


class BridgeTests(unittest.TestCase):
    def _policy(self):
        return SimpleNamespace(returncode=0, stdout='mode: smart\nsingle_query_mode: deny\n', stderr='')

    def test_only_final_result_becomes_speech(self):
        self.assertTrue((ROOT / 'voice-line/hermes_bridge.py').exists(), 'Hermes bridge missing')
        self.assertTrue((ROOT / 'voice-line/hermes_worker.py').exists(), 'Hermes worker missing')
        from hermes_bridge import HermesBridge
        with tempfile.TemporaryDirectory(dir=ROOT / '.run') as tmp:
            bridge = HermesBridge(ROOT, Path(tmp) / 'session.json', executable='/local/hermes')
            bridge._client = FakeClient({
                'ok': True, 'text': 'Hallo auf Deutsch.', 'session_id': '20260927_220000_abcdef'})
            cmd = bridge.worker_argv('/local/python', '/local/agent')
            with patch('hermes_bridge.subprocess.run', return_value=self._policy()) as run:
                self.assertEqual(bridge.ask('Hallo'), 'Hallo auf Deutsch.')
            self.assertEqual(run.call_count, 1)
            self.assertEqual(run.call_args.args[0][3:], ['config', 'get', 'approvals'])
            joined = ' '.join(cmd)
            self.assertNotIn('-z', cmd)
            self.assertNotIn('--yolo', joined)
            self.assertEqual(cmd[cmd.index('--model') + 1], 'gpt-6-astra')
            self.assertEqual(cmd[cmd.index('--provider') + 1], 'openai-codex')
            self.assertNotIn('--resume', cmd)
            worker = (ROOT / 'voice-line/hermes_worker.py').read_text(encoding='utf-8')
            self.assertIn('"terminal"', worker)
            self.assertIn('HERMES_YOLO_MODE', worker)
            self.assertIn('"low"', worker)

    def test_persona_is_sent_once_then_plain_text(self):
        from hermes_bridge import HermesBridge
        with tempfile.TemporaryDirectory(dir=ROOT / '.run') as tmp:
            bridge = HermesBridge(ROOT, Path(tmp) / 'session.json', executable='/local/hermes')
            client = FakeClient({
                'ok': True, 'text': 'Hallo', 'session_id': '20260927_220000_abcdef'})
            bridge._client = client
            with patch('hermes_bridge.subprocess.run', return_value=self._policy()):
                bridge.ask('Erster Satz.')
                bridge.ask('Zweiter Satz.')
            self.assertIn('Du bist Jarvis', client.calls[0])
            self.assertNotIn('Hermes-Terminal', client.calls[0])
            self.assertIn('Das geht von hier aus nicht', client.calls[0])
            self.assertEqual(client.calls[1], 'Zweiter Satz.')

    def test_explicit_session_survives_restart_without_latest(self):
        from hermes_bridge import HermesBridge
        sid = '20260927_220000_abcdef'
        with tempfile.TemporaryDirectory(dir=ROOT / '.run') as tmp:
            session = Path(tmp) / 'session.json'
            bridge = HermesBridge(ROOT, session, '/local/hermes')
            bridge._client = FakeClient({'ok': True, 'text': 'Hallo', 'session_id': sid})
            with patch('hermes_bridge.subprocess.run', return_value=self._policy()):
                HermesBridge(ROOT, session, '/local/hermes')
                bridge.ask('Merke dir Wolke.')
            resumed = HermesBridge(ROOT, session, '/local/hermes')
            cmd = resumed.worker_argv('/local/python', '/local/agent')
            self.assertEqual(cmd[cmd.index('--resume') + 1], sid)
            self.assertNotIn('--continue', cmd)
            self.assertNotIn('latest', cmd)
            self.assertEqual(json.loads(session.read_text())['session_id'], sid)
            self.assertTrue(resumed._introduced)
            fresh = HermesBridge(ROOT, session, '/local/hermes', reuse_session=False)
            self.assertIsNone(fresh.session_id)
            self.assertNotIn('--resume', fresh.worker_argv('/local/python', '/local/agent'))

    def test_approval_policy_is_checked_once_per_bridge(self):
        from hermes_bridge import HermesBridge
        sid = '20260927_220000_abcdef'
        with tempfile.TemporaryDirectory(dir=ROOT / '.run') as tmp:
            bridge = HermesBridge(ROOT, Path(tmp) / 'session.json', executable='/local/hermes')
            bridge._client = FakeClient({'ok': True, 'text': 'Hallo', 'session_id': sid})
            with patch('hermes_bridge.subprocess.run', return_value=self._policy()) as run:
                self.assertEqual(bridge.ask('Erster Satz.'), 'Hallo')
                self.assertEqual(bridge.ask('Zweiter Satz.'), 'Hallo')
            self.assertEqual(run.call_count, 1)
            self.assertEqual(run.call_args_list[0].args[0][3:], ['config', 'get', 'approvals'])

    def test_status_reports_found_without_claiming_a_warm_worker(self):
        from hermes_bridge import HermesBridge
        with tempfile.TemporaryDirectory(dir=ROOT / '.run') as tmp:
            bridge = HermesBridge(ROOT, Path(tmp) / 'session.json', executable='/local/hermes')
            info = bridge.status()
            self.assertTrue(info['found'])
            self.assertFalse(info['connected'])
            self.assertEqual(info['model'], 'gpt-6-astra')
            self.assertEqual(info['provider'], 'openai-codex')

    def test_child_env_keeps_approvals_closed(self):
        from hermes_bridge import HermesBridge
        with tempfile.TemporaryDirectory(dir=ROOT / '.run') as tmp:
            bridge = HermesBridge(ROOT, Path(tmp) / 'session.json', executable='/local/hermes')
            env = bridge._child_env()
            self.assertEqual(env['HERMES_SINGLE_QUERY_SESSION'], '1')
            self.assertNotIn('HERMES_YOLO_MODE', env)
            self.assertNotIn('HERMES_ACCEPT_HOOKS', env)

    def test_timeout_becomes_safe_error_without_retry(self):
        from hermes_bridge import HermesBridge, BridgeError
        import subprocess
        with tempfile.TemporaryDirectory(dir=ROOT / '.run') as tmp:
            bridge = HermesBridge(ROOT, Path(tmp)/'session.json', '/local/hermes')
            with patch('hermes_bridge.subprocess.run', side_effect=subprocess.TimeoutExpired('hermes', 30)) as run:
                with self.assertRaises(BridgeError):
                    bridge.ask('Hallo')
            self.assertEqual(run.call_count, 1)

    def test_unsafe_approval_policy_fails_closed(self):
        from hermes_bridge import HermesBridge, BridgeError
        for policy in ('mode: off\nsingle_query_mode: deny\n', 'mode: smart\nsingle_query_mode: approve\n'):
            with tempfile.TemporaryDirectory(dir=ROOT / '.run') as tmp:
                bridge = HermesBridge(ROOT, Path(tmp)/'session.json', '/local/hermes')
                with patch('hermes_bridge.subprocess.run', return_value=SimpleNamespace(returncode=0,stdout=policy,stderr='')) as run:
                    with self.assertRaises(BridgeError):
                        bridge.ask('Hallo')
                self.assertEqual(run.call_count, 1)

    def test_error_or_partial_stream_is_never_speech(self):
        from hermes_bridge import HermesBridge, BridgeError
        for payload in (
            {'ok': False, 'error': 'kaputt', 'text': 'partial'},
            {'ok': True, 'text': '   ', 'session_id': '20260927_220000_abcdef'},
        ):
            with tempfile.TemporaryDirectory(dir=ROOT / '.run') as tmp:
                bridge = HermesBridge(ROOT, Path(tmp)/'session.json', '/local/hermes')
                bridge._client = FakeClient(payload)
                with patch('hermes_bridge.subprocess.run', return_value=self._policy()):
                    with self.assertRaises(BridgeError):
                        bridge.ask('Hallo')


if __name__ == '__main__':
    unittest.main()
