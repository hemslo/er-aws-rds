import pytest

from er_aws_rds.input import AppInterfaceInput, TerraformModuleData

from .conftest import DEFAULT_PARAMETER_GROUP, input_data, input_object

EXPECTED_DEFAULT_PARAMETER_GROUP = DEFAULT_PARAMETER_GROUP | {
    "name": "test-rds-test-pg",
}
BLUE_GREEN_DEPLOYMENT_PARAMETER_GROUP = {
    "name": "postgres-16",
    "family": "postgres16",
    "description": "Parameter Group for PostgreSQL 16",
    "parameters": [],
}
EXPECTED_BLUE_GREEN_DEPLOYMENT_PARAMETER_GROUP = (
    BLUE_GREEN_DEPLOYMENT_PARAMETER_GROUP
    | {
        "name": "test-rds-postgres-16",
    }
)


def test_parameter_group_names() -> None:
    """Ensure terraform model gets the right parameter group names"""
    model = input_object()
    tf_model = TerraformModuleData(ai_input=model).model_dump()

    assert tf_model["parameter_groups"] == [EXPECTED_DEFAULT_PARAMETER_GROUP]


@pytest.mark.parametrize("enabled", [True, False])
def test_parameter_groups_with_blue_green_deployment(*, enabled: bool) -> None:
    """Test parameter groups with blue-green deployment"""
    model = input_object({
        "data": {
            "blue_green_deployment": {
                "enabled": enabled,
                "switchover": False,
                "delete": False,
                "target": {
                    "parameter_group": BLUE_GREEN_DEPLOYMENT_PARAMETER_GROUP,
                },
            },
        }
    })
    tf_model = TerraformModuleData(ai_input=model).model_dump()

    assert tf_model["parameter_groups"] == [
        EXPECTED_DEFAULT_PARAMETER_GROUP,
        EXPECTED_BLUE_GREEN_DEPLOYMENT_PARAMETER_GROUP,
    ]


def test_parameter_groups_when_blue_green_deployment_has_duplicate() -> None:
    """Test parameter groups when blue-green deployment has duplicate"""
    model = input_object({
        "data": {
            "parameter_group": DEFAULT_PARAMETER_GROUP,
            "blue_green_deployment": {
                "enabled": False,
                "switchover": False,
                "delete": False,
                "target": {
                    "parameter_group": DEFAULT_PARAMETER_GROUP,
                },
            },
        }
    })
    tf_model = TerraformModuleData(ai_input=model).model_dump()

    assert tf_model["parameter_groups"] == [EXPECTED_DEFAULT_PARAMETER_GROUP]


@pytest.mark.parametrize(
    "source_config",
    [
        pytest.param(
            {"replicate_source_db": "test-rds-source"},
            id="direct-replica",
        ),
        pytest.param(
            {
                "replica_source": {
                    "identifier": "test-rds-source",
                    "region": "us-east-1",
                },
                "db_subnet_group_name": None,
            },
            id="same-region-replica",
        ),
        pytest.param(
            {
                "replica_source": {
                    "identifier": "test-rds-source",
                    "region": "us-west-2",
                },
                "db_subnet_group_name": "custom-subnet-group",
            },
            id="cross-region-replica",
        ),
        pytest.param(
            {"snapshot_identifier": "test-snapshot"},
            id="snapshot-restore",
        ),
    ],
)
def test_allocated_storage_is_serialized_for_replica_and_snapshot(
    source_config: dict,
) -> None:
    """Serialize configured storage for replicas and snapshot restores."""
    model = input_object({"data": source_config})
    tf_model = TerraformModuleData(ai_input=model).model_dump(exclude_none=True)

    assert tf_model["rds_instance"]["allocated_storage"] == 20


@pytest.mark.parametrize(
    "source_config",
    [
        pytest.param(
            {
                "replicate_source_db": "test-rds-source",
                "allocated_storage": None,
            },
            id="replica-null",
        ),
        pytest.param(
            {"replicate_source_db": "test-rds-source"},
            id="replica",
        ),
        pytest.param(
            {
                "snapshot_identifier": "test-snapshot",
                "allocated_storage": None,
            },
            id="snapshot-null",
        ),
        pytest.param(
            {"snapshot_identifier": "test-snapshot"},
            id="snapshot",
        ),
    ],
)
def test_unset_allocated_storage_is_omitted_from_terraform_serialization(
    source_config: dict,
) -> None:
    """Do not serialize null or omitted storage."""
    mod_input = input_data({"data": source_config})
    if "allocated_storage" not in source_config:
        mod_input["data"].pop("allocated_storage")
    model = AppInterfaceInput.model_validate(mod_input)
    tf_model = TerraformModuleData(ai_input=model).model_dump(exclude_none=True)

    assert "allocated_storage" not in tf_model["rds_instance"]
