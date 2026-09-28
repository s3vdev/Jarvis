"""Read-only public web snippets for Hermes. No browser, no Hermes tools."""

import html
import json
import re
import ssl
from urllib.error import URLError
from urllib.parse import quote_plus, urlencode, urlparse
from urllib.request import Request, urlopen

from memory_store import looks_secret

_HOSTS = frozenset({
    "html.duckduckgo.com",
    "lite.duckduckgo.com",
    "api.duckduckgo.com",
    "duckduckgo.com",
    "de.wikipedia.org",
    "en.wikipedia.org",
})
_MAX_BYTES = 400_000
_TIMEOUT = 8
_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
)
_TAG = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")
_TITLE = re.compile(
    r'class="result__a"[^>]*>(.*?)</a>.*?class="result__snippet"[^>]*>(.*?)</',
    re.I | re.S,
)
_LITE = re.compile(
    r'class="result-link"[^>]*>(.*?)</a>.*?class="result-snippet"[^>]*>(.*?)</',
    re.I | re.S,
)


def _plain(text, limit=240):
    cleaned = _SPACE.sub(" ", _TAG.sub(" ", html.unescape(text or ""))).strip()
    return cleaned[:limit]


def search_query(text):
    query = _SPACE.sub(" ", (text or "").strip())
    if len(query) < 10 or len(query) > 180:
        return ""
    if looks_secret(query):
        return ""
    return query


def parse_ddg_html(raw):
    hits = []
    blob = raw if isinstance(raw, str) else raw.decode("utf-8", "replace")
    for pattern in (_TITLE, _LITE):
        for match in pattern.finditer(blob):
            title = _plain(match.group(1), 160)
            snippet = _plain(match.group(2), 240)
            if title and snippet:
                hits.append((title, snippet))
            if len(hits) >= 5:
                return hits
        if hits:
            return hits
    return hits


def parse_ddg_json(raw):
    hits = []
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return hits
    if not isinstance(data, dict):
        return hits
    abstract = _plain(data.get("AbstractText") or "", 320)
    heading = _plain(data.get("Heading") or "Kurzinfo", 160)
    if abstract:
        hits.append((heading, abstract))
    for topic in data.get("RelatedTopics") or []:
        if not isinstance(topic, dict):
            continue
        text = _plain(topic.get("Text") or "", 240)
        if text:
            hits.append((_plain(topic.get("FirstURL") or "Treffer", 120), text))
        if len(hits) >= 5:
            break
    return hits


def parse_wiki_json(raw):
    hits = []
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return hits
    rows = ((data.get("query") or {}).get("search") or [])
    if not isinstance(rows, list):
        return hits
    for row in rows:
        if not isinstance(row, dict):
            continue
        title = _plain(row.get("title") or "", 160)
        snippet = _plain(row.get("snippet") or "", 240)
        if title and snippet:
            hits.append((title, snippet))
        if len(hits) >= 5:
            break
    return hits


def format_hits(hits):
    lines = []
    for index, (title, snippet) in enumerate(hits[:5], 1):
        lines.append("%d. %s — %s" % (index, title, snippet))
    return "\n".join(lines)


def _allowed(url):
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and host in _HOSTS


def _fetch(url, data=None):
    if not _allowed(url):
        return b""
    headers = {"User-Agent": _UA, "Accept": "text/html,application/json"}
    if data is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    request = Request(url, data=data, headers=headers)
    with urlopen(request, timeout=_TIMEOUT, context=ssl.create_default_context()) as response:
        if not _allowed(response.geturl()):
            return b""
        return response.read(_MAX_BYTES)


def search_web(text):
    """Public snippets for one utterance. Empty on failure. Never opens a browser."""
    query = search_query(text)
    if not query:
        return []
    encoded = quote_plus(query)
    try:
        body = urlencode({"q": query}).encode("utf-8")
        html_body = _fetch("https://html.duckduckgo.com/html/", body)
        hits = parse_ddg_html(html_body)
        if hits:
            return hits
        lite = _fetch("https://lite.duckduckgo.com/lite/?q=%s" % encoded)
        hits = parse_ddg_html(lite)
        if hits:
            return hits
        wiki = _fetch(
            "https://de.wikipedia.org/w/api.php?action=query&list=search&srsearch=%s"
            "&utf8=1&format=json&srlimit=5" % encoded)
        hits = parse_wiki_json(wiki)
        if hits:
            return hits
        json_body = _fetch(
            "https://api.duckduckgo.com/?q=%s&format=json&no_html=1&skip_disambig=1" % encoded)
        return parse_ddg_json(json_body)
    except (URLError, TimeoutError, OSError, ValueError):
        return []
