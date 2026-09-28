import sys
from pathlib import Path
import unittest
from unittest.mock import patch
from io import BytesIO

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'voice-line'))

from web_search import format_hits, parse_ddg_html, parse_ddg_json, search_query, search_web


class WebSearchTests(unittest.TestCase):
    def test_query_rejects_secrets_and_short_text(self):
        self.assertEqual(search_query('ok'), '')
        self.assertEqual(search_query('password: geheim123 und noch mehr text'), '')
        self.assertEqual(
            search_query('Was findest du über Sven Mielke aus Bergneustadt heraus?'),
            'Was findest du über Sven Mielke aus Bergneustadt heraus?')

    def test_html_parser_keeps_plain_snippets(self):
        raw = '''
        <a class="result__a" href="/l/?uddg=https%3A%2F%2Fexample.com">Sven Mielke</a>
        <a class="result__snippet">Person aus Bergneustadt, öffentlich erwähnt.</a>
        <script>alert(1)</script>
        '''
        hits = parse_ddg_html(raw)
        self.assertEqual(hits[0][0], 'Sven Mielke')
        self.assertIn('Bergneustadt', hits[0][1])
        self.assertNotIn('<script>', format_hits(hits))

    def test_json_parser_reads_abstract(self):
        raw = '{"Heading":"Bergneustadt","AbstractText":"Stadt in Nordrhein-Westfalen.","RelatedTopics":[]}'
        hits = parse_ddg_json(raw)
        self.assertEqual(hits[0][0], 'Bergneustadt')
        self.assertIn('Nordrhein-Westfalen', hits[0][1])

    def test_search_web_posts_to_ddg_html(self):
        html = b'<a class="result__a">Titel</a><a class="result__snippet">Snippet text here.</a>'
        calls = []

        class FakeResp(BytesIO):
            def geturl(self):
                return 'https://html.duckduckgo.com/html/'
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False

        def fake_open(req, timeout=None, context=None):
            calls.append((req.full_url, req.data, req.get_method()))
            return FakeResp(html)

        with patch('web_search.urlopen', fake_open):
            hits = search_web('Was findest du über Sven Mielke aus Bergneustadt heraus?')
        self.assertEqual(hits[0][0], 'Titel')
        self.assertEqual(calls[0][2], 'POST')
        self.assertTrue(calls[0][0].startswith('https://html.duckduckgo.com/html'))
        self.assertIn(b'q=', calls[0][1])

    def test_http_redirect_off_allowlist_is_dropped(self):
        class FakeResp(BytesIO):
            def geturl(self):
                return 'http://evil.example/steal'
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False

        with patch('web_search.urlopen', return_value=FakeResp(b'nope')):
            self.assertEqual(
                search_web('Was findest du über Sven Mielke aus Bergneustadt heraus?'),
                [])


if __name__ == '__main__':
    unittest.main()
