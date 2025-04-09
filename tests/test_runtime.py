from pathlib import Path

import pytest

from hooks.utils.runtime import mark_rerun, should_rerun


def test_mark_rerun(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test mark_rerun"""
    marker_path = tmp_path / "rerun"
    monkeypatch.setenv("WORK", str(tmp_path))

    mark_rerun()

    assert marker_path.exists()


def test_mark_rerun_with_missing_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test mark_rerun with missing WORK env"""
    monkeypatch.delenv("WORK", raising=False)

    with pytest.raises(ValueError, match="WORK environment variable is not set"):
        mark_rerun()


def test_should_rerun_when_marker_exist(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test should_rerun when marker exists"""
    marker_path = tmp_path / "rerun"
    marker_path.touch()
    monkeypatch.setenv("WORK", str(tmp_path))

    result = should_rerun()

    assert result is True


def test_should_rerun_when_marker_does_not_exist(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test should_rerun when marker does not exist"""
    monkeypatch.setenv("WORK", str(tmp_path))

    result = should_rerun()

    assert result is False


def test_should_rerun_with_missing_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test should_rerun with missing WORK env"""
    monkeypatch.delenv("WORK", raising=False)

    with pytest.raises(ValueError, match="WORK environment variable is not set"):
        should_rerun()
