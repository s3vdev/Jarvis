"""Jarvis-only Hermes conversation using the installed default profile.

Never use global -z: it bypasses approvals. Only the terminal toolset is
exposed; flagged commands fail closed in noninteractive single-query mode.
"""
import json
import os
from pathlib import Path
import re
import select
import subprocess
import threading

from jarvis_config import find_hermes, load_config, public_hermes
from memory_store import load_notes


class BridgeError(RuntimeError):
    pass


_PERSONA = (
    'Du bist Jarvis, ein Sprachassistent. Antworte kurz und natürlich auf Deutsch ohne Markdown. '
    'Das ist ein Gespräch: verstehe die Absicht, auch wenn die Aufnahme undeutlich ist, '
    'Namen verdreht klingen oder der Satz unvollständig wirkt. '
    'Ergänze Offensichtliches aus dem Gespräch. Frage nur nach, wenn wirklich nichts Sinnvolles erkennbar ist. '
    'Bitte nie darum, etwas einzutippen. Ist die Aufgabe klar, erledige sie. '
    'Recherchiere Fakten, Personen, Orte, Wetter und Nachrichten selbst und sage das Ergebnis. '
    'Öffne dafür keinen Browser, keine Datei und kein Programm per Werkzeug. '
    'Führe nur ausdrücklich angeforderte Aktionen aus. '
    'Behalte alle Hermes-Sicherheitsprüfungen bei. Umgehe niemals eine Verweigerung. '
    'Wenn eine Änderung eine Freigabe braucht, sag nur: Das geht von hier aus nicht. '
    'Eine Frage, Suche oder Auskunft ist das nicht. '
    'Nicht auf ein Terminal, Hermes-Fenster oder Eintippen verweisen. '
    'Keine Änderung an Hermes-Konfiguration oder Profilen. '
    'Erfinde keine persönlichen Angaben. Nutze nur Erinnerungen, die der Nutzer '
    'gespeichert hat. Schreibe das Gedächtnis nicht selbst. '
    'Behaupte Aktionen nur mit erfolgreichem Werkzeugergebnis.'
)

# Library logs go to stderr. Protocol lines stay on the original stdout, saved as fd 3.
_WORKER_BOOT = r'''
import os, sys, runpy
os.environ.pop("PYTHONHOME", None)
os.environ.pop("PYTHONPATH", None)
os.environ.pop("VIRTUAL_ENV", None)
os.dup2(1, 3)
os.dup2(2, 1)
sys.path.insert(0, os.environ["JARVIS_HERMES_AGENT"])
os.environ["HERMES_HOME"] = os.environ.get("HERMES_HOME") or str(__import__("hermes_constants").get_default_hermes_root())
import hermes_bootstrap
sys.argv = sys.argv[1:]
try:
    runpy.run_path(sys.argv[0], run_name="__main__")
except SystemExit:
    raise
except BaseException as exc:
    os.write(3, (__import__("json").dumps({"ready": False, "ok": False, "error": str(exc)}) + chr(10)).encode())
    raise
'''


