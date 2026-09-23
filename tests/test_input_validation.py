import pytest
from pydantic_core import ValidationError

from er_aws_rds.input import (
    ENHANCED_MONITORING_ROLE_NAME_MAX_LENGTH,
    AppInterfaceInput,
    BlueGreenDeploymentTarget,
    Parameter,
    ParameterGroup,
)

from .conftest import DEFAULT_PARAMETER_GROUP, DEFAULT_TARGET, input_data


def test_parameter_value_as_string() -> None:
    """Test that parameters are serialized as strings"""
    assert Parameter(name="test", value=60).model_dump(exclude_none=True) == {
        "name": "test",
        "value": "60",
    }


def test_parameter_group_name() -> None:
    """Test correct parameter group names are set"""
    model = AppInterfaceInput.model_validate(input_data())
    assert model.data.parameter_group is not None
    expected_parameter_group_name = f"{model.data.identifier}-test-pg"
    assert model.data.parameter_group.name == expected_parameter_group_name
    assert model.data.parameter_group_name == expected_parameter_group_name


def test_parameter_group_name_without_pg_name() -> None:
    """Test correct parameter group names are set"""
    mod_input = input_data({"data": {"parameter_group": {"name": None}}})
    model = AppInterfaceInput.model_validate(mod_input)
    assert model.data.parameter_group is not None
    assert model.data.parameter_group.name == f"{model.data.identifier}-pg"


def test_blue_green_deployment_parameter_group_default_name() -> None:
    """Test Blue/Green Deployment parameter group default name"""
    mod_input = input_data({
        "data": {
            "blue_green_deployment": {
                "enabled": True,
                "switchover": True,
                "delete": False,
                "target": {
                    "parameter_group": {
                        "family": "postgres16",
                    }
                },
            }
        }
    })
    model = AppInterfaceInput.model_validate(mod_input)
    assert model.data.blue_green_deployment is not None
    assert model.data.blue_green_deployment.target == BlueGreenDeploymentTarget(
        parameter_group=ParameterGroup(
            name=f"{model.data.identifier}-pg",
            family="postgres16",
        )
    )


def test_blue_green_deployment_parameter_group_name() -> None:
    """Test Blue/Green Deployment parameter group name"""
    mod_input = input_data({
        "data": {
            "blue_green_deployment": {
                "enabled": True,
                "switchover": True,
                "delete": False,
                "target": {
                    "parameter_group": {
                        "name": "new-pg",
                        "family": "postgres16",
                    }
                },
            }
        }
    })
    model = AppInterfaceInput.model_validate(mod_input)
    assert model.data.blue_green_deployment is not None
    assert model.data.blue_green_deployment.target == BlueGreenDeploymentTarget(
        parameter_group=ParameterGroup(
            name=f"{model.data.identifier}-new-pg",
            family="postgres16",
        )
    )


@pytest.mark.parametrize("enabled", [True, False])
def test_blue_green_deployment_parameter_group_same_name_different_values(
    *,
    enabled: bool,
) -> None:
    """Test Blue/Green Deployment parameter group name"""
    target_parameter_group = DEFAULT_PARAMETER_GROUP | {"family": "postgres15"}
    mod_input = input_data({
        "data": {
            "parameter_group": DEFAULT_PARAMETER_GROUP,
            "blue_green_deployment": {
                "enabled": enabled,
                "switchover": False,
                "delete": False,
                "target": {"parameter_group": target_parameter_group},
            },
        }
    })
    with pytest.raises(
        ValidationError,
        match="Blue/Green Deployment Parameter Group name already exist",
    ):
        AppInterfaceInput.model_validate(mod_input)


def test_name() -> None:
    """Test name not set validates ok"""
    mod_input = input_data()
    mod_input["data"].pop("name")
    AppInterfaceInput.model_validate(mod_input)


def test_enhanced_monitoring_sets_default_monitoring_interval() -> None:
    """monitoring_interval != 0 enables enhanced_monitoring"""
    model = AppInterfaceInput.model_validate(
        input_data({
            "data": {
                "enhanced_monitoring": True,
            }
        })
    )
    assert model.data.monitoring_interval == 60


