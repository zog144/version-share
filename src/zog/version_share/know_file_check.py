"""Offline, read-only publication hygiene for the Zog know-file repository."""
from __future__ import annotations

import argparse
import re
from pathlib import Path, PurePosixPath

LIMIT = 500_000
EXTENSIONS = {".md", ".txt", ".json", ".jsonl", ".log", ".xml", ".patch",
              ".py", ".sh", ".service", ".png", ".jpg", ".jpeg", ".webp"}
EXACT_NAMES = {"COPYRIGHT", "LICENSE", "NOTICE"}
LINK = re.compile(r"\[[^\]\n]+\]\(([^)\n]+)\)")
CREDENTIALS = (
    ("private key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |ENCRYPTED )?PRIVATE KEY-----")),
    ("GitHub token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b|\bgithub_pat_[A-Za-z0-9_]{20,}\b")),
    ("AWS access key", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
)


def _within(root: Path, target: Path) -> bool:
    try:
        target.relative_to(root)
        return True
    except ValueError:
        return False


def audit(root: Path) -> list[str]:
    """Report problems, without reading external paths or changing any files."""
    root = root.resolve()
    problems: list[str] = []
    if not root.is_dir() or not (root / "README.md").is_file():
        return ["not a know-file repository root (README.md missing)"]
    source_paths = sorted(root.rglob("*"))
    for path in source_paths:
        rel = path.relative_to(root).as_posix()
        if any(part.startswith(".") for part in path.relative_to(root).parts):
            if path.name == ".git" or ".git" in path.parts or ".version-share" in path.parts:
                continue
        if path.is_symlink():
            problems.append(f"{rel}: symlinks are not allowed")
            continue
        if not path.is_file():
            continue
        if path.stat().st_size > LIMIT:
            problems.append(f"{rel}: larger than {LIMIT} bytes")
        if path.suffix.lower() not in EXTENSIONS and path.name not in EXACT_NAMES:
            problems.append(f"{rel}: disallowed file type")
        if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            problems.append(f"{rel}: not UTF-8 source text")
            continue
        for name, pattern in CREDENTIALS:
            if pattern.search(text):
                problems.append(f"{rel}: possible {name} (value suppressed)")
    for index in [root / "README.md", *sorted(root.glob("*/INDEX.md"))]:
        rel = index.relative_to(root).as_posix()
        try:
            content = index.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            problems.append(f"{rel}: cannot read index")
            continue
        for match in LINK.finditer(content):
            dest = match.group(1).strip("<>").split("#", 1)[0].strip()
            if not dest or re.match(r"^(?:[A-Za-z][A-Za-z0-9+.-]*:|//)", dest):
                continue
            target = (index.parent / dest).resolve()
            if not _within(root, target):
                problems.append(f"{rel}: relative link escapes repository")
            elif not target.exists():
                problems.append(f"{rel}: missing link target {dest}")
    for folder in sorted(root.iterdir()):
        if folder.is_dir() and not folder.name.startswith(".") and not (folder / "INDEX.md").is_file():
            problems.append(f"{folder.name}/: missing INDEX.md")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="know-file working tree")
    args = parser.parse_args(argv)
    problems = audit(args.root)
    if problems:
        for issue in problems:
            print(issue)
        print(f"FAIL: {len(problems)} publication hygiene issue(s)")
        return 1
    print("PASS: know-file local publication hygiene")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
