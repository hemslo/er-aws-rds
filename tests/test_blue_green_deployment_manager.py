from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from mypy_boto3_rds.type_defs import (
        BlueGreenDeploymentTypeDef,
        DBInstanceTypeDef,
        DBParameterGroupTypeDef,
        ParameterOutputTypeDef,
        SwitchoverDetailTypeDef,
        UpgradeTargetTypeDef,
    )
from logging import Logger
from unittest.mock import Mock, call, create_autospec, patch

import pytest
from pydantic import ValidationError

from hooks.utils.aws_api import AWSApi
from hooks.utils.blue_green_deployment_manager import BlueGreenDeploymentManager
from hooks.utils.models import (
    ActionType,
    CreateAction,
    CreateBlueGreenDeploymentParams,
    DeleteAction,
    DeleteSourceDBInstanceAction,
    DeleteWithoutSwitchoverAction,
    State,
    SwitchoverAction,
    WaitForAvailableAction,
    WaitForDeletedAction,
    WaitForSourceDBInstancesDeletedAction,
    WaitForSwitchoverCompletedAction,
)
from tests.conftest import (
    DEFAULT_RDS_INSTANCE,
    DEFAULT_SOURCE_DB_PARAMETERS,
    DEFAULT_TARGET,
    DEFAULT_TARGET_PARAMETER_GROUP,
    DEFAULT_TARGET_RDS_INSTANCE,
    DEFAULT_VALID_UPGRADE_TARGETS,
    input_object,
)


@pytest.fixture
def mock_aws_api() -> Mock:
    """Mock AWSApi"""
    return create_autospec(AWSApi)


@pytest.fixture
def mock_logging() -> Iterator[Mock]:
    """Patch logging"""
    with patch("hooks.utils.blue_green_deployment_manager.logging.getLogger") as m:
        logger = create_autospec(Logger)
        m.return_value = logger
        yield logger


def build_blue_green_deployment_response(
    *,
    status: str,
    switchover_details: list[SwitchoverDetailTypeDef] | None = None,
    status_details: str | None = None,
) -> BlueGreenDeploymentTypeDef:
    """Build blue/green deployment response"""
    return {
        "BlueGreenDeploymentName": "test-rds",
        "BlueGreenDeploymentIdentifier": "some-bg-id",
        "Status": status,
        "SwitchoverDetails": (
            switchover_details
            if switchover_details is not None
            else [
                {
                    "SourceMember": "some-arn-old",
                    "TargetMember": "some-arn-new",
                    "Status": status,
                }
            ]
        ),
        **({"StatusDetails": status_details} if status_details else {}),
    }


def build_blue_green_deployment_data(
    *,
    enabled: bool = False,
    switchover: bool = False,
    switchover_timeout: int | None = None,
    delete: bool = False,
    target: dict | None = None,
) -> dict:
    """Build blue/green deployment config data"""
    if target is None:
        target = DEFAULT_TARGET
    return {
        "data": {
            "blue_green_deployment": {
                "enabled": enabled,
                "switchover": switchover,
                "switchover_timeout": switchover_timeout,
                "delete": delete,
                "target": target,
            },
        }
        | target,
    }


def setup_aws_api_side_effects(  # ruff: ignore[too-many-arguments]
    mock_aws_api: Mock,
    *,
    get_db_instance: list[DBInstanceTypeDef | None] | None = None,
    get_blue_green_deployment: list[BlueGreenDeploymentTypeDef | None] | None = None,
    get_db_parameter_group: list[DBParameterGroupTypeDef | None] | None = None,
    get_blue_green_deployment_valid_upgrade_targets: list[
        dict[str, UpgradeTargetTypeDef]
    ]
    | None = None,
    get_db_parameters: list[dict[str, ParameterOutputTypeDef]] | None = None,
) -> None:
    """Setup AWSApi side effects"""
    if get_db_instance is not None:
        mock_aws_api.get_db_instance.side_effect = get_db_instance
    if get_blue_green_deployment is not None:
        mock_aws_api.get_blue_green_deployment.side_effect = get_blue_green_deployment
    if get_db_parameter_group is not None:
        mock_aws_api.get_db_parameter_group.side_effect = get_db_parameter_group
    if get_blue_green_deployment_valid_upgrade_targets is not None:
        mock_aws_api.get_blue_green_deployment_valid_upgrade_targets.side_effect = (
            get_blue_green_deployment_valid_upgrade_targets
        )
    if get_db_parameters is not None:
        mock_aws_api.get_db_parameters.side_effect = get_db_parameters


@pytest.mark.parametrize("dry_run", [True, False])
def test_run_when_no_blue_green_deployment_config(
    mock_aws_api: Mock,
    mock_logging: Mock,
    *,
    dry_run: bool,
) -> None:
    """Test not enabled"""
    manager = BlueGreenDeploymentManager(
        aws_api=mock_aws_api,
        app_interface_input=input_object(),
        dry_run=dry_run,
    )

    state = manager.run()

    assert state == State.NOT_ENABLED
    mock_logging.info.assert_called_once_with("blue_green_deployment not enabled.")


@pytest.mark.parametrize("dry_run", [True, False])
def test_run_when_not_enabled(
    mock_aws_api: Mock,
    mock_logging: Mock,
    *,
    dry_run: bool,
) -> None:
    """Test not enabled"""
    additional_data = build_blue_green_deployment_data(enabled=False)
    manager = BlueGreenDeploymentManager(
        aws_api=mock_aws_api,
        app_interface_input=input_object(additional_data),
        dry_run=dry_run,
    )

    state = manager.run()

    assert state == State.NOT_ENABLED
    mock_logging.info.assert_called_once_with("blue_green_deployment not enabled.")


