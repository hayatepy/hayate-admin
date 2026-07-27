"""Inspect built artifacts for the public package boundary."""

from __future__ import annotations

import email
import tarfile
import zipfile
from pathlib import Path

DIST = Path("dist")


def main() -> int:
    wheels = list(DIST.glob("hayate_admin-*.whl"))
    sdists = list(DIST.glob("hayate_admin-*.tar.gz"))
    assert len(wheels) == 1, wheels
    assert len(sdists) == 1, sdists

    with zipfile.ZipFile(wheels[0]) as wheel:
        names = set(wheel.namelist())
        assert "hayate_admin/py.typed" in names
        assert "hayate_admin/__init__.py" in names
        assert not any(name.startswith(("tests/", "docs/", "scripts/")) for name in names)
        metadata_name = next(name for name in names if name.endswith(".dist-info/METADATA"))
        metadata = email.message_from_bytes(wheel.read(metadata_name))
        assert metadata["Name"] == "hayate-admin"
        assert metadata["Version"] == "0.1.0"
        requirements = metadata.get_all("Requires-Dist")
        assert requirements is not None
        assert any(requirement.startswith("hayate>=0.13") for requirement in requirements)
        assert any(requirement.startswith("hayate-htmx>=0.2") for requirement in requirements)

    with tarfile.open(sdists[0], "r:gz") as sdist:
        names = sdist.getnames()
        assert any(name.endswith("/README.md") for name in names)
        assert any(name.endswith("/LICENSE") for name in names)
        assert not any("/.venv/" in name for name in names)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
