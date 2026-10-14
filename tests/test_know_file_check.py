"""Focused tests for know-file offline publication hygiene."""
import tempfile
import unittest
from pathlib import Path
from zog.version_share.know_file_check import audit, main


class KnowFileCheckTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "README.md").write_text("# know-file\n- [module](module/INDEX.md)\n", encoding="utf-8")
        (self.root / "module").mkdir()
        (self.root / "module/INDEX.md").write_text("# module\n", encoding="utf-8")

    def test_valid(self):
        self.assertEqual([], audit(self.root))
        self.assertEqual(0, main([str(self.root)]))

    def test_missing_link(self):
        (self.root / "module/INDEX.md").write_text("[missing](handoffs/old.md)\n", encoding="utf-8")
        self.assertTrue(any("missing link target" in x for x in audit(self.root)))

    def test_missing_index_and_disallowed_extension(self):
        (self.root / "new").mkdir()
        (self.root / "new/backup.zip").write_bytes(b"hi")
        problems = audit(self.root)
        self.assertTrue(any("missing INDEX.md" in x for x in problems))
        self.assertTrue(any("disallowed file type" in x for x in problems))

    def test_size_limit(self):
        (self.root / "module/large.txt").write_bytes(b"a" * 500001)
        self.assertTrue(any("larger than" in x for x in audit(self.root)))

    def test_secret_redacted(self):
        (self.root / "module/secrets.txt").write_text(
            "-----BEGIN PRIVATE KEY-----\n", encoding="utf-8")
        problems = audit(self.root)
        self.assertTrue(any("possible private key" in x for x in problems))
        self.assertFalse(any("BEGIN PRIVATE" in x for x in problems))

    def test_symlink_rejected(self):
        (self.root / "module/shortcut.md").symlink_to("INDEX.md")
        self.assertTrue(any("symlinks are not allowed" in x for x in audit(self.root)))


if __name__ == "__main__":
    unittest.main()
