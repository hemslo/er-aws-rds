import pytest
from mypy_boto3_rds.type_defs import ParameterOutputTypeDef
from pydantic import ValidationError

from er_aws_rds.input import (
    BlueGreenDeployment,
    BlueGreenDeploymentTarget,
    ParameterGroup,
    Rds,
)
from hooks.utils.blue_green_deployment_model import BlueGreenDeploymentModel
from hooks.utils.models import PendingPrepare, State
from tests.conftest import (
    DEFAULT_RDS_INSTANCE,
    DEFAULT_SOURCE_DB_PARAMETERS,
    DEFAULT_VALID_UPGRADE_TARGETS,
)


def build_blue_green_deployment_input_data(
    *,
    switchover: bool = False,
    delete: bool = False,
    target: BlueGreenDeploymentTarget | None = None,
    deletion_protection: bool = False,
) -> Rds:
    """Build Rds input object"""
    return Rds(
        identifier="test-rds",
        region="us-east-1",
        output_prefix="prefixed-test-rds",
        deletion_protection=deletion_protection,
        blue_green_deployment=BlueGreenDeployment(
            enabled=True,
            switchover=switchover,
            delete=delete,
            target=target,
        ),
    )


def test_validate_db_instance_exist() -> None:
    """Test validate db instance exist"""
    with pytest.raises(ValidationError, match=r".*DB Instance not found: test-rds.*"):
        BlueGreenDeploymentModel(
            state=State.INIT,
            input_data=build_blue_green_deployment_input_data(),
            db_instance=None,
        )


def test_validate_target_parameter_group() -> None:
    """Test validate target parameter group"""
    model = BlueGreenDeploymentModel(
        state=State.INIT,
        input_data=build_blue_green_deployment_input_data(
            target=BlueGreenDeploymentTarget(
                parameter_group=ParameterGroup(family="postgres15", name="pg15")
            )
        ),
        db_instance=DEFAULT_RDS_INSTANCE,
        target_db_parameter_group=None,
        valid_upgrade_targets=DEFAULT_VALID_UPGRADE_TARGETS,
    )

    assert model.pending_prepares == [PendingPrepare.TARGET_PARAMETER_GROUP]


def test_validate_deletion_protection() -> None:
    """Test validate deletion protection"""
    with pytest.raises(
        ValidationError, match=r".*deletion_protection must be disabled.*"
    ):
        BlueGreenDeploymentModel(
            state=State.INIT,
            input_data=build_blue_green_deployment_input_data(deletion_protection=True),
            db_instance=DEFAULT_RDS_INSTANCE | {"DeletionProtection": True},
            valid_upgrade_targets=DEFAULT_VALID_UPGRADE_TARGETS,
        )


def test_validate_deletion_protection_requires_pending_prepare() -> None:
    """Test validate deletion protection requires pending prepare"""
    model = BlueGreenDeploymentModel(
        state=State.INIT,
        input_data=build_blue_green_deployment_input_data(deletion_protection=False),
        db_instance=DEFAULT_RDS_INSTANCE | {"DeletionProtection": True},
        valid_upgrade_targets=DEFAULT_VALID_UPGRADE_TARGETS,
    )

    assert model.pending_prepares == [PendingPrepare.DELETION_PROTECTION]


def test_validate_backup_retention_period() -> None:
    """Test validate backup retention period"""
    with pytest.raises(
        ValidationError, match=r".*backup_retention_period must be greater than 0.*"
    ):
        BlueGreenDeploymentModel(
            state=State.INIT,
            input_data=build_blue_green_deployment_input_data(),
            db_instance=DEFAULT_RDS_INSTANCE | {"BackupRetentionPeriod": 0},
        )


