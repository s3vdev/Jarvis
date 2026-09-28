#!/usr/bin/env python3
"""Long-lived Hermes turn loop for Jarvis.

Started once with the Hermes interpreter. Later sentences reuse the same
agent, so the CLI and MCP startup are not paid again. Approvals stay on:
this process never sets HERMES_YOLO_MODE or HERMES_ACCEPT_HOOKS.

Protocol, one JSON object per line on the saved stdout (fd 3):
    {"ready": true}
    {"ok": true, "text": "...", "session_id": "..."}
    {"ok": false, "error": "..."}
"""

import json
import os
import sys


def _emit(payload):
    line = json.dumps(payload, ensure_ascii=False) + "\n"
    os.write(3, line.encode("utf-8"))


def _fail(message):
    _emit({"ready": False, "ok": False, "error": message})
    raise SystemExit(1)


def main(argv):
    if os.environ.get("HERMES_YOLO_MODE") == "1":
        _fail("YOLO-Modus ist für Jarvis verboten.")
    os.environ["HERMES_SINGLE_QUERY_SESSION"] = "1"
    os.environ["HERMES_IGNORE_RULES"] = "1"
    os.environ.pop("HERMES_ACCEPT_HOOKS", None)
    os.environ.pop("HERMES_INTERACTIVE", None)

    args = _parse(argv)
    os.chdir(args["workdir"])
    os.environ["TERMINAL_CWD"] = args["workdir"]

    from cli import _build_cli_from_args
    from hermes_cli.cli_single_query import (
        _configure_quiet_agent,
        _sync_cli_session_id_from_agent,
    )

    cli = _build_cli_from_args(
        args["model"], "terminal", args["provider"], "low",
        None, None, 6, None, False, True,
        args.get("resume") or None, False, False, True, None,
    )
    # Headless clarify. The MCP wait happens once at this boot, not on every sentence.
    cli._single_query_mode = True
    if not cli._init_agent():
        _fail("Hermes konnte nicht starten.")
    _configure_quiet_agent(cli.agent)
    _sync_cli_session_id_from_agent(cli)
    _emit({"ready": True, "session_id": cli.session_id or ""})

    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            incoming = json.loads(raw)
            text = incoming["text"]
        except (ValueError, KeyError, TypeError):
            _emit({"ok": False, "error": "Ungültige Anfrage."})
            continue
        try:
            history = cli.conversation_history or None
            result = cli.agent.run_conversation(
                user_message=text, conversation_history=history)
        except Exception as exc:  # noqa: BLE001
            _emit({"ok": False, "error": "Hermes-Fehler: %s" % exc})
            continue
        if isinstance(result, dict) and result.get("messages"):
            cli.conversation_history = result["messages"]
        _sync_cli_session_id_from_agent(cli)
        reply = result.get("final_response", "") if isinstance(result, dict) else str(result or "")
        failed = (not isinstance(result, dict)) or bool(result.get("failed")) or not str(reply).strip()
        if failed:
            _emit({"ok": False, "error": "Hermes hat keine Antwort geliefert.",
                   "session_id": cli.session_id or ""})
            continue
        _emit({"ok": True, "text": str(reply).strip(), "session_id": cli.session_id or ""})


def _parse(argv):
    values = {"model": "gpt-6-astra", "provider": "openai-codex", "resume": "", "workdir": os.getcwd()}
    i = 0
    while i < len(argv):
        key = argv[i]
        if key in ("--model", "--provider", "--resume", "--workdir") and i + 1 < len(argv):
            values[key[2:]] = argv[i + 1]
            i += 2
            continue
        i += 1
    if not values["workdir"]:
        _fail("Arbeitsordner fehlt.")
    return values


if __name__ == "__main__":
    main(sys.argv[1:])