@pytest.mark.parametrize(
    ("dry_run", "expected_state"),
    [
        (True, State.INIT),
        (False, State.AVAILABLE),
    ],
)
def test_run_create_blue_green_deployment_with_no_target(
    mock_aws_api: Mock,
    mock_logging: Mock,
    *,
    dry_run: bool,
    expected_state: State,
) -> None:
    """Test create with no target"""
    additional_data = build_blue_green_deployment_data(enabled=True, target={})
    setup_aws_api_side_effects(
        mock_aws_api,
        get_db_instance=[DEFAULT_RDS_INSTANCE, DEFAULT_TARGET_RDS_INSTANCE],
        get_blue_green_deployment=[
            None,
            build_blue_green_deployment_response(status="AVAILABLE"),
        ],
        get_blue_green_deployment_valid_upgrade_targets=[DEFAULT_VALID_UPGRADE_TARGETS],
        get_db_parameters=[DEFAULT_SOURCE_DB_PARAMETERS],
    )
    expected_params = CreateBlueGreenDeploymentParams(
        name="test-rds",
        source_arn="some-arn",
        tags={
            "app": "external-resources-poc",
            "cluster": "appint-ex-01",
            "environment": "stage",
            "managed_by_integration": "external_resources",
            "namespace": "external-resources-poc",
        },
    )
    expected_create_action = CreateAction(
        type=ActionType.CREATE,
        next_state=State.PROVISIONING,
        payload=expected_params,
    )
    expected_wait_for_available_action = WaitForAvailableAction(
        type=ActionType.WAIT_FOR_AVAILABLE,
        next_state=State.AVAILABLE,
    )
    manager = BlueGreenDeploymentManager(
        aws_api=mock_aws_api,
        app_interface_input=input_object(additional_data),
        dry_run=dry_run,
    )

    state = manager.run()

    assert state == expected_state
    mock_logging.info.assert_has_calls([
        call(f"Action create: {expected_create_action.model_dump_json()}"),
        call(
            f"Action wait_for_available: {expected_wait_for_available_action.model_dump_json()}"
        ),
    ])
    if dry_run:
        mock_aws_api.get_db_instance.assert_called_once_with("test-rds")
        mock_aws_api.create_blue_green_deployment.assert_not_called()
        mock_aws_api.get_blue_green_deployment.assert_called_once_with("test-rds")
    else:
        mock_logging.info.assert_has_calls([
            call("Waiting for condition to be met..."),
            call(
                f"Target DB instances endpoints: {[DEFAULT_TARGET_RDS_INSTANCE['Endpoint']]}"
            ),
        ])
        assert mock_aws_api.get_db_instance.call_count == 2
        assert mock_aws_api.get_blue_green_deployment.call_count == 2
        mock_aws_api.create_blue_green_deployment.assert_called_once_with(
            expected_params
        )


@pytest.mark.parametrize(
    ("dry_run", "expected_state"),
    [
        (True, State.INIT),
        (False, State.AVAILABLE),
    ],
)
def test_run_create_blue_green_deployment_with_default_target(
    mock_aws_api: Mock,
    mock_logging: Mock,
    *,
    dry_run: bool,
    expected_state: State,
) -> None:
    """Test create default"""
    additional_data = build_blue_green_deployment_data(enabled=True)
    setup_aws_api_side_effects(
        mock_aws_api,
        get_db_instance=[DEFAULT_RDS_INSTANCE, DEFAULT_TARGET_RDS_INSTANCE],
        get_blue_green_deployment=[
            None,
            build_blue_green_deployment_response(status="AVAILABLE"),
        ],
        get_db_parameter_group=[DEFAULT_TARGET_PARAMETER_GROUP],
        get_blue_green_deployment_valid_upgrade_targets=[DEFAULT_VALID_UPGRADE_TARGETS],
        get_db_parameters=[DEFAULT_SOURCE_DB_PARAMETERS],
    )
    expected_params = CreateBlueGreenDeploymentParams(
        name="test-rds",
        source_arn="some-arn",
        allocated_storage=20,
        engine_version="15.7",
        instance_class="db.t4g.micro",
        iops=3000,
        parameter_group_name="test-rds-pg15",
        storage_throughput=125,
        storage_type="gp3",
        tags={
            "app": "external-resources-poc",
            "cluster": "appint-ex-01",
            "environment": "stage",
            "managed_by_integration": "external_resources",
            "namespace": "external-resources-poc",
        },
    )
    expected_create_action = CreateAction(
        type=ActionType.CREATE,
        next_state=State.PROVISIONING,
        payload=expected_params,
    )
    expected_wait_for_available_action = WaitForAvailableAction(
        type=ActionType.WAIT_FOR_AVAILABLE,
        next_state=State.AVAILABLE,
    )
    manager = BlueGreenDeploymentManager(
        aws_api=mock_aws_api,
        app_interface_input=input_object(additional_data),
        dry_run=dry_run,
    )

    state = manager.run()

    assert state == expected_state
    mock_logging.info.assert_has_calls([
        call(f"Action create: {expected_create_action.model_dump_json()}"),
        call(
            f"Action wait_for_available: {expected_wait_for_available_action.model_dump_json()}"
        ),
    ])
    if dry_run:
        mock_aws_api.get_db_instance.assert_called_once_with("test-rds")
        mock_aws_api.create_blue_green_deployment.assert_not_called()
        mock_aws_api.get_blue_green_deployment.assert_called_once_with("test-rds")
    else:
        assert mock_aws_api.get_db_instance.call_count == 2
        assert mock_aws_api.get_blue_green_deployment.call_count == 2
        mock_aws_api.create_blue_green_deployment.assert_called_once_with(
            expected_params
        )


@pytest.mark.parametrize("dry_run", [True, False])
def test_run_create_blue_green_deployment_when_rds_not_found(
    mock_aws_api: Mock,
    *,
    dry_run: bool,
) -> None:
    """Test create when not found"""
    setup_aws_api_side_effects(
        mock_aws_api,
        get_db_instance=[None],
        get_blue_green_deployment=[None],
        get_db_parameter_group=[DEFAULT_TARGET_PARAMETER_GROUP],
    )
    additional_data = build_blue_green_deployment_data(enabled=True)
    manager = BlueGreenDeploymentManager(
        aws_api=mock_aws_api,
        app_interface_input=input_object(additional_data),
        dry_run=dry_run,
    )

    with pytest.raises(ValidationError, match=r".*DB Instance not found: test-rds.*"):
        manager.run()

    mock_aws_api.get_db_instance.assert_called_once_with("test-rds")


@pytest.mark.parametrize(
    ("dry_run", "expected_state"),
    [
        (True, State.PROVISIONING),
        (False, State.AVAILABLE),
    ],
)
def test_run_when_create_blue_green_deployment_when_already_created(
    mock_aws_api: Mock,
    mock_logging: Mock,
    *,
    dry_run: bool,
    expected_state: State,
) -> None:
    """Test create when already created"""
    setup_aws_api_side_effects(
        mock_aws_api,
        get_db_instance=[
            DEFAULT_RDS_INSTANCE,
            DEFAULT_RDS_INSTANCE,
            DEFAULT_TARGET_RDS_INSTANCE,
            DEFAULT_TARGET_RDS_INSTANCE,
        ],
        get_blue_green_deployment=[
            build_blue_green_deployment_response(status="PROVISIONING"),
            build_blue_green_deployment_response(status="AVAILABLE"),
        ],
        get_db_parameter_group=[DEFAULT_TARGET_PARAMETER_GROUP],
        get_blue_green_deployment_valid_upgrade_targets=[DEFAULT_VALID_UPGRADE_TARGETS],
        get_db_parameters=[DEFAULT_SOURCE_DB_PARAMETERS],
    )
    additional_data = build_blue_green_deployment_data(enabled=True)
    expected_wait_for_available_action = WaitForAvailableAction(
        type=ActionType.WAIT_FOR_AVAILABLE,
        next_state=State.AVAILABLE,
    )
    manager = BlueGreenDeploymentManager(
        aws_api=mock_aws_api,
        app_interface_input=input_object(additional_data),
        dry_run=dry_run,
    )

    state = manager.run()

    assert state == expected_state
    mock_aws_api.create_blue_green_deployment.assert_not_called()
    mock_logging.info.assert_has_calls([
        call(
            f"Action wait_for_available: {expected_wait_for_available_action.model_dump_json()}"
        )
    ])
    if dry_run:
        mock_aws_api.get_blue_green_deployment.assert_called_once_with("test-rds")
    else:
        mock_logging.info.assert_has_calls([
            call("Waiting for condition to be met..."),
            call(
                f"Target DB instances endpoints: {[DEFAULT_TARGET_RDS_INSTANCE['Endpoint']]}"
            ),
        ])
        assert mock_aws_api.get_blue_green_deployment.call_count == 2