def test_validate_version_upgrade_when_target_set() -> None:
    """Test validate version upgrade when target set"""
    with pytest.raises(
        ValidationError,
        match=r".*target engine_version 16.1 is not valid, valid versions: 16.3.*",
    ):
        BlueGreenDeploymentModel(
            state=State.INIT,
            input_data=build_blue_green_deployment_input_data(
                target=BlueGreenDeploymentTarget(engine_version="16.1")
            ),
            db_instance=DEFAULT_RDS_INSTANCE,
            valid_upgrade_targets={
                "16.3": {"EngineVersion": "16.3", "IsMajorVersionUpgrade": True},
            },
        )


def test_validate_version_upgrade_when_target_not_set() -> None:
    """Test validate version upgrade when target not set"""
    with pytest.raises(
        ValidationError,
        match=r".*target engine_version 15.7 is not valid, valid versions: 16.3.*",
    ):
        BlueGreenDeploymentModel(
            state=State.INIT,
            input_data=build_blue_green_deployment_input_data(),
            db_instance=DEFAULT_RDS_INSTANCE,
            valid_upgrade_targets={
                "16.3": {"EngineVersion": "16.3", "IsMajorVersionUpgrade": True},
            },
        )


@pytest.mark.parametrize(
    "engine_version",
    [
        "5.5.1",
        "5.6.2",
    ],
)
def test_validate_supported_engine_version_for_mysql(
    engine_version: str,
) -> None:
    """Test validate supported engine version for mysql"""
    with pytest.raises(
        ValidationError,
        match=rf".*mysql engine_version {engine_version} is not supported for blue/green deployment.*",
    ):
        BlueGreenDeploymentModel(
            state=State.INIT,
            input_data=build_blue_green_deployment_input_data(
                target=BlueGreenDeploymentTarget(engine_version="8.4.4")
            ),
            db_instance=DEFAULT_RDS_INSTANCE
            | {"EngineVersion": engine_version, "Engine": "mysql"},
            valid_upgrade_targets={
                "8.4.4": {"EngineVersion": "8.4.4", "IsMajorVersionUpgrade": True},
            },
        )


@pytest.mark.parametrize(
    "engine_version",
    [
        "5.7.44",
        "8.0.32",
        "8.4.3",
    ],
)
def test_validate_supported_engine_version_for_mysql_ok(
    engine_version: str,
) -> None:
    """Test validate supported engine version for mysql OK"""
    model = BlueGreenDeploymentModel(
        state=State.INIT,
        input_data=build_blue_green_deployment_input_data(
            target=BlueGreenDeploymentTarget(engine_version="8.4.4")
        ),
        db_instance=DEFAULT_RDS_INSTANCE
        | {"EngineVersion": engine_version, "Engine": "mysql"},
        valid_upgrade_targets={
            "8.4.4": {"EngineVersion": "8.4.4", "IsMajorVersionUpgrade": True},
        },
    )
    assert model is not None


@pytest.mark.parametrize(
    "engine_version",
    [
        "16.0",
        "15.3",
        "14.8",
        "13.11",
        "12.15",
        "11.20",
    ],
)
def test_validate_supported_engine_version_for_postgres_major_version_upgrade(
    engine_version: str,
) -> None:
    """Test validate supported engine version for postgres major version upgrade"""
    with pytest.raises(
        ValidationError,
        match=rf".*postgres engine_version {engine_version} is not supported for blue/green deployment.*",
    ):
        BlueGreenDeploymentModel(
            state=State.INIT,
            input_data=build_blue_green_deployment_input_data(
                target=BlueGreenDeploymentTarget(engine_version="17.1")
            ),
            db_instance=DEFAULT_RDS_INSTANCE | {"EngineVersion": engine_version},
            valid_upgrade_targets={
                "17.1": {"EngineVersion": "17.1", "IsMajorVersionUpgrade": True},
            },
        )