def test_enhanced_monitoring_custom_monitoring_interval() -> None:
    """Test for enhanced monitoring tests"""
    model = AppInterfaceInput.model_validate(
        input_data({"data": {"enhanced_monitoring": True, "monitoring_interval": 90}})
    )
    assert model.data.monitoring_interval == 90


def test_no_enhanced_monitoring_disables_enhanced_monitoring() -> None:
    """enhanced_monitoring_configuration requires enhanced_monitoring"""
    model = AppInterfaceInput.model_validate(
        input_data({
            "data": {
                "enhanced_monitoring": False,
                "monitoring_interval": 90,
                "monitoring_role_arn": "arn:bla:bla",
            }
        })
    )
    assert model.data.monitoring_interval is None
    assert model.data.monitoring_role_arn is None


def test_enhanced_monitoring_with_monitoring_interval_0() -> None:
    """enhanced_monitoring_configuration requires enhanced_monitoring"""
    with pytest.raises(
        ValidationError,
        match=r".*Monitoring interval can not be 0 when enhanced monitoring is enabled.*",
    ):
        AppInterfaceInput.model_validate(
            input_data({
                "data": {
                    "enhanced_monitoring": True,
                    "monitoring_interval": 0,
                }
            })
        )


def test_monitoring_role_arn_requires_monitoring_interval() -> None:
    """monitoring_role_arn requires monitoring_interval != 0"""
    mod_input = input_data({
        "data": {
            "enhanced_monitoring": True,
            "monitoring_role_arn": "A-Role-ARN",
        }
    })
    model = AppInterfaceInput.model_validate(mod_input)
    assert model.data.monitoring_interval == 60
    assert model.data.monitoring_role_arn == "A-Role-ARN"


def test_very_long_enhanced_monitoring_role_name() -> None:
    """Enhanced monitoring role name must be less than 64 characters"""
    mod_input = input_data({
        "data": {
            "identifier": "a-very-long-identifier-that-will-generate-a-very-long-role-name",
        }
    })
    model = AppInterfaceInput.model_validate(mod_input)
    assert (
        len(model.data.enhanced_monitoring_role_name)
        == ENHANCED_MONITORING_ROLE_NAME_MAX_LENGTH
    )
    assert (
        model.data.enhanced_monitoring_role_name
        == "a-very-long-identifier-that-will-generate-a-very-long-role-na-em"
    )


def test_kms_key_id_alias_removed() -> None:
    """Test that kms_key_id_alias is removed from the input data"""
    mod_input = input_data({
        "data": {
            "kms_key_id": "alias/test",
        }
    })
    model = AppInterfaceInput.model_validate(mod_input)
    assert model.data.kms_key_id == "test"


def test_timeouts() -> None:
    """Test timeouts data"""
    mod_input = input_data({"data": {"timeouts": {"create": "60m"}}})
    model = AppInterfaceInput.model_validate(mod_input)
    assert model.data.timeouts is not None
    assert model.data.timeouts.create == "60m"


def test_validate_blue_green_update() -> None:
    """Test blue_green_update"""
    mod_input = input_data({"data": {"blue_green_update": {"enabled": True}}})
    with pytest.raises(
        ValidationError,
        match=r"blue_green_update is not supported, use blue_green_deployment instead",
    ):
        AppInterfaceInput.model_validate(mod_input)


def test_validate_blue_green_deployment_for_replica_with_parameter_group() -> None:
    """Test blue_green_deployment for replica with parameter group"""
    mod_input = input_data({
        "data": {
            "replica_source": {
                "identifier": "test-rds-source",
                "region": "us-east-1",
                "blue_green_deployment": {
                    "enabled": True,
                },
            },
            "parameter_group": DEFAULT_PARAMETER_GROUP,
        }
    })
    with pytest.raises(
        ValidationError,
        match=r".*parameter_group is not supported when replica_source has blue_green_deployment enabled.*",
    ):
        AppInterfaceInput.model_validate(mod_input)


