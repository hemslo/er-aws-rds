from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator
from typing import Any
from unittest.mock import Mock, patch

import pytest
from external_resources_io.terraform import Action, Plan

from hooks.post_plan import RDSPlanValidator

from .conftest import input_object


@pytest.fixture
def new_instance_plan() -> dict[str, Any]:
    "Return a plan for an rds instance creation"
    return {
        "resource_changes": [
            {
                "type": "aws_db_instance",
                "change": {
                    "actions": [Action.ActionCreate],
                    "before": None,
                    "after": {
                        "engine": "postgres",
                        "engine_version": "16.1",
                        "deletion_protection": False,
                    },
                    "after_unknown": None,
                },
            }
        ]
    }


@pytest.fixture
def mock_aws_api() -> Iterator[Mock]:
    """Patch AWSApi"""
    with patch("hooks.post_plan.AWSApi", autospec=True) as m:
        # Make sure Action.Create tests dont fail because of missing sgA.
        m.return_value.get_security_group_ids_for_db_subnet_group.return_value = {"sgA"}
        yield m


@pytest.mark.parametrize(
    ("is_rds_engine_version_available", "expected_errors"),
    [
        (True, []),
        (False, ["postgres version 16.1 is not available."]),
    ],
)
def test_validate_desired_version(
    new_instance_plan: dict[str, Any],
    mock_aws_api: Mock,
    *,
    is_rds_engine_version_available: bool,
    expected_errors: list[str],
) -> None:
    """Test engine version available in AWS"""
    mock_aws_api.return_value.is_rds_engine_version_available.return_value = (
        is_rds_engine_version_available
    )

    plan = Plan.model_validate(new_instance_plan)
    validator = RDSPlanValidator(plan, input_object())
    errors = validator.validate()
    assert errors == expected_errors


def test_validate_deletion_protection_not_enabled_on_destroy() -> None:
    """Test instance deletion protection is not set when destroying the instance"""
    plan = Plan.model_validate({
        "resource_changes": [
            {
                "type": "aws_db_instance",
                "change": {
                    "actions": [Action.ActionDelete],
                    "before": {
                        "engine": "postgres",
                        "engine_version": "16.1",
                        "deletion_protection": True,
                        "region": "us-east-1",
                    },
                    "after": None,
                    "after_unknown": None,
                },
            }
        ]
    })

    validator = RDSPlanValidator(plan, input_object())
    errors = validator.validate()
    assert (
        "Deletion protection cannot be enabled on destroy. Disable deletion_protection first to remove the instance"
        in errors
    )


def test_validate_version_upgrade(mock_aws_api: Mock) -> None:
    """Test version upgrade validation"""
    mock_aws_api.return_value.get_rds_valid_upgrade_targets.return_value = {
        "16.1": {
            "EngineVersion": "16.1",
            "IsMajorVersionUpgrade": True,
        }
    }
    plan = Plan.model_validate({
        "resource_changes": [
            {
                "type": "aws_db_instance",
                "change": {
                    "actions": [Action.ActionUpdate],
                    "before": {
                        "engine": "postgres",
                        "engine_version": "15.7",
                        "region": "us-east-1",
                    },
                    "after": {
                        "engine": "postgres",
                        "engine_version": "16.1",
                    },
                    "after_unknown": None,
                },
            }
        ]
    })

    validator = RDSPlanValidator(
        plan,
        input_object({
            "data": {
                "allow_major_version_upgrade": False,
            }
        }),
    )
    errors = validator.validate()
    assert errors == [
        "To enable major version upgrade, allow_major_version_upgrade attribute must be set to True"
    ]