@pytest.mark.parametrize(
    "engine_version",
    [
        "17.1",
        "16.1",
        "16.2",
        "15.4",
        "15.5",
        "14.9",
        "14.10",
        "13.12",
        "13.13",
        "12.16",
        "12.17",
        "11.21",
        "11.22",
    ],
)
def test_validate_supported_engine_version_for_postgres_major_version_upgrade_ok(
    engine_version: str,
) -> None:
    """Test validate supported engine version for postgres major version upgrade ok"""
    model = BlueGreenDeploymentModel(
        state=State.INIT,
        input_data=build_blue_green_deployment_input_data(
            target=BlueGreenDeploymentTarget(engine_version="18.0")
        ),
        db_instance=DEFAULT_RDS_INSTANCE | {"EngineVersion": engine_version},
        valid_upgrade_targets={
            "18.0": {"EngineVersion": "18.0", "IsMajorVersionUpgrade": True},
        },
        source_db_parameters=DEFAULT_SOURCE_DB_PARAMETERS,
    )
    assert model is not None


@pytest.mark.parametrize(
    "engine_version",
    [
        "16.0",
        "15.3",
        "14.8",
        "13.11",
        "12.15",
        "11.20",
    ],
)
def test_validate_supported_engine_version_for_postgres_non_major_version_upgrade(
    engine_version: str,
) -> None:
    """Test validate supported engine version for postgres non-major version upgrade"""
    model = BlueGreenDeploymentModel(
        state=State.INIT,
        input_data=build_blue_green_deployment_input_data(
            target=BlueGreenDeploymentTarget(engine_version=engine_version)
        ),
        db_instance=DEFAULT_RDS_INSTANCE | {"EngineVersion": engine_version},
        valid_upgrade_targets={
            engine_version: {
                "EngineVersion": engine_version,
                "IsMajorVersionUpgrade": False,
            },
        },
    )
    assert model is not None


@pytest.mark.parametrize(
    "status",
    [
        "applying",
        "failed-to-apply",
        "pending-database-upgrade",
        "pending-reboot",
    ],
)
def test_validate_source_parameter_group_status(status: str) -> None:
    """Test validate source parameter group status"""
    db_instance = DEFAULT_RDS_INSTANCE | {
        "DBParameterGroups": [
            {
                "DBParameterGroupName": "test-rds-pg15",
                "ParameterApplyStatus": status,
            }
        ]
    }
    with pytest.raises(
        ValidationError,
        match=r".*Source Parameter Group status is not in-sync: .*",
    ):
        BlueGreenDeploymentModel(
            state=State.INIT,
            input_data=build_blue_green_deployment_input_data(),
            db_instance=db_instance,
            valid_upgrade_targets=DEFAULT_VALID_UPGRADE_TARGETS,
        )


@pytest.mark.parametrize(
    "source_db_parameters",
    [
        {},
        {
            "rds.logical_replication": {
                "ParameterName": "rds.logical_replication",
                "ParameterValue": "0",
                "ApplyMethod": "pending-reboot",
            }
        },
    ],
)
def test_validate_source_db_parameters(
    source_db_parameters: dict[str, ParameterOutputTypeDef],
) -> None:
    """Test validate source db parameters"""
    with pytest.raises(
        ValidationError,
        match=r".*Source Parameter Group rds.logical_replication must be 1 for major version upgrade.*",
    ):
        BlueGreenDeploymentModel(
            state=State.INIT,
            input_data=build_blue_green_deployment_input_data(
                target=BlueGreenDeploymentTarget(engine_version="16.3")
            ),
            db_instance=DEFAULT_RDS_INSTANCE,
            valid_upgrade_targets=DEFAULT_VALID_UPGRADE_TARGETS,
            source_db_parameters=source_db_parameters,
        )


def test_validate_source_db_parameters_for_non_major_version_upgrade() -> None:
    """Test validate source db parameters for minor version upgrade"""
    model = BlueGreenDeploymentModel(
        state=State.INIT,
        input_data=build_blue_green_deployment_input_data(
            target=BlueGreenDeploymentTarget(engine_version="15.7")
        ),
        db_instance=DEFAULT_RDS_INSTANCE,
        valid_upgrade_targets=DEFAULT_VALID_UPGRADE_TARGETS,
        source_db_parameters={},
    )
    assert model is not None