def test_validate_blue_green_deployment_for_replica_with_deletion_protection() -> None:
    """Test blue_green_deployment for replica with deletion protection"""
    mod_input = input_data({
        "data": {
            "replica_source": {
                "identifier": "test-rds-source",
                "region": "us-east-1",
                "blue_green_deployment": {
                    "enabled": True,
                },
            },
            "parameter_group": None,
            "deletion_protection": True,
        }
    })
    with pytest.raises(
        ValidationError,
        match=r".*deletion_protection must be disabled when replica_source has blue_green_deployment enabled.*",
    ):
        AppInterfaceInput.model_validate(mod_input)


def test_validate_blue_green_deployment_for_replica_when_desired_config_not_match_target() -> (
    None
):
    """Test replica desired config match target"""
    mod_input = input_data({
        "data": {
            "replica_source": {
                "identifier": "test-rds-source",
                "region": "us-east-1",
                "blue_green_deployment": {
                    "enabled": True,
                    "switchover": True,
                    "delete": True,
                    "target": DEFAULT_TARGET,
                },
            },
            "parameter_group": None,
        }
    })
    expected_not_matched = {
        "engine_version": "15.7",
    }
    with pytest.raises(
        ValidationError,
        match=rf".*desired config not match replica_source blue_green_deployment.target, update: {expected_not_matched}.*",
    ):
        AppInterfaceInput.model_validate(mod_input)


def test_validate_blue_green_deployment_for_replica() -> None:
    """Test that blue_green_deployment is not supported for replica instance"""
    mod_input = input_data({
        "data": {
            "replica_source": {
                "identifier": "test-rds-source",
                "region": "us-east-1",
                "blue_green_deployment": {
                    "enabled": False,
                },
            },
            "blue_green_deployment": {
                "enabled": False,
                "switchover": False,
                "delete": False,
            },
        }
    })
    with pytest.raises(
        ValidationError,
        match=r".*blue_green_deployment is not supported for replica instance.*",
    ):
        AppInterfaceInput.model_validate(mod_input)


def test_validate_blue_green_deployment_for_cross_region_replica() -> None:
    """Test that cross-region read replicas are not supported for blue green deployments"""
    mod_input = input_data({
        "data": {
            "replica_source": {
                "identifier": "test-rds-source",
                "region": "us-east-1",
                "blue_green_deployment": {
                    "enabled": True,
                },
            },
            "region": "us-west-2",
            "db_subnet_group_name": "test-subnet-group",
            "parameter_group": None,
        }
    })
    with pytest.raises(
        ValidationError,
        match=r".*Cross-region read replicas are not currently supported for Blue Green Deployments*",
    ):
        AppInterfaceInput.model_validate(mod_input)


def test_validate_blue_green_deployment_when_desired_config_not_match_target_after_delete() -> (
    None
):
    """Test that desired config not match target after delete"""
    mod_input = input_data({
        "data": {
            "blue_green_deployment": {
                "enabled": True,
                "switchover": True,
                "delete": True,
                "target": DEFAULT_TARGET,
            },
        }
    })
    with pytest.raises(
        ValidationError,
        match=r".*desired config not match blue_green_deployment.target after delete, update: .*",
    ):
        AppInterfaceInput.model_validate(mod_input)


def test_copy_tags_to_snapshot_default_true() -> None:
    """Test copy_tags_to_snapshot default True"""
    mod_input = input_data()
    model = AppInterfaceInput.model_validate(mod_input)
    assert model.data.copy_tags_to_snapshot is True


@pytest.mark.parametrize(
    ("replica_config", "expected_source"),
    [
        pytest.param(
            {
                "replicate_source_db": (
                    "arn:aws:rds:us-east-1:123456789012:db:test-rds-source"
                ),
            },
            "arn:aws:rds:us-east-1:123456789012:db:test-rds-source",
            id="direct",
        ),
        pytest.param(
            {
                "replica_source": {
                    "identifier": "test-rds-source",
                    "region": "us-east-1",
                },
                "db_subnet_group_name": None,
            },
            "test-rds-source",
            id="same-region",
        ),
        pytest.param(
            {
                "replica_source": {
                    "identifier": "test-rds-source",
                    "region": "us-west-2",
                },
                "db_subnet_group_name": "custom-subnet-group",
            },
            None,
            id="cross-region",
        ),
    ],
)
def test_allocated_storage_is_preserved_for_read_replicas(
    replica_config: dict,
    expected_source: str | None,
) -> None:
    """Keep explicitly configured storage for every read-replica input form."""
    model = AppInterfaceInput.model_validate(input_data({"data": replica_config}))

    assert model.data.allocated_storage == 20
    assert model.data.replicate_source_db == expected_source
    assert model.data.username is None
    assert model.data.password is None
    assert model.data.name is None