@pytest.mark.parametrize(
    ("dry_run", "expected_state"),
    [
        (True, State.PROVISIONING),
        (False, State.AVAILABLE),
    ],
)
def test_run_when_blue_green_deployment_available_but_target_instance_not_available(
    mock_aws_api: Mock,
    mock_logging: Mock,
    *,
    dry_run: bool,
    expected_state: State,
) -> None:
    """Test switchover in progress"""
    setup_aws_api_side_effects(
        mock_aws_api,
        get_db_instance=[
            DEFAULT_RDS_INSTANCE,
            DEFAULT_RDS_INSTANCE,
            DEFAULT_TARGET_RDS_INSTANCE | {"DBInstanceStatus": "storage-optimization"},
            DEFAULT_TARGET_RDS_INSTANCE,
        ],
        get_blue_green_deployment=[
            build_blue_green_deployment_response(status="AVAILABLE"),
            build_blue_green_deployment_response(status="AVAILABLE"),
        ],
        get_db_parameter_group=[DEFAULT_TARGET_PARAMETER_GROUP],
        get_blue_green_deployment_valid_upgrade_targets=[DEFAULT_VALID_UPGRADE_TARGETS],
        get_db_parameters=[DEFAULT_SOURCE_DB_PARAMETERS],
    )
    additional_data = build_blue_green_deployment_data(enabled=True)
    expected_wait_for_available_action = WaitForAvailableAction(
        type=ActionType.WAIT_FOR_AVAILABLE,
        next_state=State.AVAILABLE,
    )
    manager = BlueGreenDeploymentManager(
        aws_api=mock_aws_api,
        app_interface_input=input_object(additional_data),
        dry_run=dry_run,
    )

    state = manager.run()

    assert state == expected_state
    mock_aws_api.create_blue_green_deployment.assert_not_called()
    mock_logging.info.assert_has_calls([
        call(
            f"Action wait_for_available: {expected_wait_for_available_action.model_dump_json()}"
        )
    ])
    if dry_run:
        mock_aws_api.get_blue_green_deployment.assert_called_once_with("test-rds")
        assert mock_aws_api.get_db_instance.call_count == 3
    else:
        mock_logging.info.assert_has_calls([
            call("Waiting for condition to be met..."),
            call(
                f"Target DB instances endpoints: {[DEFAULT_TARGET_RDS_INSTANCE['Endpoint']]}"
            ),
        ])
        assert mock_aws_api.get_blue_green_deployment.call_count == 2
        assert mock_aws_api.get_db_instance.call_count == 4


@pytest.mark.parametrize("dry_run", [True, False])
def test_run_when_create_blue_green_deployment_with_parameter_group_not_found(
    mock_aws_api: Mock,
    mock_logging: Mock,
    *,
    dry_run: bool,
) -> None:
    """Test create when parameter group not found"""
    setup_aws_api_side_effects(
        mock_aws_api,
        get_db_instance=[DEFAULT_RDS_INSTANCE],
        get_db_parameter_group=[None],
        get_blue_green_deployment=[None],
        get_blue_green_deployment_valid_upgrade_targets=[DEFAULT_VALID_UPGRADE_TARGETS],
        get_db_parameters=[DEFAULT_SOURCE_DB_PARAMETERS],
    )
    additional_data = build_blue_green_deployment_data(enabled=True)
    manager = BlueGreenDeploymentManager(
        aws_api=mock_aws_api,
        app_interface_input=input_object(additional_data),
        dry_run=dry_run,
    )

    state = manager.run()

    assert state == State.PENDING_PREPARE
    mock_aws_api.get_db_parameter_group.assert_called_once_with("test-rds-pg15")
    mock_aws_api.create_blue_green_deployment.assert_not_called()
    mock_logging.info.assert_has_calls([
        call("Pending prepares needed: target_parameter_group"),
    ])


@pytest.mark.parametrize(
    ("dry_run", "expected_state"),
    [
        (True, State.AVAILABLE),
        (False, State.SWITCHOVER_COMPLETED),
    ],
)
def test_run_when_switchover(
    mock_aws_api: Mock,
    mock_logging: Mock,
    *,
    dry_run: bool,
    expected_state: State,
) -> None:
    """Test switchover"""
    setup_aws_api_side_effects(
        mock_aws_api,
        get_db_instance=[
            DEFAULT_RDS_INSTANCE,
            DEFAULT_RDS_INSTANCE,
            DEFAULT_TARGET_RDS_INSTANCE,
        ],
        get_blue_green_deployment=[
            build_blue_green_deployment_response(status="AVAILABLE"),
            build_blue_green_deployment_response(status="SWITCHOVER_COMPLETED"),
        ],
        get_db_parameter_group=[DEFAULT_TARGET_PARAMETER_GROUP],
        get_blue_green_deployment_valid_upgrade_targets=[DEFAULT_VALID_UPGRADE_TARGETS],
        get_db_parameters=[DEFAULT_SOURCE_DB_PARAMETERS],
    )
    additional_data = build_blue_green_deployment_data(enabled=True, switchover=True)
    expected_switchover_action = SwitchoverAction(
        type=ActionType.SWITCHOVER,
        next_state=State.SWITCHOVER_IN_PROGRESS,
    )
    expected_wait_for_switchover_action = WaitForSwitchoverCompletedAction(
        type=ActionType.WAIT_FOR_SWITCHOVER_COMPLETED,
        next_state=State.SWITCHOVER_COMPLETED,
    )
    manager = BlueGreenDeploymentManager(
        aws_api=mock_aws_api,
        app_interface_input=input_object(additional_data),
        dry_run=dry_run,
    )

    state = manager.run()

    assert state == expected_state
    mock_logging.info.assert_has_calls([
        call(f"Action switchover: {expected_switchover_action.model_dump_json()}"),
        call(
            f"Action wait_for_switchover_completed: {expected_wait_for_switchover_action.model_dump_json()}"
        ),
    ])
    if dry_run:
        mock_aws_api.switchover_blue_green_deployment.assert_not_called()
        mock_aws_api.get_blue_green_deployment.assert_called_once_with("test-rds")
    else:
        mock_logging.info.assert_called_with("Waiting for condition to be met...")
        mock_aws_api.switchover_blue_green_deployment.assert_called_once_with(
            "some-bg-id",
            timeout=None,
        )
        assert mock_aws_api.get_blue_green_deployment.call_count == 2


