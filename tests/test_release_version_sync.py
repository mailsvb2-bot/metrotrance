from __future__ import annotations

import json
import tomllib
from pathlib import Path

import windows_installer
from metrotrance import __version__


ROOT = Path(__file__).resolve().parents[1]


def test_release_version_is_synchronized() -> None:
    with (ROOT / "pyproject.toml").open("rb") as stream:
        project_version = tomllib.load(stream)["project"]["version"]
    manifest_version = json.loads(
        (ROOT / "bundle_manifest.json").read_text(encoding="utf-8")
    )["version"]
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert windows_installer.VERSION == __version__
    assert project_version == __version__
    assert manifest_version == __version__
    assert f"MetroTrance {__version__}" in readme
