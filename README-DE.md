# Jarvis auf dem Mac – Fork s3vdev/Jarvis

Jarvis ist die Sprachoberfläche. Das Modell kommt vom **Hermes auf diesem Rechner**: Profil, Provider und Anmeldung gehören der Person, die startet. Standard in `jarvis.json` ist `default` / `gpt-6-astra` / `openai-codex`. Andere Werte setzt man in `jarvis.local.json` oder mit `JARVIS_HERMES_PROFILE`, `JARVIS_HERMES_MODEL`, `JARVIS_HERMES_PROVIDER`. Keine Zugangsdaten ins Repo.

## Herkunft

Dieses Repo ist [s3vdev/Jarvis](https://github.com/s3vdev/Jarvis). Das Gesicht und die alte Voice-Line stammen aus [Sujatx/Jarvis](https://github.com/Sujatx/Jarvis). Dort liegt **keine Lizenz**. Das ist nicht alles eigener Code. Details: `NOTICE`. Screenshots: `docs/jarvis-fenster.jpg`, `docs/jarvis-einstellungen.jpg`.

## Einmal einrichten

Voraussetzungen: macOS 13+, Python 3, Xcode Command Line Tools (`swiftc`), eigenes Hermes mit Login.

```bash
cd /Pfad/zu/Jarvis
./setup.command
```

`setup.command` legt `.venv` an, installiert `requirements.txt` und sucht Hermes in `PATH`, `JARVIS_HERMES`, `~/.local/bin` oder der neuesten Installation unter `~/.hermes/installs`. Kein fest verdrahteter Benutzerpfad.

## Starten

**Jarvis starten.command** doppelklicken. Es öffnet das Terminal und das kleine Jarvis-Fenster.

- Mac-Fenster, etwa 500×520, plus Icon in der Menüleiste. Das rote Schließen blendet nur das Fenster aus; **Beenden** sitzt im Menüleisten-Menü. Oben **J.A.R.V.I.S** und **CONNECTED**, darunter die goldene Kugel. Unten **PAUSE** und **ZUHÖREN**. Das Zahnrad zeigt Hermes, Nutzung, Stimme, Mikrofon, optionalen Rufnamen, Lautstärke und Animation. Probe liegt unter der Stimme.
- Im Terminal **einfach Deutsch sprechen**. Kein Enter. Der Name ist optional. In den Einstellungen kannst du „nur mit Jarvis“ einschalten, wenn der Raum laut ist. Eine Sprechpause schickt die Frage. Du kannst ihm **ins Wort fallen**. **Stopp** oder **PAUSE** schließt das Mikrofon und bricht die Stimme ab.
- Die Nutzung kommt von `hermes usage` über das Konto auf diesem Rechner. Im Zahnrad **Aktualisieren**. Jarvis kann Limits nicht selbst erhöhen und führt keinen Reset aus.
- Uhr, Timer, Lautstärke und **nochmal** antworten sofort, ohne Hermes. Längere Hermes-Antworten spricht er satzweise, der erste Satz kommt früher.
- **Öffne Safari**, eine Website oder **öffne die Datei …**: erst **Ja** im Fenster. Gesucht wird nur auf Schreibtisch, in Dokumente, Downloads und im Jarvis-Ordner. Ein Nein oder Timeout lässt es. Fehlt eine Freigabe für etwas anderes, sagt er nur, dass es von hier aus nicht geht. Kein Verweis auf ein Hermes-Terminal.
- Das Mikrofon ist offen, solange das Terminal läuft und nicht pausiert ist. Strg+C beendet Jarvis und das Fenster.
- macOS fragt bei der ersten Aufnahme eventuell nach Mikrofonzugriff für Terminal.
- Ist Port 8777 belegt, bricht der Starter ab, ohne fremde Prozesse zu beenden.

## Was funktioniert und was nicht

- Lokale Whisper-Erkennung `base`, CPU/int8, Sprache Deutsch. Die Aufnahme endet erst nach einer etwas längeren Pause. Jeder Jarvis-Start nimmt eine frische Hermes-Sitzung.
- Hermes bleibt für die laufende Jarvis-Sitzung geladen, mit niedrigem Denkaufwand. Freigaben bleiben `smart`/`manual` und `single_query_mode: deny`.
- Stimme standardmäßig `de-DE-ConradNeural`. Im Zahnrad auch Killian und Florian. PCM-WAV mono, 16 Bit, 48 kHz. Fällt das Netz aus, spricht die lokale Stimme `Anna`.
- Hermes antwortet per Stream. Ausschließlich das erfolgreiche abschließende `result.text` geht an TTS.
- Nur Hermes-Toolset `terminal` ist aktiviert. Normale Hermes-Prüfungen bleiben aktiv. Jarvis ändert die globale Hermes-Konfiguration nicht.
- **Keine interaktive Freigabe über Sprache.** Befehle, die eine neue Freigabe erfordern, werden im nichtinteraktiven Modus verweigert.
- Niemals `hermes -z` oder `--yolo` als Ersatz verwenden.

## Gespräch und Gedächtnis

Die eigene Sitzungs-ID steht in `.run/hermes-session.json`. Folgeturns verwenden nur diese ID, nie `--continue` oder `latest`. `--ignore-rules` verhindert automatische Übernahme von globalem Gedächtnis. `memory/` bleibt ein eigener, anfangs leerer Ordner. `AGENTS.md` gilt für manuelle Arbeit hier.

Für eine Aktion mit interaktiver Freigabe Jarvis mit Strg+C beenden. Dann im Terminal die **exakte ID aus `.run/hermes-session.json`** einsetzen und das eigene Profil/Modell/Provider verwenden:

```bash
cd /Pfad/zu/Jarvis
hermes -p default chat --cli --ignore-rules -t terminal -m gpt-6-astra --provider openai-codex --in "$PWD" --resume HIER_DIE_EXAKTE_SITZUNGS_ID
```

Den abgewiesenen Auftrag selbst nochmals formulieren. Keine Freigaben abschalten.

## Veröffentlichen

Nicht mitgeben: `.venv/`, `.run/`, `jarvis.local.json`, `memory/` mit persönlichen Notizen, Hermes-Tokens, `~/.hermes`. Der Signalbus liegt unter `~/voice-line` und gehört nicht ins Repo.

Öffentlicher Fork: [s3vdev/Jarvis](https://github.com/s3vdev/Jarvis). `NOTICE` mitliefern. Das Original hat keine Lizenz.

## Prüfung

Bei beendetem Visualizer, ohne Mikrofonaufnahme und ohne KI-Anfrage:

```bash
cd /Pfad/zu/Jarvis
.venv/bin/python -m unittest discover -s tests -v
```

Opt-in mit zwei echten Anfragen über das Konto auf diesem Rechner (verbraucht Limits):

```bash
.venv/bin/python tests/smoke_hermes.py
```

Die Test-Sitzung bleibt von der normalen Jarvis-Sitzung getrennt. CONNECTED ist die Bereitschaftsanzeige, kein separates Konto.