@pytest.mark.parametrize(
    ("dry_run", "expected_state"),
    [
        (True, State.SWITCHOVER_IN_PROGRESS),
        (False, State.SWITCHOVER_COMPLETED),
    ],
)
def test_run_when_switchover_in_progress(
    mock_aws_api: Mock,
    mock_logging: Mock,
    *,
    dry_run: bool,
    expected_state: State,
) -> None:
    """Test switchover in progress"""
    setup_aws_api_side_effects(
        mock_aws_api,
        get_db_instance=[
            DEFAULT_RDS_INSTANCE,
            DEFAULT_RDS_INSTANCE,
            DEFAULT_TARGET_RDS_INSTANCE,
        ],
        get_blue_green_deployment=[
            build_blue_green_deployment_response(status="SWITCHOVER_IN_PROGRESS"),
            build_blue_green_deployment_response(status="SWITCHOVER_COMPLETED"),
        ],
        get_db_parameter_group=[DEFAULT_TARGET_PARAMETER_GROUP],
        get_blue_green_deployment_valid_upgrade_targets=[DEFAULT_VALID_UPGRADE_TARGETS],
        get_db_parameters=[DEFAULT_SOURCE_DB_PARAMETERS],
    )
    additional_data = build_blue_green_deployment_data(enabled=True, switchover=True)
    expected_wait_for_switchover_action = WaitForSwitchoverCompletedAction(
        type=ActionType.WAIT_FOR_SWITCHOVER_COMPLETED,
        next_state=State.SWITCHOVER_COMPLETED,
    )
    manager = BlueGreenDeploymentManager(
        aws_api=mock_aws_api,
        app_interface_input=input_object(additional_data),
        dry_run=dry_run,
    )

    state = manager.run()

    assert state == expected_state
    mock_aws_api.switchover_blue_green_deployment.assert_not_called()
    mock_logging.info.assert_has_calls([
        call(
            f"Action wait_for_switchover_completed: {expected_wait_for_switchover_action.model_dump_json()}"
        )
    ])
    if dry_run:
        mock_aws_api.get_blue_green_deployment.assert_called_once_with("test-rds")
    else:
        mock_logging.info.assert_called_with("Waiting for condition to be met...")
        assert mock_aws_api.get_blue_green_deployment.call_count == 2


@pytest.mark.parametrize(
    ("dry_run", "expected_state"),
    [
        (True, State.SWITCHOVER_COMPLETED),
        (False, State.NO_OP),
    ],
)
def test_run_when_delete_after_switchover(
    mock_aws_api: Mock,
    mock_logging: Mock,
    *,
    dry_run: bool,
    expected_state: State,
) -> None:
    """Test delete after switchover"""
    setup_aws_api_side_effects(
        mock_aws_api,
        get_db_instance=[
            DEFAULT_RDS_INSTANCE
            | {
                "DBInstanceArn": "some-arn-new",
                "DBInstanceStatus": "available",
                "DBInstanceIdentifier": "test-rds",
            },
            DEFAULT_RDS_INSTANCE
            | {
                "DBInstanceArn": "some-arn-old",
                "DBInstanceStatus": "available",
                "DBInstanceIdentifier": "test-rds-old",
            },
            DEFAULT_RDS_INSTANCE
            | {
                "DBInstanceArn": "some-arn-new",
                "DBInstanceStatus": "available",
                "DBInstanceIdentifier": "test-rds",
            },
            DEFAULT_RDS_INSTANCE
            | {
                "DBInstanceArn": "some-arn-old",
                "DBInstanceStatus": "available",
                "DBInstanceIdentifier": "test-rds-old",
            },
            None,
        ],
        get_blue_green_deployment=[
            build_blue_green_deployment_response(
                status="SWITCHOVER_COMPLETED",
                switchover_details=[
                    {
                        "SourceMember": "some-arn-old",
                        "TargetMember": "some-arn-new",
                        "Status": "SWITCHOVER_COMPLETED",
                    }
                ],
            ),
            None,
        ],
        get_db_parameter_group=[DEFAULT_TARGET_PARAMETER_GROUP],
        get_blue_green_deployment_valid_upgrade_targets=[DEFAULT_VALID_UPGRADE_TARGETS],
        get_db_parameters=[DEFAULT_SOURCE_DB_PARAMETERS],
    )
    additional_data = build_blue_green_deployment_data(
        enabled=True, switchover=True, delete=True
    )
    expected_delete_source_db_instance_action = DeleteSourceDBInstanceAction(
        type=ActionType.DELETE_SOURCE_DB_INSTANCE,
        next_state=State.DELETING_SOURCE_DB_INSTANCES,
    )
    expected_wait_for_source_db_instances_deleted_action = (
        WaitForSourceDBInstancesDeletedAction(
            type=ActionType.WAIT_FOR_SOURCE_DB_INSTANCES_DELETED,
            next_state=State.SOURCE_DB_INSTANCES_DELETED,
        )
    )
    expected_delete_action = DeleteAction(
        type=ActionType.DELETE,
        next_state=State.DELETING,
    )
    expected_wait_for_deleted_action = WaitForDeletedAction(
        type=ActionType.WAIT_FOR_DELETED,
        next_state=State.NO_OP,
    )
    manager = BlueGreenDeploymentManager(
        aws_api=mock_aws_api,
        app_interface_input=input_object(additional_data),
        dry_run=dry_run,
    )

    state = manager.run()

    assert state == expected_state
    mock_aws_api.get_db_instance.assert_has_calls([
        call("test-rds"),
        call("some-arn-old"),
    ])
    mock_logging.info.assert_has_calls(
        [
            call(
                f"Action delete_source_db_instance: {expected_delete_source_db_instance_action.model_dump_json()}"
            ),
            call(
                f"Action wait_for_source_db_instances_deleted: {expected_wait_for_source_db_instances_deleted_action.model_dump_json()}"
            ),
            call(f"Action delete: {expected_delete_action.model_dump_json()}"),
            call(
                f"Action wait_for_deleted: {expected_wait_for_deleted_action.model_dump_json()}"
            ),
        ],
        any_order=True,
    )
    if dry_run:
        assert mock_aws_api.get_db_instance.call_count == 3
        mock_aws_api.delete_db_instance.assert_not_called()
        mock_aws_api.delete_blue_green_deployment.assert_not_called()
        mock_aws_api.get_blue_green_deployment.assert_called_once_with("test-rds")
    else:
        mock_logging.info.assert_called_with("Waiting for condition to be met...")
        assert mock_aws_api.get_db_instance.call_count == 5
        mock_aws_api.delete_db_instance.assert_called_once_with("test-rds-old")
        mock_aws_api.delete_blue_green_deployment.assert_called_once_with("some-bg-id")
        assert mock_aws_api.get_blue_green_deployment.call_count == 2


