#!/usr/bin/env python3
"""Update DanEQ's package version and add a blank changelog section."""
from __future__ import annotations

import re
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 2 or not re.fullmatch(r"\d+\.\d+\.\d+", sys.argv[1]):
        print("usage: python scripts/bump_version.py X.Y.Z", file=sys.stderr)
        return 2

    version = sys.argv[1]
    init_file = Path("daneq/__init__.py")
    changelog_file = Path("CHANGELOG.md")
    init_text = init_file.read_text()
    changelog_text = changelog_file.read_text()

    if re.search(rf"(?m)^## {re.escape(version)}\s*$", changelog_text):
        print(f"CHANGELOG.md already contains a {version} section", file=sys.stderr)
        return 1

    updated, count = re.subn(
        r'(?m)^__version__ = "[^\"]+"$',
        f'__version__ = "{version}"',
        init_text,
        count=1,
    )
    if count != 1:
        print("Could not find __version__ in daneq/__init__.py", file=sys.stderr)
        return 1
    if "# Changelog\n" not in changelog_text:
        print("Could not find '# Changelog' heading in CHANGELOG.md", file=sys.stderr)
        return 1

    init_file.write_text(updated)
    changelog_file.write_text(
        changelog_text.replace(
            "# Changelog\n",
            f"# Changelog\n\n## {version}\n- \n",
            1,
        )
    )
    print(f"Prepared DanEQ {version} in daneq/__init__.py and CHANGELOG.md")
    print("Edit the new changelog entry before committing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
