from collections.abc import Iterator
from unittest.mock import Mock, patch

import pytest

from hooks.post_run import main


@pytest.fixture
def mock_should_rerun() -> Iterator[Mock]:
    """Patch mark_rerun"""
    with patch("hooks.post_run.should_rerun") as m:
        yield m


@pytest.mark.parametrize(
    ("should_rerun", "expected_exit_code"),
    [
        (True, 1),
        (False, 0),
    ],
)
def test_post_run_hook_when_no_rerun_marker(
    mock_should_rerun: Mock,
    *,
    should_rerun: bool,
    expected_exit_code: int,
) -> None:
    """Test post_run_hook when no rerun marker"""
    mock_should_rerun.return_value = should_rerun

    with pytest.raises(SystemExit) as e:
        main()

    assert e.value.code == expected_exit_code
    mock_should_rerun.assert_called_once_with()
