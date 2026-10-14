import importlib
from pathlib import Path
import unittest

import zog.version_share as version_share


class NamespaceMigrationTests(unittest.TestCase):
    def test_canonical_import_and_version(self):
        self.assertEqual(version_share.__version__, "0.4.0")
        package = Path(version_share.__file__).resolve().parent
        self.assertEqual(package.name, "version_share")
        self.assertEqual(package.parent.name, "zog")

    def test_legacy_top_level_package_is_not_in_checkout(self):
        root = Path(__file__).resolve().parents[1]
        legacy = "version" + "_share"
        self.assertFalse((root / legacy).exists())

    def test_active_sources_do_not_reference_legacy_import_path(self):
        root = Path(__file__).resolve().parents[1]
        legacy = "version" + "_share"
        needles = (
            "from " + legacy,
            "import " + legacy,
            "'" + legacy + ".",
            '"' + legacy + ".",
            "-m " + legacy,
        )
        candidates = [root / "pyproject.toml", root / "bootstrap.py",
                      root / "README.md", root / "BOOTSTRAP.md", root / "MIGRATION.md"]
        candidates.extend((root / "src").rglob("*.py"))
        candidates.extend(path for path in (root / "tests").glob("*.py") if path != Path(__file__))
        failures = []
        for path in candidates:
            text = path.read_text()
            for needle in needles:
                if needle in text:
                    failures.append(f"{path.relative_to(root)}: {needle}")
        self.assertEqual(failures, [])


if __name__ == "__main__":
    unittest.main()
