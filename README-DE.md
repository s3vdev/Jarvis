# Jarvis – Anleitung

Kurzüberblick und Bilder stehen in [README.md](README.md). Hier die Bedienung und die Grenzen.

## Sprechen

Einfach Deutsch reden. Kein Enter. Eine Pause schickt die Frage. Während er spricht, darfst du ihm ins Wort fallen.

**Stopp** oder **Pause** schließt das Mikrofon und bricht die Stimme ab. **Zuhören** macht wieder auf.

Der Name Jarvis ist optional. In den Einstellungen kannst du „nur mit Jarvis“ einschalten, wenn der Raum laut ist.

macOS fragt beim ersten Mal nach dem Mikrofon fürs Terminal. Strg+C beendet Jarvis und das Fenster.

## Was er lokal kann

Uhr, Timer, Lautstärke und „nochmal“ gehen sofort, ohne Hermes.

Safari, eine Website oder eine Datei öffnet er erst nach **Ja** im Fenster. Dateien sucht er auf dem Schreibtisch, in Dokumente, Downloads und im Jarvis-Ordner. Nein oder Timeout heißt: er lässt es.

Geht etwas anderes nicht, sagt er nur: Das geht von hier aus nicht.

## Einstellungen

Im Zahnrad:

- Hermes: gefunden oder nicht, welches Profil
- Nutzung deines Codex-Kontos. **Aktualisieren** holt die Zahlen. Jarvis kann Limits nicht erhöhen.
- Stimme: Conrad, Killian oder Florian. Darunter die Probe.
- Mikrofon, optionaler Rufname, Lautstärke, Animation

Fällt das Netz aus, spricht die lokale Stimme Anna.

## Einmal einrichten

Voraussetzungen: macOS 13+, Python 3, Xcode Command Line Tools, eigenes Hermes mit Login.

```bash
cd /Pfad/zu/Jarvis
./setup.command
```

Danach `Jarvis starten.command` doppelklicken.

Setup legt `.venv` an und sucht Hermes im normalen PATH, in `JARVIS_HERMES` oder unter `~/.hermes/installs`. Ist Port 8777 schon belegt, bricht der Starter ab.

Profil, Modell und Provider stehen in `jarvis.json`. Für diesen Rechner kannst du `jarvis.local.json` nutzen oder `JARVIS_HERMES_PROFILE`, `JARVIS_HERMES_MODEL` und `JARVIS_HERMES_PROVIDER`. Keine Zugangsdaten in den Ordner legen.

## Was Hermes hier darf

Jeder Start ist eine frische Sitzung. Freigaben bleiben an. Sprache bestätigt keine Hermes-Freigabe.

Befehle, die eine neue Freigabe brauchen, laufen hier nicht. `hermes -z` und `--yolo` sind verboten.

`memory/` bleibt leer, bis du selbst etwas hineinschreibst. Jarvis liest und schreibt dort nicht von allein.

Wenn eine Aktion eine echte Freigabe braucht: Jarvis mit Strg+C beenden, dann im Terminal die Sitzungs-ID aus `.run/hermes-session.json` einsetzen und den Auftrag dort nochmal sagen.

```bash
cd /Pfad/zu/Jarvis
hermes -p default chat --cli --ignore-rules -t terminal -m gpt-6-astra --provider openai-codex --in "$PWD" --resume HIER_DIE_EXAKTE_SITZUNGS_ID
```

## Tests

Visualizer aus, kein Mikrofon, keine Modellanfrage:

```bash
.venv/bin/python -m unittest discover -s tests -v
```

Zwei echte Anfragen (verbraucht Kontingent):

```bash
.venv/bin/python tests/smoke_hermes.py
```

## Herkunft

Dieser Ordner ist der Fork [s3vdev/Jarvis](https://github.com/s3vdev/Jarvis). Gesicht und alte Voice-Line stammen von [Sujatx/Jarvis](https://github.com/Sujatx/Jarvis). Dort gibt es keine Lizenz. Siehe [NOTICE](NOTICE).