@pytest.mark.parametrize(
    "change",
    [
        {
            "type": "aws_db_parameter_group",
            "change": {
                "actions": ["update"],
                "before": {
                    "id": "test-rds-pg15",
                    "name": "test-rds-pg15",
                    "family": "postgres15",
                    "parameter": [
                        {
                            "apply_method": "pending-reboot",
                            "name": "rds.force_ssl",
                            "value": "0",
                        },
                    ],
                    "region": "us-east-1",
                },
                "after": {
                    "id": "test-rds-pg15",
                    "name": "test-rds-pg15",
                    "family": "postgres15",
                    "parameter": [
                        {
                            "apply_method": "pending-reboot",
                            "name": "rds.force_ssl",
                            "value": "1",
                        },
                    ],
                },
                "after_unknown": None,
            },
        },
        {
            "type": "aws_db_instance",
            "change": {
                "actions": ["update"],
                "before": {
                    "id": "some-id",
                    "name": "test-rds",
                    "engine": "postgres",
                    "engine_version": "15.7",
                    "allocated_storage": 30,
                    "region": "us-east-1",
                },
                "after": {
                    "id": "test-rds-pg15",
                    "name": "test-rds-pg15",
                    "engine": "postgres",
                    "engine_version": "15.7",
                    "allocated_storage": 20,
                },
                "after_unknown": {},
            },
        },
    ],
)
def test_validate_no_changes_when_blue_green_deployment_enabled(
    change: dict,
    mock_aws_api: Mock,
) -> None:
    """Test no changes when Blue/Green Deployment is enabled"""
    mock_aws_api.return_value.get_engine_default_parameters.return_value = {
        "rds.force_ssl": {
            "ParameterName": "rds.force_ssl",
            "ParameterValue": "1",
            "ApplyType": "static",
        }
    }
    plan = Plan.model_validate({
        "resource_changes": [
            change,
        ]
    })
    validator = RDSPlanValidator(
        plan,
        input_object({
            "data": {
                "blue_green_deployment": {
                    "enabled": True,
                    "switchover": True,
                    "delete": True,
                }
            }
        }),
    )

    errors = validator.validate()

    assert errors == [
        (
            "There are pending resource changes after a Blue/Green Deployment. "
            "Check the Terraform plan output."
        )
    ]


@pytest.mark.parametrize(
    "change",
    [
        {
            "type": "aws_db_instance",
            "change": {
                "actions": ["delete"],
                "before": {
                    "id": "some-id",
                    "name": "test-rds",
                    "engine": "postgres",
                    "engine_version": "16.3",
                    "region": "us-east-1",
                },
                "after": {},
                "after_unknown": {},
            },
        },
        {
            "type": "aws_db_parameter_group",
            "change": {
                "actions": ["delete"],
                "before": {
                    "id": "test-rds-pg15",
                    "name": "test-rds-pg15",
                    "family": "postgres15",
                    "region": "us-east-1",
                },
                "after": {},
                "after_unknown": {},
            },
        },
    ],
)
def test_validate_no_changes_allow_delete_when_blue_green_deployment_enabled(
    change: dict,
) -> None:
    """Test delete is allowed when Blue/Green Deployment is enabled"""
    plan = Plan.model_validate({"resource_changes": [change]})
    validator = RDSPlanValidator(
        plan,
        input_object({
            "data": {
                "blue_green_deployment": {
                    "enabled": True,
                    "switchover": True,
                    "delete": True,
                }
            }
        }),
    )

    errors = validator.validate()

    assert errors == []


def test_validate_no_changes_allow_when_blue_green_deployment_enabled_but_not_delete() -> (
    None
):
    """Test no changes when Blue/Green Deployment is enabled"""
    plan = Plan.model_validate({
        "resource_changes": [
            {
                "type": "aws_db_instance",
                "change": {
                    "actions": ["update"],
                    "before": {
                        "id": "some-id",
                        "name": "test-rds",
                        "engine": "postgres",
                        "engine_version": "15.7",
                        "deletion_protection": True,
                        "region": "us-east-1",
                    },
                    "after": {
                        "id": "test-rds-pg15",
                        "name": "test-rds-pg15",
                        "engine": "postgres",
                        "engine_version": "15.7",
                        "deletion_protection": False,
                    },
                    "after_unknown": {},
                },
            },
        ]
    })
    validator = RDSPlanValidator(
        plan,
        input_object({
            "data": {
                "blue_green_deployment": {
                    "enabled": True,
                    "switchover": True,
                    "delete": False,
                }
            }
        }),
    )

    errors = validator.validate()

    assert errors == []


