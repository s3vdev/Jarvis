import importlib.util
import sys
from pathlib import Path
import unittest
from unittest.mock import patch
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'voice-line'))
spec = importlib.util.spec_from_file_location('voice_line', ROOT / 'voice-line/voice_line.py')
voice = importlib.util.module_from_spec(spec)
spec.loader.exec_module(voice)

class MacTests(unittest.TestCase):
    def test_german_multilingual_transcription(self):
        calls = []
        class Recognizer:
            def transcribe(self, audio, **kwargs):
                calls.append(kwargs)
                return [SimpleNamespace(text=' Guten Morgen.')], None
        with patch.object(voice, 'load_whisper', return_value=Recognizer()), patch.object(voice, 'load_notes', return_value=''):
            self.assertEqual(voice.transcribe('test.wav'), 'Guten Morgen.')
        self.assertEqual(voice.WHISPER_SIZE, 'large-v3-turbo')
        self.assertEqual(calls[0]['beam_size'], 5)
        self.assertEqual(calls[0]['language'], 'de')
        self.assertNotIn('initial_prompt', calls[0])

    def test_brain_uses_local_memory_and_default_permissions(self):
        self.assertEqual(Path(voice.VAULT_DIR), ROOT / 'memory')
        with patch.object(voice, '_brain') as brain:
            brain.ask.return_value = 'Hallo'
            self.assertEqual(voice.ask_brain('Hallo', True), 'Hallo')
            brain.ask.assert_called_once_with('Hallo')

    def test_questions_go_to_the_model(self):
        with patch.object(voice, 'handle_command', return_value=(False, 'ok')) as brain:
            self.assertEqual(
                voice.handle_turn('suche nach sven mielke aus bergneustadt', True, ''),
                (False, 'ok'))
            brain.assert_called_once_with('suche nach sven mielke aus bergneustadt', True)

    def test_default_handsfree_without_tty_never_records(self):
        with patch.object(voice.sys, 'argv', ['voice_line.py']), patch.object(voice, 'load_whisper'), patch.object(voice, 'speak'), patch('builtins.input') as pressed, patch.object(voice, 'listen') as listen, patch.object(voice, 'ensure_bus'), patch.object(voice, 'write_state'), patch.object(voice, 'write_status'), patch.object(voice, 'clear_alert'), patch.object(voice, 'wait_while_paused') as paused, patch.object(voice.sys.stdin, 'isatty', return_value=False):
            voice.main()
            listen.assert_not_called()
            pressed.assert_not_called()
            paused.assert_not_called()

    def test_daemon_without_tty_still_listens(self):
        class FakeStream:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
        with patch.object(voice.sys, 'argv', ['voice_line.py', '--daemon']), patch.object(voice, 'load_whisper'), patch.object(voice, 'speak'), patch.object(voice, 'finish_speech'), patch.object(voice, 'HermesBridge'), patch.object(voice, 'listen', side_effect=SystemExit) as listen, patch.object(voice, 'ensure_bus'), patch.object(voice, 'write_state'), patch.object(voice, 'write_status'), patch.object(voice, 'clear_alert'), patch.object(voice, 'is_paused', return_value=False), patch.object(voice, 'wait_while_paused'), patch.object(voice.sys.stdin, 'isatty', return_value=False), patch.object(voice.sd, 'InputStream', return_value=FakeStream()):
            with self.assertRaises(SystemExit):
                voice.main()
            listen.assert_called()

    def test_pause_file_closes_the_microphone(self):
        import tempfile
        from pathlib import Path as P
        with tempfile.TemporaryDirectory() as tmp:
            pause = P(tmp) / '.voice_pause'
            with patch.object(voice, 'PAUSE_FILE', str(pause)), patch.object(voice, 'write_state'), patch.object(voice, 'write_status'):
                self.assertFalse(voice.is_paused())
                pause.write_text('1')
                self.assertTrue(voice.is_paused())
                pause.unlink()
                self.assertFalse(voice.is_paused())

    def test_preview_marker_is_not_compared_to_audio_arrays(self):
        import numpy as np
        audio = np.zeros(8, dtype=np.float32)
        self.assertFalse(voice.is_preview(audio))
        self.assertTrue(voice.is_preview('preview'))
        self.assertFalse(voice.is_preview(None))

    def test_settings_keep_only_known_voices(self):
        import tempfile
        from pathlib import Path as P
        with tempfile.TemporaryDirectory() as tmp:
            path = P(tmp) / '.voice_settings'
            with patch.object(voice, 'SETTINGS_FILE', str(path)):
                self.assertEqual(voice.load_settings()['voice'], 'de-DE-ConradNeural')
                path.write_text('{"voice":"de-DE-KillianNeural","sensitivity":"leise"}')
                self.assertEqual(voice.load_settings()['voice'], 'de-DE-KillianNeural')
                path.write_text('{"voice":"de-DE-KillianNeural","sensitivity":"leise","wake":"an","volume":"leise"}')
                loaded = voice.load_settings()
                self.assertEqual(loaded['voice'], 'de-DE-KillianNeural')
                self.assertEqual(loaded['wake'], 'an')
                self.assertEqual(loaded['volume'], 'leise')
                path.write_text('{"voice":"evil","sensitivity":"off","wake":"maybe","volume":"max"}')
                self.assertEqual(voice.load_settings(), {
                    'voice': 'de-DE-ConradNeural',
                    'sensitivity': 'normal',
                    'wake': 'aus',
                    'volume': 'normal',
                    'animation': 'kugel',
                })

    def test_visualizer_pause_button_writes_only_the_pause_file(self):
        import json, os, tempfile, threading, time, urllib.request
        spec = importlib.util.spec_from_file_location('viz', ROOT / 'voice-visualizer/server.py')
        viz = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(viz)
        bus = Path(tempfile.mkdtemp())
        viz.BUS_DIR = str(bus)
        viz.STATE_FILE = str(bus / '.voice_state')
        viz.WAVEFORM_FILE = str(bus / '.voice_waveform')
        viz.ALERT_FILE = str(bus / '.voice_alert')
        viz.STATUS_FILE = str(bus / '.voice_status')
        viz.PAUSE_FILE = str(bus / '.voice_pause')
        viz.SETTINGS_FILE = str(bus / '.voice_settings')
        viz.PREVIEW_FILE = str(bus / '.voice_preview')
        viz.HERMES_FILE = str(bus / '.voice_hermes')
        viz.CONFIRM_FILE = str(bus / '.voice_confirm')
        viz.CONFIRM_REPLY_FILE = str(bus / '.voice_confirm_reply')
        viz.USAGE_FILE = str(bus / '.voice_usage')
        viz.LOAD_FILE = str(bus / '.voice_load')
        viz.set_memory_root(str(bus))
        (bus / '.voice_state').write_text('listening')
        (bus / '.voice_status').write_text('LISTENING')
        server = viz.ThreadingHTTPServer(('127.0.0.1', 0), viz.Handler)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            html = urllib.request.urlopen('http://127.0.0.1:%d/' % port, timeout=2).read().decode()
            self.assertIn('id="pauseBtn"', html)
            self.assertIn('id="bootMeter"', html)
            self.assertIn('id="bootPct"', html)
            self.assertIn('id="gear"', html)
            self.assertIn('ZUHÖREN', html)
            req = urllib.request.Request(
                'http://127.0.0.1:%d/pause' % port,
                data=json.dumps({'paused': True}).encode(),
                headers={'Content-Type': 'application/json'})
            paused = json.loads(urllib.request.urlopen(req, timeout=2).read())
            self.assertTrue(paused['paused'])
            self.assertEqual(paused['state'], 'idle')
            self.assertTrue((bus / '.voice_pause').exists())
            self.assertFalse((bus / '.voice_state').read_text() == '')
            req = urllib.request.Request(
                'http://127.0.0.1:%d/pause' % port,
                data=json.dumps({'paused': False}).encode(),
                headers={'Content-Type': 'application/json'})
            cleared = json.loads(urllib.request.urlopen(req, timeout=2).read())
            self.assertFalse(cleared['paused'])
            self.assertFalse((bus / '.voice_pause').exists())
            bad = urllib.request.Request(
                'http://127.0.0.1:%d/settings' % port,
                data=json.dumps({'voice': '<script>x</script>', 'sensitivity': 'normal'}).encode(),
                headers={'Content-Type': 'application/json'})
            with self.assertRaises(Exception):
                urllib.request.urlopen(bad, timeout=2)
            good = urllib.request.Request(
                'http://127.0.0.1:%d/settings' % port,
                data=json.dumps({
                    'voice': 'de-DE-KillianNeural', 'sensitivity': 'fest',
                    'wake': 'an', 'volume': 'leise', 'animation': 'radar'}).encode(),
                headers={'Content-Type': 'application/json'})
            saved = json.loads(urllib.request.urlopen(good, timeout=2).read())
            self.assertEqual(saved['voice'], 'de-DE-KillianNeural')
            self.assertEqual(saved['wake'], 'an')
            self.assertEqual(saved['volume'], 'leise')
            self.assertEqual(saved['animation'], 'radar')
            stored = json.loads((bus / '.voice_settings').read_text())
            self.assertEqual(stored['voice'], 'de-DE-KillianNeural')
            self.assertEqual(stored['wake'], 'an')
            html = urllib.request.urlopen('http://127.0.0.1:%d/' % port, timeout=2).read().decode()
            self.assertIn('id="wakeSel"', html)
            self.assertIn('id="volSel"', html)
            self.assertIn('id="animSel"', html)
            self.assertIn('Radar · Ringe', html)
            self.assertIn('id="hermesHint"', html)
            self.assertIn('id="confirmYes"', html)
            self.assertIn('id="usageBtn"', html)
            self.assertIn('usageFill', html)
            self.assertIn('usageTrack', html)
            self.assertIn('PERSÖNLICHES', html)
            self.assertIn('id="memBox"', html)
            self.assertIn('function typingInField', html)
            self.assertIn('node === "TEXTAREA"', html)
            mem_req = urllib.request.Request(
                'http://127.0.0.1:%d/memory' % port,
                data=json.dumps({'text': 'Ich heiße Sven.'}).encode(),
                headers={'Content-Type': 'application/json'})
            memorized = json.loads(urllib.request.urlopen(mem_req, timeout=2).read())
            self.assertTrue(memorized['ok'])
            self.assertEqual(memorized['memory']['text'], 'Ich heiße Sven.')
            settings = json.loads(urllib.request.urlopen(
                'http://127.0.0.1:%d/settings' % port, timeout=2).read())
            self.assertEqual(settings['memory']['text'], 'Ich heiße Sven.')
            secret = urllib.request.Request(
                'http://127.0.0.1:%d/memory' % port,
                data=json.dumps({'text': 'password: geheim123'}).encode(),
                headers={'Content-Type': 'application/json'})
            with self.assertRaises(Exception):
                urllib.request.urlopen(secret, timeout=2)
            (bus / '.voice_confirm').write_text(json.dumps({
                'id': 'aabbccddeeff', 'kind': 'open_app', 'app': 'Safari'}))
            state = json.loads(urllib.request.urlopen('http://127.0.0.1:%d/state' % port, timeout=2).read())
            self.assertEqual(state['confirm']['title'], 'Safari öffnen?')
            vote = urllib.request.Request(
                'http://127.0.0.1:%d/confirm' % port,
                data=json.dumps({'id': 'aabbccddeeff', 'accepted': True}).encode(),
                headers={'Content-Type': 'application/json'})
            json.loads(urllib.request.urlopen(vote, timeout=2).read())
            self.assertTrue(json.loads((bus / '.voice_confirm_reply').read_text())['accepted'])
            self.assertFalse((bus / '.voice_confirm').read_text() == '')
            (bus / '.voice_state').write_text('booting')
            (bus / '.voice_load').write_text('37')
            (bus / '.voice_status').write_text('Sprachmodell 37%')
            booting = json.loads(urllib.request.urlopen('http://127.0.0.1:%d/state' % port, timeout=2).read())
            self.assertEqual(booting['state'], 'booting')
            self.assertEqual(booting['progress'], 37)
            (bus / '.voice_hermes').write_text(json.dumps({
                'found': True, 'connected': True, 'profile': 'default',
                'model': 'gpt-6-astra', 'provider': 'openai-codex'}))
            info = json.loads(urllib.request.urlopen('http://127.0.0.1:%d/settings' % port, timeout=2).read())
            self.assertTrue(info['hermes']['found'])
            self.assertTrue(info['hermes']['connected'])
            self.assertEqual(info['hermes']['model'], 'gpt-6-astra')
        finally:
            server.shutdown()
            server.server_close()

    def test_wake_phrase_splits_the_command(self):
        self.assertEqual(voice.split_wake('Hey Jarvis, wie wird das Wetter?'), (True, 'wie wird das Wetter?'))
        self.assertEqual(voice.split_wake('Jarvis'), (True, ''))
        self.assertEqual(voice.split_wake('Hörst du mich?'), (False, ''))
        self.assertEqual(voice.split_wake('okay dscharvis was gibt es neues'), (True, 'was gibt es neues'))
        self.assertTrue(voice.is_echo('deine Nachricht kommt an', 'Ja, deine Nachricht kommt an.'))
        self.assertFalse(voice.is_echo('Wie wird das Wetter?', 'Ja, deine Nachricht kommt an.'))

    def test_spoken_stop_and_optional_wake(self):
        import tempfile
        from pathlib import Path as P
        self.assertEqual(voice.local_action('Stopp'), 'pause')
        self.assertEqual(voice.local_action('Jarvis stopp bitte'), 'pause')
        self.assertEqual(voice.local_action('Wie spät ist es?'), '')
        with tempfile.TemporaryDirectory() as tmp:
            path = P(tmp) / '.voice_settings'
            with patch.object(voice, 'SETTINGS_FILE', str(path)):
                self.assertEqual(
                    voice.command_from_utterance('wie spät ist es'),
                    ('ask', 'wie spät ist es'))
                self.assertEqual(
                    voice.command_from_utterance('Hörst du mich?'),
                    ('ask', 'Hörst du mich?'))
                self.assertEqual(voice.command_from_utterance('Stopp'), ('pause', ''))
                path.write_text('{"wake":"an"}')
                self.assertEqual(voice.command_from_utterance('Hörst du mich?'), ('ignore', ''))
                self.assertEqual(
                    voice.command_from_utterance('Jarvis, wie spät ist es?'),
                    ('ask', 'wie spät ist es?'))
                self.assertEqual(voice.command_from_utterance('Jarvis'), ('ask', ''))
        self.assertEqual(
            voice.split_spoken('Erster Satz. Zweiter Satz!'),
            ['Erster Satz.', 'Zweiter Satz!'])
        self.assertTrue(voice.needs_hermes_notice('Bitte im Hermes-Terminal die Freigabe bestätigen.'))
        self.assertFalse(voice.needs_hermes_notice('Hermes ist nicht erreichbar.'))
        self.assertEqual(
            voice.scrub_voice('Bitte im interaktiven Hermes-Terminal bestätigen.'),
            'Das geht von hier aus nicht.')
        self.assertEqual(voice.scrub_voice('Es ist 13 Uhr 11.'), 'Es ist 13 Uhr 11.')
        voice._barge_hit = True
        self.assertTrue(voice.barged())
        self.assertTrue(voice.consume_barge())
        self.assertFalse(voice.consume_barge())

    def test_launcher_starts_real_server_then_cleans_up_on_eof(self):
        import subprocess, os
        launcher = ROOT / 'launch.command'
        self.assertTrue(launcher.exists(), 'macOS launcher missing')
        env = dict(os.environ, JARVIS_NO_WINDOW='1', JARVIS_NO_BROWSER='1')
        result = subprocess.run(['/bin/bash', str(launcher)], input='', text=True, capture_output=True, env=env, timeout=180)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('JARVIS CONNECTED', result.stdout)
        self.assertNotIn('press Enter', result.stdout)
        self.assertIn('Hermes', result.stdout)
        self.assertNotIn('Claude', result.stdout)
        launcher_text = (ROOT / 'launch.command').read_text()
        self.assertNotIn("open 'http://127.0.0.1:8777/'", launcher_text)
        self.assertNotIn('/Users/svenmielke', launcher_text)
        self.assertNotIn('/Users/svenmielke', (ROOT / 'setup.command').read_text())
        self.assertTrue((ROOT / 'setup.command').exists())
        self.assertTrue((ROOT / 'NOTICE').exists())
        self.assertTrue((ROOT / 'jarvis.json').exists())
        self.assertTrue((ROOT / 'voice-visualizer/JarvisWindow.swift').exists())
        swift = (ROOT / 'voice-visualizer/JarvisWindow.swift').read_text()
        self.assertIn('500', swift)
        self.assertIn('520', swift)
        self.assertNotIn('680', swift)
        self.assertIn('NSStatusItem', swift)
        self.assertIn('statusItem', swift)
        self.assertIn('.voice_pause', swift)
        self.assertIn('windowShouldClose', swift)
        self.assertIn('applicationWillTerminate', swift)
        self.assertIn('.jarvis.pids', swift)
        self.assertIn('SIGTERM', swift)
        self.assertIn('127.0.0.1:8777/state', swift)
        self.assertIn('--daemon', launcher_text)
        self.assertIn('nohup', launcher_text)
        self.assertIn('Menüleiste', launcher_text)
        self.assertIn('dist/Jarvis.app', launcher_text)
        self.assertFalse((ROOT / '.run/visualizer.pid').exists())
        plist = (ROOT / 'macos/Info.plist').read_text()
        self.assertIn('NSMicrophoneUsageDescription', plist)
        self.assertIn('CFBundleIconFile', plist)
        self.assertIn('de.s3vdev.jarvis', plist)
        self.assertTrue((ROOT / 'macos/jarvis-app-icon.png').exists())
        self.assertTrue((ROOT / 'macos/build_app.sh').exists())
        self.assertTrue((ROOT / 'macos/launch_backend.sh').exists())
        backend = (ROOT / 'macos/launch_backend.sh').read_text()
        self.assertIn('JARVIS_HOME', backend)
        self.assertIn('JARVIS_ROOT', backend)
        self.assertNotIn('/Users/svenmielke', backend)
        self.assertIn('startBackend', swift)
        self.assertIn('JARVIS_HOME', swift)
        self.assertIn('launch_backend', swift)
        self.assertIn('NSMicrophoneUsageDescription', (ROOT / 'macos/Info.plist').read_text())

    def test_usage_shows_remaining_without_reset_or_yolo(self):
        spec = importlib.util.spec_from_file_location('viz', ROOT / 'voice-visualizer/server.py')
        viz = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(viz)
        cmd = viz.usage_argv('/local/hermes')
        self.assertEqual(cmd[-4:], ['usage', '--json', '--provider', 'openai-codex'])
        self.assertNotIn('-z', cmd)
        self.assertNotIn('--yolo', ' '.join(cmd))
        shown = viz.public_usage({
            'plan': 'Plus',
            'windows': [{
                'label': 'Session', 'used_percent': 23.0,
                'resets_at': '2026-09-28T01:38:45+00:00'}],
            'details': ['You have 2 resets banked'],
        })
        self.assertTrue(shown['ok'])
        self.assertEqual(shown['windows'][0]['left'], 77.0)
        self.assertEqual(shown['plan'], 'Plus')
        self.assertNotIn('reset_command', shown)

    def test_check_accepts_macos_ptt_dependencies(self):
        with patch.object(voice, '_hermes', '/local/hermes'):
            self.assertTrue(voice.check())

    def test_neural_german_tts_is_pcm_wave(self):
        import wave
        self.assertEqual(voice.TTS_VOICE, 'de-DE-ConradNeural')
        self.assertNotIn('pyttsx3', voice._synth_wav.__code__.co_names)
        self.assertNotIn('Eddy', voice._synth_wav.__code__.co_consts)
        path = voice._synth_wav('Guten Morgen. Heute testen wir die deutsche Spracherkennung.')
        self.assertEqual(voice._last_tts, 'edge')
        try:
            self.assertEqual(Path(path).parent, ROOT / '.run/tmp')
            with wave.open(path) as wav:
                self.assertEqual(wav.getsampwidth(), 2)
                self.assertEqual(wav.getnchannels(), 1)
                self.assertEqual(wav.getframerate(), 48000)
                self.assertGreater(wav.getnframes(), 48000)
        finally:
            Path(path).unlink(missing_ok=True)

if __name__ == '__main__':
    unittest.main()
