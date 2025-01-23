import pytest
from cdktf import Testing
from pydantic_core import ValidationError

from er_aws_rds.errors import RDSLogicalReplicationError
from er_aws_rds.input import (
    ENHANCED_MONITORING_ROLE_NAME_MAX_LENGTH,
    AppInterfaceInput,
    Parameter,
)

from .conftest import input_data

Testing.__test__ = False


def test_validate_parameter_rds_replication() -> None:
    """Test that rds.logical_replication parameter must be set to 'pending-reboot'"""
    with pytest.raises(RDSLogicalReplicationError):
        AppInterfaceInput.model_validate(
            input_data(
                parameters=[
                    Parameter(
                        name="rds.logical_replication",
                        value="1",
                        apply_method="immediate",
                    ),
                ]
            )
        )


def test_parameter_value_as_string() -> None:
    """Test that parameters are serialized as strings"""
    assert Parameter(name="test", value=60).model_dump(exclude_none=True) == {
        "name": "test",
        "value": "60",
    }


def test_parameter_group_name() -> None:
    """Test correct parameter group names are set"""
    model = AppInterfaceInput.model_validate(input_data([]))
    assert model.data.parameter_group is not None
    assert (
        model.data.parameter_group.computed_pg_name
        == f"{model.data.identifier}-{model.data.parameter_group.name}"
    )


def test_parameter_group_name_without_pg_name() -> None:
    """Test correct parameter group names are set"""
    mod_input = input_data([])
    mod_input["data"]["parameter_group"]["name"] = None
    model = AppInterfaceInput.model_validate(mod_input)
    assert model.data.parameter_group is not None
    assert model.data.parameter_group.computed_pg_name == f"{model.data.identifier}-pg"


def test_parameter_group_name_along_old_parameter_group_1() -> None:
    """Test correct parameter group names are set"""
    mod_input = input_data([])
    mod_input["data"]["old_parameter_group"] = {
        "name": "postgres-16",
        "family": "postgres16",
        "description": "Parameter Group for PostgreSQL 16",
        "parameters": [],
    }
    model = AppInterfaceInput.model_validate(mod_input)
    assert model.data.parameter_group is not None
    assert model.data.old_parameter_group is not None
    assert (
        model.data.parameter_group.computed_pg_name
        == f"{model.data.identifier}-{model.data.parameter_group.name}"
    )
    assert (
        model.data.old_parameter_group.computed_pg_name
        == f"{model.data.identifier}-{model.data.old_parameter_group.name}"
    )


def test_parameter_group_name_along_old_parameter_group_without_names() -> None:
    """Test correct parameter group names are set"""
    mod_input = input_data([])
    mod_input["data"]["parameter_group"]["name"] = None
    mod_input["data"]["old_parameter_group"] = {
        "family": "postgres16",
        "description": "Parameter Group for PostgreSQL 16",
        "parameters": [],
    }
    with pytest.raises(
        ValidationError,
        match=r".*Parameter group and old parameter group have the same name.*",
    ):
        AppInterfaceInput.model_validate(mod_input)


def test_name() -> None:
    """Test name not set validates ok"""
    mod_input = input_data([])
    mod_input["data"].pop("name")
    AppInterfaceInput.model_validate(mod_input)


def test_enhanced_monitoring_configuration_requires_enhanced_monitoring() -> None:
    """enhanced_monitoring_configuration requires enhanced_monitoring"""
    mod_input = input_data([])
    mod_input["data"]["enhanced_monitoring"] = False
    mod_input["data"]["monitoring_interval"] = 60
    with pytest.raises(
        ValidationError,
        match=r".*Enhanced monitoring attributes requires enhanced_monitoring to be true.*",
    ):
        AppInterfaceInput.model_validate(mod_input)

    mod_input["data"]["monitoring_interval"] = 0
    mod_input["data"]["monitoring_role_arn"] = "arn:bla:bla"
    with pytest.raises(
        ValidationError,
        match=r".*Enhanced monitoring attributes requires enhanced_monitoring to be true.*",
    ):
        AppInterfaceInput.model_validate(mod_input)


def test_enhanced_monitoring_requires_monitoring_interval() -> None:
    """monitoring_interval != 0 enables enhanced_monitoring"""
    mod_input = input_data([])
    mod_input["data"]["enhanced_monitoring"] = True
    mod_input["data"]["monitoring_interval"] = 0
    with pytest.raises(
        ValidationError,
        match=r".*enhanced_monitoring requires a monitoring_interval != 0.*",
    ):
        AppInterfaceInput.model_validate(mod_input)


def test_monitoring_role_arn_requires_monitoring_interval() -> None:
    """monitoring_role_arn requires monitoring_interval != 0"""
    mod_input = input_data([])
    mod_input["data"]["enhanced_monitoring"] = True
    mod_input["data"]["monitoring_interval"] = 0
    mod_input["data"]["monitoring_role_arn"] = "A-Role-ARN"
    with pytest.raises(
        ValidationError,
        match=r".*monitoring_role_arn requires a monitoring_interval != 0.*",
    ):
        AppInterfaceInput.model_validate(mod_input)


def test_very_long_enhanced_monitoring_role_name() -> None:
    """Enhanced monitoring role name must be less than 64 characters"""
    mod_input = input_data([])
    mod_input["data"]["identifier"] = (
        "a-very-long-identifier-that-will-generate-a-very-long-role-name"
    )
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
    mod_input = input_data([])
    mod_input["data"]["kms_key_id"] = "alias/test"
    model = AppInterfaceInput.model_validate(mod_input)
    assert model.data.kms_key_id == "test"