@pytest.mark.parametrize(
    ("dry_run", "expected_state"),
    [
        (True, State.SOURCE_DB_INSTANCES_DELETED),
        (False, State.NO_OP),
    ],
)
def test_run_when_delete_after_switchover_and_source_deleted(
    mock_aws_api: Mock,
    mock_logging: Mock,
    *,
    dry_run: bool,
    expected_state: State,
) -> None:
    """Test delete after switchover and source deleted"""
    setup_aws_api_side_effects(
        mock_aws_api,
        get_db_instance=[
            DEFAULT_TARGET_RDS_INSTANCE,
            None,
            DEFAULT_TARGET_RDS_INSTANCE,
        ],
        get_blue_green_deployment=[
            build_blue_green_deployment_response(
                status="SWITCHOVER_COMPLETED",
                switchover_details=[
                    {
                        "SourceMember": "some-arn-old",
                        "TargetMember": "some-arn-new",
                        "Status": "SWITCHOVER_COMPLETED",
                    }
                ],
            ),
            None,
        ],
        get_db_parameter_group=[DEFAULT_TARGET_PARAMETER_GROUP],
        get_blue_green_deployment_valid_upgrade_targets=[DEFAULT_VALID_UPGRADE_TARGETS],
        get_db_parameters=[DEFAULT_SOURCE_DB_PARAMETERS],
    )
    additional_data = build_blue_green_deployment_data(
        enabled=True, switchover=True, delete=True
    )
    expected_delete_action = DeleteAction(
        type=ActionType.DELETE,
        next_state=State.DELETING,
    )
    expected_wait_for_deleted_action = WaitForDeletedAction(
        type=ActionType.WAIT_FOR_DELETED,
        next_state=State.NO_OP,
    )
    manager = BlueGreenDeploymentManager(
        aws_api=mock_aws_api,
        app_interface_input=input_object(additional_data),
        dry_run=dry_run,
    )

    state = manager.run()

    assert state == expected_state
    mock_aws_api.get_db_instance.assert_has_calls([
        call("test-rds"),
        call("some-arn-old"),
    ])
    mock_logging.info.assert_has_calls([
        call(f"Action delete: {expected_delete_action.model_dump_json()}"),
        call(
            f"Action wait_for_deleted: {expected_wait_for_deleted_action.model_dump_json()}"
        ),
    ])
    mock_aws_api.delete_db_instance.assert_not_called()
    if dry_run:
        mock_aws_api.delete_blue_green_deployment.assert_not_called()
        mock_aws_api.get_blue_green_deployment.assert_called_once_with("test-rds")
    else:
        mock_logging.info.assert_called_with("Waiting for condition to be met...")
        mock_aws_api.delete_blue_green_deployment.assert_called_once_with("some-bg-id")
        assert mock_aws_api.get_blue_green_deployment.call_count == 2


@pytest.mark.parametrize(
    ("dry_run", "expected_state"),
    [
        (True, State.AVAILABLE),
        (False, State.NO_OP),
    ],
)
def test_run_when_delete_without_switchover(
    mock_aws_api: Mock,
    mock_logging: Mock,
    *,
    dry_run: bool,
    expected_state: State,
) -> None:
    """Test delete without switchover"""
    setup_aws_api_side_effects(
        mock_aws_api,
        get_db_instance=[
            DEFAULT_RDS_INSTANCE,
            DEFAULT_RDS_INSTANCE,
            DEFAULT_TARGET_RDS_INSTANCE,
        ],
        get_blue_green_deployment=[
            build_blue_green_deployment_response(status="AVAILABLE"),
            None,
        ],
        get_db_parameter_group=[DEFAULT_TARGET_PARAMETER_GROUP],
        get_blue_green_deployment_valid_upgrade_targets=[DEFAULT_VALID_UPGRADE_TARGETS],
        get_db_parameters=[DEFAULT_SOURCE_DB_PARAMETERS],
    )
    additional_data = build_blue_green_deployment_data(
        enabled=True, switchover=False, delete=True
    )
    expected_delete_without_switchover_action = DeleteWithoutSwitchoverAction(
        type=ActionType.DELETE_WITHOUT_SWITCHOVER,
        next_state=State.DELETING,
    )
    expected_wait_for_deleted_action = WaitForDeletedAction(
        type=ActionType.WAIT_FOR_DELETED,
        next_state=State.NO_OP,
    )
    manager = BlueGreenDeploymentManager(
        aws_api=mock_aws_api,
        app_interface_input=input_object(additional_data),
        dry_run=dry_run,
    )

    state = manager.run()

    assert state == expected_state
    mock_logging.info.assert_has_calls([
        call(
            f"Action delete_without_switchover: {expected_delete_without_switchover_action.model_dump_json()}"
        ),
        call(
            f"Action wait_for_deleted: {expected_wait_for_deleted_action.model_dump_json()}"
        ),
    ])
    mock_aws_api.delete_db_instance.assert_not_called()
    if dry_run:
        mock_aws_api.delete_blue_green_deployment.assert_not_called()
        mock_aws_api.get_blue_green_deployment.assert_called_once_with("test-rds")
    else:
        mock_logging.info.assert_called_with("Waiting for condition to be met...")
        mock_aws_api.delete_blue_green_deployment.assert_called_once_with(
            "some-bg-id",
            delete_target=True,
        )
        assert mock_aws_api.get_blue_green_deployment.call_count == 2


@pytest.mark.parametrize(
    ("switchover", "target", "dry_run"),
    [
        (True, {}, True),
        (True, {}, False),
        (True, DEFAULT_TARGET, True),
        (True, DEFAULT_TARGET, False),
        (False, {}, True),
        (False, {}, False),
        (False, DEFAULT_TARGET, True),
        (False, DEFAULT_TARGET, False),
    ],
)
def test_run_when_no_changes_and_no_blue_green_deployment(
    mock_aws_api: Mock,
    mock_logging: Mock,
    *,
    switchover: bool,
    target: dict | None,
    dry_run: bool,
) -> None:
    """Test no changes and no blue/green deployment"""
    setup_aws_api_side_effects(
        mock_aws_api,
        get_db_instance=[DEFAULT_RDS_INSTANCE],
        get_blue_green_deployment=[None],
        get_db_parameter_group=[DEFAULT_TARGET_PARAMETER_GROUP],
        get_blue_green_deployment_valid_upgrade_targets=[DEFAULT_VALID_UPGRADE_TARGETS],
        get_db_parameters=[DEFAULT_SOURCE_DB_PARAMETERS],
    )
    additional_data = build_blue_green_deployment_data(
        enabled=True,
        switchover=switchover,
        delete=True,
        target=target,
    )
    manager = BlueGreenDeploymentManager(
        aws_api=mock_aws_api,
        app_interface_input=input_object(additional_data),
        dry_run=dry_run,
    )

    state = manager.run()

    assert state == State.NO_OP
    mock_aws_api.get_db_instance.assert_called_once_with("test-rds")
    mock_aws_api.get_blue_green_deployment.assert_called_once_with("test-rds")
    mock_logging.info.assert_called_once_with("No changes for Blue/Green Deployment.")