@pytest.mark.parametrize(
    ("actions", "before", "after"),
    [
        (
            ["update"],
            {
                "id": "test-rds-pg15",
                "name": "test-rds-pg15",
                "family": "postgres15",
                "parameter": [
                    {
                        "apply_method": "pending-reboot",
                        "name": "rds.force_ssl",
                        "value": "1",
                    },
                ],
            },
            {
                "id": "test-rds-pg15",
                "name": "test-rds-pg15",
                "family": "postgres15",
                "parameter": [
                    {
                        "apply_method": "immediate",
                        "name": "rds.force_ssl",
                        "value": "1",
                    },
                ],
            },
        ),
        (
            ["create"],
            None,
            {
                "id": "test-rds-pg15",
                "name": "test-rds-pg15",
                "family": "postgres15",
                "parameter": [
                    {
                        "apply_method": "immediate",
                        "name": "rds.force_ssl",
                        "value": "1",
                    },
                ],
            },
        ),
        (
            ["delete", "create"],
            {
                "id": "test-rds-pg15",
                "name": "test-rds-pg15",
                "family": "postgres15",
                "parameter": [
                    {
                        "apply_method": "immediate",
                        "name": "rds.force_ssl",
                        "value": "1",
                    },
                ],
            },
            {
                "id": "test-rds-pg15",
                "name": "test-rds-pg15",
                "family": "postgres15",
                "parameter": [
                    {
                        "apply_method": "immediate",
                        "name": "rds.force_ssl",
                        "value": "1",
                    },
                ],
            },
        ),
    ],
)
def test_validate_parameter_group_with_apply_method_only_change(
    actions: list[str],
    before: dict[str, Any] | None,
    after: dict[str, Any],
    mock_aws_api: Mock,
) -> None:
    """Test parameter group validation for apply_method only change"""
    # ApplyMethod is pending-reboot in default parameter group
    # but the field is not returned in actual DescribeEngineDefaultParameters response
    mock_aws_api.return_value.get_engine_default_parameters.return_value = {
        "rds.force_ssl": {
            "ParameterName": "rds.force_ssl",
            "ParameterValue": "1",
        }
    }
    mock_aws_api.return_value.get_db_parameter_group.return_value = None
    plan = Plan.model_validate({
        "resource_changes": [
            {
                "type": "aws_db_parameter_group",
                "change": {
                    "actions": actions,
                    "before": before,
                    "after": after,
                    "after_unknown": {},
                },
            },
        ]
    })
    validator = RDSPlanValidator(plan, input_object())

    errors = validator.validate()

    assert errors == [
        (
            "Problematic plan changes for parameter group detected for parameters: rds.force_ssl. "
            "Parameter with only apply_method toggled while value is same as before or default is not allowed, "
            "remove the parameter OR change value OR align apply_method with AWS default pending-reboot, "
            "checkout details at https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/db_parameter_group#problematic-plan-changes"
        )
    ]