def test_allocated_storage_is_preserved_for_snapshot_restore() -> None:
    """Keep explicitly configured storage for snapshot restores."""
    model = AppInterfaceInput.model_validate(
        input_data({"data": {"snapshot_identifier": "test-snapshot"}})
    )

    assert model.data.allocated_storage == 20
    assert model.data.username is None
    assert model.data.password is None
    assert model.data.name is None


@pytest.mark.parametrize(
    "source_config",
    [
        pytest.param(
            {"replicate_source_db": "test-rds-source"},
            id="replica",
        ),
        pytest.param(
            {"snapshot_identifier": "test-snapshot"},
            id="snapshot",
        ),
    ],
)
def test_null_allocated_storage_remains_unmanaged(source_config: dict) -> None:
    """Do not manage storage when it is explicitly null."""
    model = AppInterfaceInput.model_validate(
        input_data({"data": source_config | {"allocated_storage": None}})
    )

    assert model.data.allocated_storage is None


@pytest.mark.parametrize(
    "source_config",
    [
        pytest.param(
            {"replicate_source_db": "test-rds-source"},
            id="replica",
        ),
        pytest.param(
            {"snapshot_identifier": "test-snapshot"},
            id="snapshot",
        ),
    ],
)
def test_omitted_allocated_storage_remains_unmanaged(source_config: dict) -> None:
    """Do not manage storage when it is omitted from the input."""
    mod_input = input_data({"data": source_config})
    mod_input["data"].pop("allocated_storage")

    model = AppInterfaceInput.model_validate(mod_input)

    assert model.data.allocated_storage is None


def test_same_region_replica_without_db_subnet_group_name() -> None:
    """Test same-region replica sets replicate_source_db to source identifier when db_subnet_group_name is not specified"""
    mod_input = input_data({
        "data": {
            "replica_source": {
                "identifier": "test-rds-source",
                "region": "us-east-1",
            },
            "db_subnet_group_name": None,
        }
    })
    model = AppInterfaceInput.model_validate(mod_input)
    assert model.data.replicate_source_db == "test-rds-source"
    assert model.data.db_subnet_group_name is None
    assert model.data.backup_retention_period is None


def test_same_region_replica_with_db_subnet_group_name() -> None:
    """Test same-region replica does not set replicate_source_db when db_subnet_group_name is specified"""
    mod_input = input_data({
        "data": {
            "replica_source": {
                "identifier": "test-rds-source",
                "region": "us-east-1",
            },
            "db_subnet_group_name": "custom-subnet-group",
        }
    })
    model = AppInterfaceInput.model_validate(mod_input)
    assert model.data.replicate_source_db is None
    assert model.data.db_subnet_group_name == "custom-subnet-group"
    assert model.data.backup_retention_period is None


@pytest.mark.parametrize(
    "replica_input",
    [
        {
            "replica_source": {"identifier": "test-rds-source", "region": "us-east-1"},
        },
        {
            "replicate_source_db": "arn:aws:rds:us-east-1:123456789012:db:test-rds-source",
        },
    ],
)
def test_validate_major_version_upgrade_for_postgres_replica(
    replica_input: dict,
) -> None:
    """Test that allow_major_version_upgrade raises error for postgres read replica"""
    mod_input = input_data({
        "data": {
            **replica_input,
            "allow_major_version_upgrade": True,
        }
    })
    with pytest.raises(ValidationError) as exc:
        AppInterfaceInput.model_validate(mod_input)
    assert (
        "allow_major_version_upgrade is not supported for postgres read replica instances"
        in str(exc.value)
    )
