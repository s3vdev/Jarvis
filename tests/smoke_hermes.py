"""Opt-in real account smoke test: two inference turns, no mic or audio playback."""
import json
from pathlib import Path
import subprocess
import sys
import uuid
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'voice-line'))
import hermes_bridge
import voice_line

run_dir = ROOT / '.run' / ('hermes-smoke-' + uuid.uuid4().hex[:8])
run_dir.mkdir(parents=True)
real_run = subprocess.run
turns = []

def capture_real_run(cmd, **kwargs):
    result = real_run(cmd, **kwargs)
    if 'chat' in cmd:
        events = []
        for line in result.stdout.splitlines():
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if isinstance(record, dict):
                events.append(record)
        turns.append(events)
        (run_dir / ('turn-%d.json' % len(turns))).write_text(json.dumps(events, indent=2, ensure_ascii=False))
    return result

# Instrument only for evidence; every subprocess and provider response is real.
hermes_bridge.subprocess.run = capture_real_run
session = run_dir / 'session.json'
bridge = hermes_bridge.HermesBridge(ROOT, session)
first = bridge.ask('Merke dir nur für dieses Gespräch das Kennwort Nebelbirke. Führe ausschließlich den harmlosen Nur-Lese-Befehl /bin/pwd mit workdir %s aus. Antworte kurz auf Deutsch mit dem tatsächlichen Arbeitsverzeichnis.' % ROOT)
sid = bridge.session_id
assert str(ROOT) in first, first
# Fresh Python object reads ONLY the explicit Jarvis smoke session.
bridge = hermes_bridge.HermesBridge(ROOT, session)
second = bridge.ask('Welches Kennwort habe ich dir eben genannt? Antworte in einem kurzen deutschen Satz, ohne Werkzeugaufruf.')
assert bridge.session_id == sid
assert 'Nebelbirke' in second, second
hermes_bridge.subprocess.run = real_run
wav = voice_line._synth_wav(voice_line.for_speech(second))
with wave.open(wav) as audio:
    assert audio.getnframes() > 0 and audio.getframerate() == 48000
report = {'session_id': sid, 'first_response': first, 'continuity_response': second, 'german_response_wav': wav, 'evidence_dir': str(run_dir), 'real_tool_action': '/bin/pwd', 'microphone_recorded': False}
(run_dir / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
print(json.dumps(report, ensure_ascii=False, indent=2))