@pytest.mark.parametrize(
    ("dry_run", "expected_state"),
    [
        (True, State.INIT),
        (False, State.NO_OP),
    ],
)
def test_run_when_all_in_one_config(
    mock_aws_api: Mock,
    mock_logging: Mock,
    *,
    dry_run: bool,
    expected_state: State,
) -> None:
    """Test all in one config"""
    setup_aws_api_side_effects(
        mock_aws_api,
        get_db_instance=[
            DEFAULT_RDS_INSTANCE,
            DEFAULT_TARGET_RDS_INSTANCE,
            {
                "DBInstanceArn": "some-arn-old",
                "DBInstanceStatus": "available",
                "DBInstanceIdentifier": "test-rds-old",
            },
            None,
        ],
        get_blue_green_deployment=[
            None,
            build_blue_green_deployment_response(status="AVAILABLE"),
            build_blue_green_deployment_response(status="SWITCHOVER_COMPLETED"),
            None,
        ],
        get_db_parameter_group=[DEFAULT_TARGET_PARAMETER_GROUP],
        get_blue_green_deployment_valid_upgrade_targets=[DEFAULT_VALID_UPGRADE_TARGETS],
        get_db_parameters=[DEFAULT_SOURCE_DB_PARAMETERS],
    )
    additional_data = build_blue_green_deployment_data(
        enabled=True,
        switchover=True,
        switchover_timeout=600,
        delete=True,
        target={"engine_version": "16.3"},
    )
    expected_params = CreateBlueGreenDeploymentParams(
        name="test-rds",
        source_arn="some-arn",
        engine_version="16.3",
        tags={
            "app": "external-resources-poc",
            "cluster": "appint-ex-01",
            "environment": "stage",
            "managed_by_integration": "external_resources",
            "namespace": "external-resources-poc",
        },
    )
    expected_create_action = CreateAction(
        type=ActionType.CREATE,
        next_state=State.PROVISIONING,
        payload=expected_params,
    )
    expected_wait_for_available_action = WaitForAvailableAction(
        type=ActionType.WAIT_FOR_AVAILABLE,
        next_state=State.AVAILABLE,
    )
    expected_switchover_action = SwitchoverAction(
        type=ActionType.SWITCHOVER,
        next_state=State.SWITCHOVER_IN_PROGRESS,
    )
    expected_wait_for_switchover_action = WaitForSwitchoverCompletedAction(
        type=ActionType.WAIT_FOR_SWITCHOVER_COMPLETED,
        next_state=State.SWITCHOVER_COMPLETED,
    )
    expected_delete_source_db_instance_action = DeleteSourceDBInstanceAction(
        type=ActionType.DELETE_SOURCE_DB_INSTANCE,
        next_state=State.DELETING_SOURCE_DB_INSTANCES,
    )
    expected_wait_for_source_db_instances_deleted_action = (
        WaitForSourceDBInstancesDeletedAction(
            type=ActionType.WAIT_FOR_SOURCE_DB_INSTANCES_DELETED,
            next_state=State.SOURCE_DB_INSTANCES_DELETED,
        )
    )
    expected_delete_action = DeleteAction(
        type=ActionType.DELETE,
        next_state=State.DELETING,
    )
    expected_wait_for_deleted_action = WaitForDeletedAction(
        type=ActionType.WAIT_FOR_DELETED,
        next_state=State.NO_OP,
    )
    manager = BlueGreenDeploymentManager(
        aws_api=mock_aws_api,
        app_interface_input=input_object(additional_data),
        dry_run=dry_run,
    )

    state = manager.run()

    assert state == expected_state
    mock_logging.info.assert_has_calls(
        [
            call(f"Action create: {expected_create_action.model_dump_json()}"),
            call(
                f"Action wait_for_available: {expected_wait_for_available_action.model_dump_json()}"
            ),
            call(f"Action switchover: {expected_switchover_action.model_dump_json()}"),
            call(
                f"Action wait_for_switchover_completed: {expected_wait_for_switchover_action.model_dump_json()}"
            ),
            call(
                f"Action delete_source_db_instance: {expected_delete_source_db_instance_action.model_dump_json()}"
            ),
            call(
                f"Action wait_for_source_db_instances_deleted: {expected_wait_for_source_db_instances_deleted_action.model_dump_json()}"
            ),
            call(f"Action delete: {expected_delete_action.model_dump_json()}"),
            call(
                f"Action wait_for_deleted: {expected_wait_for_deleted_action.model_dump_json()}"
            ),
        ],
        any_order=True,
    )
    if dry_run:
        mock_aws_api.create_blue_green_deployment.assert_not_called()
        mock_aws_api.switchover_blue_green_deployment.assert_not_called()
        mock_aws_api.delete_db_instance.assert_not_called()
        mock_aws_api.delete_blue_green_deployment.assert_not_called()
    else:
        mock_logging.info.assert_called_with("Waiting for condition to be met...")
        mock_aws_api.create_blue_green_deployment.assert_called_once_with(
            expected_params
        )
        mock_aws_api.switchover_blue_green_deployment.assert_called_once_with(
            "some-bg-id",
            timeout=600,
        )
        mock_aws_api.delete_db_instance.assert_called_once_with("test-rds-old")
        mock_aws_api.delete_blue_green_deployment.assert_called_once_with("some-bg-id")


@pytest.mark.parametrize(
    ("dry_run", "expected_state"),
    [
        (True, State.REPLICA_SOURCE_ENABLED),
        (False, State.REPLICA_SOURCE_ENABLED),
    ],
)
def test_run_for_read_replica_has_blue_green_deployment_enabled(
    mock_aws_api: Mock,
    mock_logging: Mock,
    *,
    dry_run: bool,
    expected_state: State,
) -> None:
    """Test read replica"""
    additional_data = {
        "data": {
            "replica_source": {
                "identifier": "test-rds-source",
                "region": "us-east-1",
                "blue_green_deployment": {
                    "enabled": True,
                },
            },
            "parameter_group": None,
        }
    }
    manager = BlueGreenDeploymentManager(
        aws_api=mock_aws_api,
        app_interface_input=input_object(additional_data),
        dry_run=dry_run,
    )

    state = manager.run()

    assert state == expected_state
    mock_logging.info.assert_called_once_with(
        "blue_green_deployment in replica_source enabled."
    )


