"""Offline integrity checks for direct installer assets."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts import bootstrap_offline as bootstrap
from scripts import preflight_offline
import setup_installer


def test_manifest_has_no_unverified_hashes():
    manifest = json.loads((bootstrap.ROOT / "scripts" / "asset_manifest.json").read_text())
    assert manifest["algorithm"] == "sha256"
    for entry in manifest["assets"].values():
        assert len(entry["sha256"]) == 64


def test_sha256_verifier_accepts_and_rejects(tmp_path: Path):
    asset = tmp_path / "asset.bin"
    asset.write_bytes(b"rightly-integrity")
    digest = hashlib.sha256(asset.read_bytes()).hexdigest()
    bootstrap._verify_sha256(asset, digest)
    with pytest.raises(RuntimeError, match="Kiểm tra toàn vẹn thất bại"):
        bootstrap._verify_sha256(asset, "0" * 64)


def test_installer_verifier_rejects_corrupt_file(tmp_path: Path):
    asset = tmp_path / "python.exe"
    asset.write_bytes(b"corrupt")
    with pytest.raises(RuntimeError, match="File bị loại bỏ"):
        setup_installer._verify_sha256(asset, "f" * 64)
    assert asset.exists()  # caller owns cleanup so verifier stays side-effect free


def test_unlisted_assets_are_not_given_a_guessed_hash():
    assert bootstrap._asset_sha256("https://example.invalid/file", Path("file")) is None
    assert setup_installer._manifest_sha256("file", "https://example.invalid/file") is None


def test_empty_manifest_is_reported_as_unverified_not_verified():
    verified, bootstrap_note = bootstrap._asset_verification_summary()
    preflight_verified, preflight_note = preflight_offline._asset_verification_note()

    assert verified == 0
    assert not preflight_verified
    assert "NOT checksum-verified" in bootstrap_note
    assert "NOT verified" in preflight_note