@pytest.mark.parametrize(
    ("action", "before", "after"),
    [
        (
            "update",
            {
                "id": "test-rds-pg15",
                "name": "test-rds-pg15",
                "family": "postgres15",
                "parameter": [
                    {
                        "apply_method": "pending-reboot",
                        "name": "rds.logical_replication",
                        "value": "0",
                    },
                ],
            },
            {
                "id": "test-rds-pg15",
                "name": "test-rds-pg15",
                "family": "postgres15",
                "parameter": [
                    {
                        "apply_method": "immediate",
                        "name": "rds.logical_replication",
                        "value": "1",
                    },
                ],
            },
        ),
        (
            "create",
            None,
            {
                "id": "test-rds-pg15",
                "name": "test-rds-pg15",
                "family": "postgres15",
                "parameter": [
                    {
                        "apply_method": "immediate",
                        "name": "rds.logical_replication",
                        "value": "1",
                    },
                ],
            },
        ),
    ],
)
def test_validate_parameter_group_with_immediate_for_static_parameter(
    action: str,
    before: dict[str, Any] | None,
    after: dict[str, Any],
    mock_aws_api: Mock,
) -> None:
    """Test parameter group update validation for apply_only_change"""
    mock_aws_api.return_value.get_engine_default_parameters.return_value = {
        "rds.logical_replication": {
            "ParameterName": "rds.logical_replication",
            "ParameterValue": "0",
            "ApplyType": "static",
        }
    }
    mock_aws_api.return_value.get_db_parameter_group.return_value = None
    plan = Plan.model_validate({
        "resource_changes": [
            {
                "type": "aws_db_parameter_group",
                "change": {
                    "actions": [action],
                    "before": before,
                    "after": after,
                    "after_unknown": {},
                },
            },
        ]
    })
    validator = RDSPlanValidator(plan, input_object())

    errors = validator.validate()

    assert errors == [
        "Cannot use immediate apply method for static parameter, must be set to pending-reboot: rds.logical_replication"
    ]


@pytest.mark.parametrize(
    ("action", "before", "after"),
    [
        (
            "update",
            {
                "id": "test-rds-pg15",
                "name": "test-rds-pg15",
                "family": "postgres15",
                "parameter": [
                    {
                        "apply_method": "pending-reboot",
                        "name": "rds.logical_replication",
                        "value": "0",
                    },
                ],
            },
            {
                "id": "test-rds-pg15",
                "name": "test-rds-pg15",
                "family": "postgres15",
                "parameter": [
                    {
                        "apply_method": "pending-reboot",
                        "name": "typo",
                        "value": "1",
                    },
                ],
            },
        ),
        (
            "create",
            None,
            {
                "id": "test-rds-pg15",
                "name": "test-rds-pg15",
                "family": "postgres15",
                "parameter": [
                    {
                        "apply_method": "pending-reboot",
                        "name": "typo",
                        "value": "1",
                    },
                ],
            },
        ),
    ],
)
def test_validate_parameter_group_with_unknown_parameters(
    action: str,
    before: dict[str, Any] | None,
    after: dict[str, Any],
    mock_aws_api: Mock,
) -> None:
    """Test parameter group update validation for unknown parameters"""
    mock_aws_api.return_value.get_engine_default_parameters.return_value = {
        "rds.logical_replication": {
            "ParameterName": "rds.logical_replication",
            "ParameterValue": "0",
            "ApplyType": "static",
        }
    }
    mock_aws_api.return_value.get_db_parameter_group.return_value = None
    plan = Plan.model_validate({
        "resource_changes": [
            {
                "type": "aws_db_parameter_group",
                "change": {
                    "actions": [action],
                    "before": before,
                    "after": after,
                    "after_unknown": {},
                },
            },
        ]
    })
    validator = RDSPlanValidator(plan, input_object())

    errors = validator.validate()

    assert errors == ["Unknown parameter detected in parameter group: typo"]


def test_validate_parameter_group_deletion() -> None:
    """Test parameter group deletion validation"""
    plan = Plan.model_validate({
        "resource_changes": [
            {
                "type": "aws_db_instance",
                "change": {
                    "actions": ["no-op"],
                    "before": {
                        "engine": "postgres",
                        "engine_version": "15.3",
                        "parameter_group_name": "test-rds-pg15",
                        "region": "us-east-1",
                    },
                    "after": {
                        "engine": "postgres",
                        "engine_version": "15.3",
                        "parameter_group_name": "test-rds-pg15",
                    },
                    "after_unknown": None,
                },
            },
            {
                "type": "aws_db_parameter_group",
                "change": {
                    "actions": ["delete"],
                    "before": {
                        "id": "test-rds-pg15",
                        "name": "test-rds-pg15",
                        "family": "postgres15",
                    },
                    "after": {},
                    "after_unknown": {},
                },
            },
        ]
    })
    validator = RDSPlanValidator(
        plan,
        input_object({
            "data": {
                "parameter_group": None,
            }
        }),
    )

    errors = validator.validate()

    assert errors == [
        (
            "Cannot delete parameter group test-rds-pg15 via unset parameter_group, specify a different parameter group. "
            "If this is the preparation for a blue/green deployment on read replica, then unset parameter_group when source instance has enabled blue_green_deployment."
        )
    ]