@pytest.mark.parametrize(
    ("status", "status_details", "expected_instruction"),
    [
        (
            "INVALID_CONFIGURATION",
            "green database is still catching up",
            "blue_green_deployment.delete: true",
        ),
        (
            "SWITCHOVER_FAILED",
            "replication is behind",
            "blue_green_deployment.switchover: false",
        ),
    ],
)
def test_terminal_failure_during_availability_polling_fails_promptly(
    mock_aws_api: Mock,
    mock_logging: Mock,
    *,
    status: str,
    status_details: str,
    expected_instruction: str,
) -> None:
    """Report terminal AWS status details instead of waiting for availability."""
    del mock_logging
    setup_aws_api_side_effects(
        mock_aws_api,
        get_db_instance=[DEFAULT_RDS_INSTANCE],
        get_blue_green_deployment=[
            build_blue_green_deployment_response(
                status="PROVISIONING", switchover_details=[]
            ),
            build_blue_green_deployment_response(
                status=status,
                switchover_details=[],
                status_details=status_details,
            ),
        ],
        get_db_parameter_group=[DEFAULT_TARGET_PARAMETER_GROUP],
        get_blue_green_deployment_valid_upgrade_targets=[DEFAULT_VALID_UPGRADE_TARGETS],
        get_db_parameters=[DEFAULT_SOURCE_DB_PARAMETERS],
    )
    manager = BlueGreenDeploymentManager(
        aws_api=mock_aws_api,
        app_interface_input=input_object(
            build_blue_green_deployment_data(enabled=True)
        ),
        dry_run=False,
    )

    with pytest.raises(RuntimeError) as error:
        manager.run()

    message = str(error.value)
    assert "some-bg-id" in message
    assert status in message
    assert status_details in message
    assert expected_instruction in message
    mock_aws_api.get_blue_green_deployment.assert_has_calls([
        call("test-rds"),
        call("test-rds"),
    ])
    mock_aws_api.delete_blue_green_deployment.assert_not_called()


def test_fresh_invalid_configuration_requires_explicit_delete(
    mock_aws_api: Mock,
    mock_logging: Mock,
) -> None:
    """Do not run creation checks or cleanup unless delete is requested."""
    del mock_logging
    setup_aws_api_side_effects(
        mock_aws_api,
        get_blue_green_deployment=[
            build_blue_green_deployment_response(
                status="INVALID_CONFIGURATION",
                status_details="target is invalid",
            )
        ],
    )
    manager = BlueGreenDeploymentManager(
        aws_api=mock_aws_api,
        app_interface_input=input_object(
            build_blue_green_deployment_data(enabled=True)
        ),
        dry_run=False,
    )

    with pytest.raises(RuntimeError, match=r"blue_green_deployment\.delete: true"):
        manager.run()

    mock_aws_api.get_db_instance.assert_not_called()
    mock_aws_api.get_blue_green_deployment_valid_upgrade_targets.assert_not_called()
    mock_aws_api.get_db_parameter_group.assert_not_called()
    mock_aws_api.delete_blue_green_deployment.assert_not_called()


def test_fresh_failed_switchover_fails_even_when_delete_is_requested(
    mock_aws_api: Mock,
    mock_logging: Mock,
) -> None:
    """A failed switchover is reported instead of starting another action."""
    del mock_logging
    setup_aws_api_side_effects(
        mock_aws_api,
        get_blue_green_deployment=[
            build_blue_green_deployment_response(
                status="SWITCHOVER_FAILED",
                status_details="replication is behind",
            )
        ],
    )
    manager = BlueGreenDeploymentManager(
        aws_api=mock_aws_api,
        app_interface_input=input_object(
            build_blue_green_deployment_data(enabled=True, switchover=True, delete=True)
        ),
        dry_run=False,
    )

    with pytest.raises(RuntimeError, match="SWITCHOVER_FAILED") as error:
        manager.run()

    assert "replication is behind" in str(error.value)
    mock_aws_api.get_db_instance.assert_not_called()
    mock_aws_api.switchover_blue_green_deployment.assert_not_called()
    mock_aws_api.delete_blue_green_deployment.assert_not_called()


def test_delete_invalid_configuration_uses_delete_without_switchover(
    mock_aws_api: Mock,
    mock_logging: Mock,
) -> None:
    """An explicit delete request takes the cleanup path without creation checks."""
    del mock_logging
    setup_aws_api_side_effects(
        mock_aws_api,
        get_blue_green_deployment=[
            build_blue_green_deployment_response(status="INVALID_CONFIGURATION"),
            None,
        ],
    )
    manager = BlueGreenDeploymentManager(
        aws_api=mock_aws_api,
        app_interface_input=input_object(
            build_blue_green_deployment_data(enabled=True, delete=True)
        ),
        dry_run=False,
    )

    assert manager.run() == State.NO_OP

    mock_aws_api.get_db_instance.assert_not_called()
    mock_aws_api.delete_db_instance.assert_not_called()
    mock_aws_api.delete_blue_green_deployment.assert_called_once_with(
        "some-bg-id", delete_target=True
    )
    assert mock_aws_api.get_blue_green_deployment.call_count == 2


def test_delete_requested_before_invalid_configuration_is_detected_while_waiting(
    mock_aws_api: Mock,
    mock_logging: Mock,
) -> None:
    """Use the no-switchover cleanup path when polling discovers the failure."""
    del mock_logging
    setup_aws_api_side_effects(
        mock_aws_api,
        get_db_instance=[DEFAULT_RDS_INSTANCE],
        get_blue_green_deployment=[
            build_blue_green_deployment_response(
                status="PROVISIONING", switchover_details=[]
            ),
            build_blue_green_deployment_response(
                status="INVALID_CONFIGURATION", switchover_details=[]
            ),
            None,
        ],
        get_db_parameter_group=[DEFAULT_TARGET_PARAMETER_GROUP],
        get_blue_green_deployment_valid_upgrade_targets=[DEFAULT_VALID_UPGRADE_TARGETS],
        get_db_parameters=[DEFAULT_SOURCE_DB_PARAMETERS],
    )
    manager = BlueGreenDeploymentManager(
        aws_api=mock_aws_api,
        app_interface_input=input_object(
            build_blue_green_deployment_data(enabled=True, delete=True)
        ),
        dry_run=False,
    )

    assert manager.run() == State.NO_OP

    mock_aws_api.delete_blue_green_deployment.assert_called_once_with(
        "some-bg-id", delete_target=True
    )
    mock_aws_api.delete_db_instance.assert_not_called()
    assert mock_aws_api.get_blue_green_deployment.call_count == 3


def test_delete_invalid_configuration_propagates_aws_error(
    mock_aws_api: Mock,
    mock_logging: Mock,
) -> None:
    """Surface AWS delete failures without starting an unbounded deletion wait."""
    del mock_logging
    setup_aws_api_side_effects(
        mock_aws_api,
        get_blue_green_deployment=[
            build_blue_green_deployment_response(status="INVALID_CONFIGURATION")
        ],
    )
    mock_aws_api.delete_blue_green_deployment.side_effect = RuntimeError(
        "InvalidBlueGreenDeploymentStateFault"
    )
    manager = BlueGreenDeploymentManager(
        aws_api=mock_aws_api,
        app_interface_input=input_object(
            build_blue_green_deployment_data(enabled=True, delete=True)
        ),
        dry_run=False,
    )

    with pytest.raises(RuntimeError, match="InvalidBlueGreenDeploymentStateFault"):
        manager.run()

    mock_aws_api.delete_blue_green_deployment.assert_called_once_with(
        "some-bg-id", delete_target=True
    )
    mock_aws_api.get_blue_green_deployment.assert_called_once_with("test-rds")