class HermesBridge:
    def __init__(self, root, session_file=None, executable=None, reuse_session=True):
        self.root = Path(root).resolve()
        self.session_file = Path(session_file or self.root / '.run/hermes-session.json')
        self.executable = executable or find_hermes()
        self.session_id = None
        self._approvals_ok = False
        self._introduced = False
        self._client = None
        self._lock = threading.Lock()
        if reuse_session and self.session_file.exists():
            try:
                state = json.loads(self.session_file.read_text(encoding='utf-8'))
                sid = state['session_id']
                if (state.get('root') != str(self.root) or
                        not isinstance(sid, str) or not re.fullmatch(r'\d{8}_\d{6}_[0-9a-f]+', sid)):
                    raise ValueError('invalid session')
                self.session_id = sid
                self._introduced = True
            except (ValueError, KeyError, OSError) as exc:
                raise BridgeError('Jarvis-Sitzungsdatei ungültig. Nicht auf eine fremde Sitzung zurückgefallen.') from exc

    def ask(self, text):
        try:
            return self._ask(text)
        except (subprocess.TimeoutExpired, TimeoutError, OSError) as exc:
            self._drop_client()
            raise BridgeError('Hermes ist nicht erreichbar oder hat das Zeitlimit überschritten. Keine automatische Wiederholung.') from exc

    def status(self):
        """What the settings panel can show: found on disk, worker process alive."""
        client = self._client
        alive = client is not None and getattr(client, 'proc', None) is not None and client.proc.poll() is None
        info = public_hermes({'found': bool(self.executable), 'connected': alive})
        return info

    def warmup(self):
        """Load Hermes while speech recognition loads. The first question then skips process startup."""
        try:
            self._ensure_client()
        except BridgeError as exc:
            print("[Hermes]", exc)

    def _ask(self, text):
        if not self.executable:
            raise BridgeError('Hermes wurde nicht gefunden. Bitte Hermes im Terminal prüfen.')
        env = self._child_env()
        self._ensure_approvals([self.executable, '-p', load_config()['profile']], env)
        if not self._introduced:
            self._introduced = True
            spoken = text
            text = _PERSONA + '\n\nArbeitsordner: ' + str(self.root) + '.'
            notes = load_notes()
            if notes:
                text += '\n\nErinnerungen, die der Nutzer gespeichert hat:\n' + notes
            text += '\n\nNutzer: ' + spoken
        reply = self._ensure_client().ask(text)
        self._remember(reply)
        return reply['text'].strip()

    def _child_env(self):
        env = dict(os.environ)
        # Do not inherit another agent's conversation or its approval bypass.
        for key in ('HERMES_YOLO_MODE', 'HERMES_ACCEPT_HOOKS', 'HERMES_SESSION_KEY',
                    'HERMES_SESSION_ID', 'HERMES_GATEWAY_SESSION', 'HERMES_CRON_SESSION',
                    'HERMES_EXEC_ASK', 'HERMES_INTERACTIVE', 'HERMES_KANBAN_TASK',
                    'HERMES_QUIET_TURN_REPORT_FILE', 'HERMES_TURN_AUTHOR'):
            env.pop(key, None)
        env['TERMINAL_CWD'] = str(self.root)
        env['HERMES_SINGLE_QUERY_SESSION'] = '1'
        env['HERMES_IGNORE_RULES'] = '1'
        return env

    def worker_argv(self, python, agent_dir):
        """Command for the warm Hermes process. Never includes -z or --yolo."""
        worker = str(Path(__file__).with_name('hermes_worker.py'))
        cfg = load_config()
        cmd = [python, '-I', '-c', _WORKER_BOOT, worker,
               '--model', cfg['model'], '--provider', cfg['provider'],
               '--workdir', str(self.root)]
        if self.session_id:
            cmd += ['--resume', self.session_id]
        return cmd

    def _ensure_client(self):
        with self._lock:
            if self._client is not None:
                return self._client
            python, agent_dir = self._runtime()
            env = self._child_env()
            env['JARVIS_HERMES_AGENT'] = agent_dir
            log_path = self.root / '.run' / 'hermes-worker.log'
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log = open(log_path, 'a', encoding='utf-8')
            try:
                proc = subprocess.Popen(
                    self.worker_argv(python, agent_dir), cwd=str(self.root), env=env,
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log)
            finally:
                log.close()
            client = _HermesClient(proc)
            try:
                ready = client.read(timeout=120)
            except (TimeoutError, OSError):
                client.close()
                raise
            if not ready.get('ready'):
                client.close()
                raise BridgeError(ready.get('error') or 'Hermes ist nicht bereit.')
            self._client = client
            return client

    def _drop_client(self):
        client = self._client
        self._client = None
        close = getattr(client, 'close', None)
        if close:
            close()

    def _runtime(self):
        completed = subprocess.run(
            [self.executable, '--print-runtime-command'], cwd=str(self.root),
            capture_output=True, text=True, timeout=30)
        if completed.returncode:
            raise BridgeError('Die Hermes-Laufzeit konnte nicht ermittelt werden.')
        try:
            command = json.loads(completed.stdout)
            source = command[3]
        except (ValueError, IndexError, TypeError) as exc:
            raise BridgeError('Die Hermes-Laufzeit konnte nicht ermittelt werden.') from exc
        match = re.search(r"sys\.path\.insert\(0, '([^']+)'\)", source)
        if not match:
            raise BridgeError('Die Hermes-Laufzeit konnte nicht ermittelt werden.')
        return command[0], match.group(1)

    def _remember(self, reply):
        sid = reply.get('session_id')
        if not isinstance(sid, str) or not re.fullmatch(r'\d{8}_\d{6}_[0-9a-f]+', sid):
            raise BridgeError('Hermes hat keine gültige Sitzungs-ID geliefert.')
        if self.session_id and sid != self.session_id:
            raise BridgeError('Hermes hat unerwartet die Sitzung gewechselt. Antwort verworfen.')
        self.session_id = sid
        self.session_file.parent.mkdir(parents=True, exist_ok=True)
        temp = self.session_file.with_suffix('.tmp')
        temp.write_text(json.dumps({'root': str(self.root), 'session_id': sid}), encoding='utf-8')
        temp.chmod(0o600)
        temp.replace(self.session_file)

    def _ensure_approvals(self, base, env):
        """Check the unattended approval policy once per process, then reuse it.

        A fresh Hermes process costs about two seconds. Voice turns stay fail-closed:
        an unsafe policy still blocks the first question and is never cached.
        """
        if self._approvals_ok:
            return
        policy = subprocess.run(base + ['config', 'get', 'approvals'], cwd=str(self.root),
                                env=env, capture_output=True, text=True, timeout=30)
        if (policy.returncode or not re.search(r'^mode: (smart|manual)\s*$', policy.stdout, re.M)
                or not re.search(r'^single_query_mode: deny\s*$', policy.stdout, re.M)):
            raise BridgeError('Jarvis startet keine Werkzeuge: Hermes-Freigaben müssen smart oder manual und single_query_mode: deny sein. Globale Einstellungen wurden nicht geändert.')
        self._approvals_ok = True


class _HermesClient:
    """One warm Hermes process. A failed turn is not sent again."""

    def __init__(self, proc):
        self.proc = proc

    def read(self, timeout):
        ready, _, _ = select.select([self.proc.stdout], [], [], timeout)
        if not ready:
            raise TimeoutError('Hermes hat nicht rechtzeitig geantwortet.')
        line = self.proc.stdout.readline()
        if not line:
            raise OSError('Hermes-Prozess ist beendet.')
        try:
            payload = json.loads(line.decode('utf-8'))
        except ValueError as exc:
            raise OSError('Hermes hat kein JSON geliefert.') from exc
        if not isinstance(payload, dict):
            raise OSError('Hermes hat kein JSON geliefert.')
        return payload

    def close(self):
        if self.proc.poll() is None:
            self.proc.terminate()
        try:
            self.proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.proc.kill()

    def ask(self, text):
        if self.proc.poll() is not None:
            raise OSError('Hermes-Prozess ist beendet.')
        self.proc.stdin.write((json.dumps({'text': text}, ensure_ascii=False) + '\n').encode('utf-8'))
        self.proc.stdin.flush()
        payload = self.read(timeout=90)
        if not payload.get('ok') or not str(payload.get('text') or '').strip():
            raise BridgeError(payload.get('error') or 'Hermes hat keine abschließende Antwort geliefert.')
        return payload