def test_validate_parameter_group_name_already_exists(
    mock_aws_api: Mock,
) -> None:
    """Test parameter group name already exists"""
    mock_aws_api.return_value.get_db_parameter_group.return_value = {
        "DBParameterGroupName": "test-rds-pg15",
        "DBParameterGroupFamily": "postgres15",
    }

    plan = Plan.model_validate({
        "resource_changes": [
            {
                "type": "aws_db_parameter_group",
                "change": {
                    "actions": ["create"],
                    "before": None,
                    "after": {
                        "id": "test-rds-pg15",
                        "name": "test-rds-pg15",
                        "family": "postgres15",
                    },
                    "after_unknown": {},
                },
            },
        ]
    })
    validator = RDSPlanValidator(plan, input_object())

    errors = validator.validate()

    assert errors == [
        "Parameter group test-rds-pg15 already exists, use a different name"
    ]


def test_validate_region_change() -> None:
    """Test region change"""
    plan = Plan.model_validate({
        "resource_changes": [
            {
                "type": "aws_db_instance",
                "change": {
                    "after": None,
                    "before": {"region": "us-east-1"},
                    "after_unknown": {},
                },
            }
        ]
    })
    validator = RDSPlanValidator(
        plan,
        input_object({
            "data": {
                "region": "us-east-2",
            }
        }),
    )

    errors = validator.validate()

    assert errors == [
        "Region change detected for RDS instance. Current region: us-east-1, Desired region: us-east-2. RDS instances cannot change regions in-place."
    ]


@pytest.mark.parametrize(
    ("existing_security_groups", "input_security_groups", "expected_errors"),
    [
        # Case: Security Group IDs exist
        (
            ["sgA", "sgB"],
            ["sgA"],
            [],
        ),
        # Case: No Security Group ID given
        (
            ["sgA", "sgB"],
            [],
            [],
        ),
        # Case: Security Group ID does not exist
        (
            ["sgA", "sgB"],
            ["sgC"],
            [
                (
                    "The following VPC Security Group IDs do not exist in the AWS Account: ['sgC']. "
                    "Valid VPC Security Group IDs for the given subnet group name 'db-subnet-group' are ['sgA', 'sgB']. "
                    "Try querying app-interface for other RDS instances for that AWS account and compare their VPC Security Group ID."
                )
            ],
        ),
    ],
)
def test_validate_security_group_ids_exist(
    existing_security_groups: list[str],
    input_security_groups: list[str],
    expected_errors: list[str],
    mock_aws_api: Mock,
    new_instance_plan: dict[str, Any],
) -> None:
    """Test parameter group name already exists"""
    mock_aws_api.return_value.get_security_group_ids_for_db_subnet_group.return_value = set(
        existing_security_groups
    )

    plan = Plan.model_validate(new_instance_plan)
    validator = RDSPlanValidator(
        plan,
        input_object({
            "data": {
                "vpc_security_group_ids": input_security_groups,
            }
        }),
    )

    errors = validator.validate()

    assert errors == expected_errors


def test_validate_security_group_ids_skipped_when_no_db_subnet_group_name(
    mock_aws_api: Mock,
    new_instance_plan: dict[str, Any],
) -> None:
    """Test that VPC security group validation is skipped when db_subnet_group_name is None"""
    plan = Plan.model_validate(new_instance_plan)
    validator = RDSPlanValidator(
        plan,
        input_object({
            "data": {
                "vpc_security_group_ids": ["sgA"],
                "db_subnet_group_name": None,
            }
        }),
    )

    errors = validator.validate()

    assert errors == []
    mock_aws_api.return_value.get_security_group_ids_for_db_subnet_group.assert_not_called()
