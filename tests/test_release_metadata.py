from __future__ import annotations

import tomllib
from pathlib import Path

from hayate_admin import __version__

ROOT = Path(__file__).resolve().parents[1]


def test_public_version_matches_project_metadata() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]

    assert __version__ == project["version"]


def test_public_discovery_uses_the_canonical_site() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert project["urls"]["Homepage"] == "https://hayatepy.dev/ecosystem/#hayate-admin"
    assert "[Start here](https://hayatepy.dev/)" in readme
    assert "[Tested compatibility](https://hayatepy.dev/evidence/compatibility/)" in readme
    assert "https://github.com/hayatepy/.github/blob/main/docs/" not in readme
