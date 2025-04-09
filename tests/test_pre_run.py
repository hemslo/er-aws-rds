from collections.abc import Iterator
from unittest.mock import Mock, patch

import pytest

from hooks.pre_run import main
from hooks.utils.models import State
from tests.conftest import input_data, input_object


@pytest.fixture
def mock_read_input_from_file() -> Iterator[Mock]:
    """Patch read_input_from_file"""
    with patch("hooks.pre_run.read_input_from_file") as m:
        yield m


@pytest.fixture
def mock_aws_api() -> Iterator[Mock]:
    """Patch AWSApi"""
    with patch("hooks.pre_run.AWSApi", autospec=True) as m:
        yield m


@pytest.fixture
def mock_blue_green_deployment_manager() -> Iterator[Mock]:
    """Patch BlueGreenDeploymentManager"""
    with patch("hooks.pre_run.BlueGreenDeploymentManager", autospec=True) as m:
        yield m


@pytest.fixture
def mock_is_dry_run() -> Iterator[Mock]:
    """Patch is_dry_run"""
    with patch("hooks.pre_run.is_dry_run") as m:
        yield m


@pytest.fixture
def mock_mark_rerun() -> Iterator[Mock]:
    """Patch mark_rerun"""
    with patch("hooks.pre_run.mark_rerun") as m:
        yield m


@pytest.mark.parametrize(
    ("dry_run", "state", "expected_exit_code"),
    [
        (True, State.INIT, 42),
        (False, State.INIT, 42),
        (True, State.NOT_ENABLED, 0),
        (False, State.NOT_ENABLED, 0),
        (True, State.PROVISIONING, 42),
        (False, State.PROVISIONING, 42),
        (True, State.AVAILABLE, 42),
        (False, State.AVAILABLE, 42),
        (True, State.SWITCHOVER_IN_PROGRESS, 42),
        (False, State.SWITCHOVER_IN_PROGRESS, 42),
        (True, State.SWITCHOVER_COMPLETED, 42),
        (False, State.SWITCHOVER_COMPLETED, 42),
        (True, State.DELETING_SOURCE_DB_INSTANCES, 42),
        (False, State.DELETING_SOURCE_DB_INSTANCES, 42),
        (True, State.SOURCE_DB_INSTANCES_DELETED, 42),
        (False, State.SOURCE_DB_INSTANCES_DELETED, 42),
        (True, State.DELETING, 42),
        (False, State.DELETING, 42),
        (True, State.NO_OP, 0),
        (False, State.NO_OP, 0),
        (True, State.REPLICA_SOURCE_ENABLED, 42),
        (False, State.REPLICA_SOURCE_ENABLED, 42),
        (True, State.PENDING_PREPARE, 0),
    ],
)
def test_pre_run_hook(  # noqa: PLR0913
    mock_read_input_from_file: Mock,
    mock_aws_api: Mock,
    mock_blue_green_deployment_manager: Mock,
    mock_is_dry_run: Mock,
    *,
    dry_run: bool,
    state: State,
    expected_exit_code: int,
) -> None:
    """Test pre_hook"""
    mock_read_input_from_file.return_value = input_data()
    mock_is_dry_run.return_value = dry_run
    expected_model = input_object()
    mock_blue_green_deployment_manager.return_value.run.return_value = state

    with pytest.raises(SystemExit) as e:
        main()

    assert e.value.code == expected_exit_code
    mock_aws_api.assert_called_once_with(region_name=expected_model.data.region)
    mock_blue_green_deployment_manager.assert_called_once_with(
        aws_api=mock_aws_api.return_value,
        app_interface_input=expected_model,
        dry_run=dry_run,
    )
    mock_blue_green_deployment_manager.return_value.run.assert_called_once_with()


def test_pre_run_hook_with_pending_prepare(
    mock_read_input_from_file: Mock,
    mock_aws_api: Mock,
    mock_blue_green_deployment_manager: Mock,
    mock_is_dry_run: Mock,
    mock_mark_rerun: Mock,
) -> None:
    """Test pre_hook with pending prepare"""
    mock_read_input_from_file.return_value = input_data()
    mock_is_dry_run.return_value = False
    expected_model = input_object()
    mock_blue_green_deployment_manager.return_value.run.return_value = (
        State.PENDING_PREPARE
    )

    with pytest.raises(SystemExit) as e:
        main()

    assert e.value.code == 0
    mock_aws_api.assert_called_once_with(region_name=expected_model.data.region)
    mock_blue_green_deployment_manager.assert_called_once_with(
        aws_api=mock_aws_api.return_value,
        app_interface_input=expected_model,
        dry_run=False,
    )
    mock_blue_green_deployment_manager.return_value.run.assert_called_once_with()
    mock_mark_rerun.assert_called_once_with()


@pytest.mark.parametrize("dry_run", [True, False])
def test_pre_run_hook_exception(
    mock_read_input_from_file: Mock,
    mock_aws_api: Mock,
    mock_blue_green_deployment_manager: Mock,
    mock_is_dry_run: Mock,
    *,
    dry_run: bool,
) -> None:
    """Test pre_hook exception"""
    mock_read_input_from_file.return_value = input_data()
    mock_is_dry_run.return_value = dry_run
    expected_model = input_object()
    mock_blue_green_deployment_manager.return_value.run.side_effect = Exception(
        "Test exception"
    )

    with pytest.raises(SystemExit) as e:
        main()

    assert e.value.code == 1
    mock_aws_api.assert_called_once_with(region_name=expected_model.data.region)