@pytest.mark.parametrize(
    ("initial_status", "poll_statuses", "expected_message"),
    [
        (
            "SWITCHOVER_IN_PROGRESS",
            ["SWITCHOVER_FAILED"],
            "SWITCHOVER_FAILED",
        ),
        (
            "AVAILABLE",
            ["SWITCHOVER_IN_PROGRESS", "AVAILABLE"],
            "cancelled or rolled back",
        ),
    ],
)
def test_failed_or_cancelled_switchover_does_not_delete_source(
    mock_aws_api: Mock,
    mock_logging: Mock,
    *,
    initial_status: str,
    poll_statuses: list[str],
    expected_message: str,
) -> None:
    """Stop before source deletion if AWS fails or cancels the switchover."""
    del mock_logging
    setup_aws_api_side_effects(
        mock_aws_api,
        get_db_instance=[
            DEFAULT_RDS_INSTANCE,
            DEFAULT_RDS_INSTANCE,
            DEFAULT_TARGET_RDS_INSTANCE,
        ],
        get_blue_green_deployment=[
            build_blue_green_deployment_response(status=initial_status),
            *[
                build_blue_green_deployment_response(
                    status=status,
                    status_details="green database is still catching up",
                )
                for status in poll_statuses
            ],
        ],
        get_db_parameter_group=[DEFAULT_TARGET_PARAMETER_GROUP],
        get_blue_green_deployment_valid_upgrade_targets=[DEFAULT_VALID_UPGRADE_TARGETS],
        get_db_parameters=[DEFAULT_SOURCE_DB_PARAMETERS],
    )
    manager = BlueGreenDeploymentManager(
        aws_api=mock_aws_api,
        app_interface_input=input_object(
            build_blue_green_deployment_data(enabled=True, switchover=True)
        ),
        dry_run=False,
    )

    def no_sleep_wait_for(
        condition: Callable[[], bool],
        *,
        logger: Logger,
        timeout: int | None = None,
        interval: int = 60,
    ) -> None:
        del logger, timeout, interval
        while not condition():
            pass

    with (
        patch(
            "hooks.utils.blue_green_deployment_manager.wait_for",
            side_effect=no_sleep_wait_for,
        ),
        pytest.raises(RuntimeError, match=expected_message) as error,
    ):
        manager.run()

    assert "green database is still catching up" in str(error.value)
    mock_aws_api.delete_db_instance.assert_not_called()
    mock_aws_api.delete_blue_green_deployment.assert_not_called()


def test_initial_available_status_is_not_switchover_cancellation(
    mock_aws_api: Mock,
    mock_logging: Mock,
) -> None:
    """An AVAILABLE response before observed progress is polled through."""
    del mock_logging
    setup_aws_api_side_effects(
        mock_aws_api,
        get_db_instance=[
            DEFAULT_RDS_INSTANCE,
            DEFAULT_RDS_INSTANCE,
            DEFAULT_TARGET_RDS_INSTANCE,
        ],
        get_blue_green_deployment=[
            build_blue_green_deployment_response(status="AVAILABLE"),
            build_blue_green_deployment_response(status="AVAILABLE"),
            build_blue_green_deployment_response(status="SWITCHOVER_IN_PROGRESS"),
            build_blue_green_deployment_response(status="SWITCHOVER_COMPLETED"),
        ],
        get_db_parameter_group=[DEFAULT_TARGET_PARAMETER_GROUP],
        get_blue_green_deployment_valid_upgrade_targets=[DEFAULT_VALID_UPGRADE_TARGETS],
        get_db_parameters=[DEFAULT_SOURCE_DB_PARAMETERS],
    )
    manager = BlueGreenDeploymentManager(
        aws_api=mock_aws_api,
        app_interface_input=input_object(
            build_blue_green_deployment_data(enabled=True, switchover=True)
        ),
        dry_run=False,
    )

    def no_sleep_wait_for(
        condition: Callable[[], bool],
        *,
        logger: Logger,
        timeout: int | None = None,
        interval: int = 60,
    ) -> None:
        del logger, timeout, interval
        while not condition():
            pass

    with patch(
        "hooks.utils.blue_green_deployment_manager.wait_for",
        side_effect=no_sleep_wait_for,
    ) as wait_for_mock:
        assert manager.run() == State.SWITCHOVER_COMPLETED

    mock_aws_api.switchover_blue_green_deployment.assert_called_once_with(
        "some-bg-id", timeout=None
    )
    assert mock_aws_api.get_blue_green_deployment.call_count == 4
    assert wait_for_mock.call_args.kwargs["timeout"] == 300


def test_switchover_wait_timeout_reports_last_status(
    mock_aws_api: Mock,
    mock_logging: Mock,
) -> None:
    """Bound a resumed switchover wait by the configured timeout."""
    del mock_logging
    setup_aws_api_side_effects(
        mock_aws_api,
        get_db_instance=[DEFAULT_RDS_INSTANCE],
        get_blue_green_deployment=[
            build_blue_green_deployment_response(
                status="SWITCHOVER_IN_PROGRESS", switchover_details=[]
            ),
            build_blue_green_deployment_response(
                status="SWITCHOVER_IN_PROGRESS",
                switchover_details=[],
                status_details="replication is progressing",
            ),
        ],
        get_db_parameter_group=[DEFAULT_TARGET_PARAMETER_GROUP],
        get_blue_green_deployment_valid_upgrade_targets=[DEFAULT_VALID_UPGRADE_TARGETS],
        get_db_parameters=[DEFAULT_SOURCE_DB_PARAMETERS],
    )
    manager = BlueGreenDeploymentManager(
        aws_api=mock_aws_api,
        app_interface_input=input_object(
            build_blue_green_deployment_data(
                enabled=True, switchover=True, switchover_timeout=123
            )
        ),
        dry_run=False,
    )

    def time_out(
        condition: Callable[[], bool],
        *,
        logger: Logger,
        timeout: int | None = None,
        interval: int = 60,
    ) -> None:
        del logger, interval
        assert timeout == 123
        assert not condition()
        raise TimeoutError("condition wait expired")

    with (
        patch(
            "hooks.utils.blue_green_deployment_manager.wait_for",
            side_effect=time_out,
        ),
        pytest.raises(TimeoutError) as error,
    ):
        manager.run()

    message = str(error.value)
    assert "some-bg-id" in message
    assert "123 seconds" in message
    assert "SWITCHOVER_IN_PROGRESS" in message
    assert "replication is progressing" in message
    assert "blue_green_deployment.switchover: false" in message
    mock_aws_api.delete_db_instance.assert_not_called()
