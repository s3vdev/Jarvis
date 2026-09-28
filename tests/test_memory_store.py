from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'voice-line'))

from memory_store import add_note, load_notes, looks_secret, save_notes, set_memory_root


class MemoryStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        set_memory_root(self.tmp.name)

    def tearDown(self):
        set_memory_root(ROOT)
        self.tmp.cleanup()

    def test_empty_placeholder_is_not_a_note(self):
        self.assertEqual(load_notes(), '')
        self.assertEqual(save_notes(''), '')
        self.assertEqual(load_notes(), '')

    def test_save_and_add_stay_in_memory_md(self):
        self.assertEqual(save_notes('Ich heiße Sven.'), 'Ich heiße Sven.')
        self.assertEqual(load_notes(), 'Ich heiße Sven.')
        self.assertEqual(add_note('Kaffee schwarz'), 'Ich heiße Sven.\nKaffee schwarz')
        path = Path(self.tmp.name) / 'memory' / 'MEMORY.md'
        self.assertTrue(path.is_file())
        self.assertIn('Kaffee schwarz', path.read_text(encoding='utf-8'))

    def test_secrets_are_rejected(self):
        self.assertTrue(looks_secret('api_key=sk-abcdefghijklmnop'))
        self.assertIsNone(save_notes('password: geheim123'))
        self.assertEqual(load_notes(), '')


if __name__ == '__main__':
    unittest.main()
