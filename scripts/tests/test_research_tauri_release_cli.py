"""Exercise the real release checker CLI with synthetic local Git and Cargo inputs.

No network, ActivityWatch event history, Anki database, or identifying data.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "check_tauri_server.py"


def _git(root: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(root), *args], text=True, stderr=subprocess.DEVNULL
    ).strip()


def _inputs(tmp_path: Path, *, submodule_version="0.14.0",
            tauri_version="0.14.0", mismatch_revision=False) -> Path:
    server = tmp_path / "aw-server-rust"
    (server / "aw-server").mkdir(parents=True)
    (server / "aw-server/Cargo.toml").write_text(
        f'[package]\nname = "aw-server"\nversion = "{submodule_version}"\n'
    )
    _git(server, "init", "-q")
    _git(server, "add", ".")
    subprocess.run(
        ["git", "-C", str(server), "-c", "user.name=Fixture",
         "-c", "user.email=fixture@example.invalid", "commit", "-qm", "fixture"],
        check=True
    )
    sha = _git(server, "rev-parse", "HEAD")
    assert len(sha) == 40
    locked = "f" * 40 if mismatch_revision else sha
    lock = tmp_path / "aw-tauri/src-tauri/Cargo.lock"
    lock.parent.mkdir(parents=True)
    lock.write_text(
        '[[package]]\nname = "aw-server"\n'
        f'version = "{tauri_version}"\n'
        'source = "git+https://github.com/ActivityWatch/aw-server-rust#'
        f'{locked}"\n'
    )
    return tmp_path


@pytest.mark.parametrize("release,submodule,tauri,rev_diff,expected_rc,expected", [
    ("0.0.0.dev-36f55bf", "0.14.0", "0.14.0", False, 0, "OK: Qt and Tauri"),
    ("0.14.0b5", "0.14.0", "0.14.0", False, 0, "OK: Qt and Tauri"),
    ("0.15.0b1", "0.14.0", "0.14.0", False, 1, "release line 0.15"),
    ("0.0.0.dev-36f55bf", "0.14.0", "0.13.0", False, 1, "does not match aw-server-rust"),
    ("0.0.0.dev-36f55bf", "0.14.0", "0.14.0", True, 1, "but the release submodule is"),
    ("0.0.0.dev-unsigned-claim", "0.14.0", "0.14.0", False, 1, "release line 0.0"),
])
def test_release_checker_uses_real_local_git(tmp_path, release, submodule,
                                             tauri, rev_diff, expected_rc, expected):
    root = _inputs(tmp_path, submodule_version=submodule,
                   tauri_version=tauri, mismatch_revision=rev_diff)
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), release, "--repo-root", str(root)],
        capture_output=True, text=True, timeout=15
    )
    assert proc.returncode == expected_rc, proc.stderr
    assert expected in proc.stdout + proc.stderr
    assert "fixture@example.invalid" not in proc.stdout + proc.stderr
    if release == "0.0.0.dev-36f55bf" and expected_rc:
        assert "Update aw-tauri's Cargo.lock to the intended server release line" not in proc.stderr


def test_sync_validation_cannot_omit_version_checks():
    spec = importlib.util.spec_from_file_location("checked_tauri_server", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sha = "a" * 40
    assert module.validation_errors(None, "0.14.0", sha, "0.14.0", sha) == []
    errors = module.validation_errors(None, "0.14.0", sha, "0.13.0", sha)
    assert len(errors) == 1
    assert "does not match aw-server-rust" in errors[0]
