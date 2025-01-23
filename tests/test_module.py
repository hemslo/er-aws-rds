import json

import pytest
from cdktf import Testing
from cdktf_cdktf_provider_aws.db_instance import DbInstance
from cdktf_cdktf_provider_aws.db_parameter_group import DbParameterGroup
from cdktf_cdktf_provider_aws.iam_role import IamRole
from cdktf_cdktf_provider_aws.iam_role_policy_attachment import IamRolePolicyAttachment

from er_aws_rds.input import VaultSecret
from er_aws_rds.rds import Stack

from .conftest import input_object


def build_synth(snapshot_identifier: str | None = None) -> str:
    """Create Synth"""
    stack = Stack(
        Testing.app(),
        "CDKTF",
        input_object(snapshot_identifier=snapshot_identifier),
    )
    return Testing.synth(stack)


@pytest.fixture
def synth() -> str:
    """Synth fixture"""
    return build_synth()


def test_should_contain_rds_instance(synth: str) -> None:
    """Test should_contain_rds_instance"""
    assert Testing.to_have_resource_with_properties(
        synth,
        DbInstance.TF_RESOURCE_TYPE,
        {
            "identifier": "test-rds",
            "engine": "postgres",
            "db_name": "postgres",
            "allocated_storage": 20,
            "parameter_group_name": "test-rds-postgres-14",
            "tags": {
                "app": "external-resources-poc",
                "cluster": "appint-ex-01",
                "environment": "stage",
                "managed_by_integration": "external_resources",
                "namespace": "external-resources-poc",
            },
        },
    )


def test_should_contain_parameter_group(synth: str) -> None:
    """Test should_contain_parameter_group"""
    assert Testing.to_have_resource_with_properties(
        synth,
        DbParameterGroup.TF_RESOURCE_TYPE,
        {
            "name": "test-rds-postgres-14",
            "family": "postgres14",
        },
        # Test fails if I add the parameters. It works for 1 parameter
        # but fails if I set the full list
    )


def test_enhanced_monitoring(synth: str) -> None:
    """Test enhanced monitoring"""
    assert Testing.to_have_resource_with_properties(
        synth,
        IamRole.TF_RESOURCE_TYPE,
        {
            "name": "test-rds-enhanced-monitoring",
            "assume_role_policy": '{"Version": "2012-10-17", "Statement": [{"Action": "sts:AssumeRole", "Principal": {"Service": "monitoring.rds.amazonaws.com"}, "Effect": "Allow"}]}',
        },
    )
    assert Testing.to_have_resource_with_properties(
        synth,
        IamRolePolicyAttachment.TF_RESOURCE_TYPE,
        {
            "role": "${aws_iam_role.test-rds-enhanced-monitoring.name}",
            "policy_arn": "arn:aws:iam::aws:policy/service-role/AmazonRDSEnhancedMonitoringRole",
        },
    )


@pytest.mark.parametrize("snapshot_identifier", [None, "some-identifier"])
def test_outputs(snapshot_identifier: str | None) -> None:
    """Test outputs"""
    synth = build_synth(snapshot_identifier)
    result = json.loads(synth)
    ca_cert = VaultSecret(
        path="app-interface/global/rds-ca-cert",
        field="us-east-1",
        version=2,
        q_format=None,
    )
    expected_outputs = {
        "test-rds__db_ca_cert": {
            "sensitive": False,
            "value": f"__vault__:{ca_cert.model_dump_json()}",
        },
        "test-rds__db_host": {
            "value": "${aws_db_instance.test-rds.address}",
        },
        "test-rds__db_name": {
            "value": "${aws_db_instance.test-rds.db_name}",
        },
        "test-rds__db_port": {
            "value": "${aws_db_instance.test-rds.port}",
        },
        "test-rds__db_user": {
            "sensitive": True,
            "value": "${aws_db_instance.test-rds.username}",
        },
        "test-rds__db_password": {
            "sensitive": True,
            "value": "${aws_db_instance.test-rds.password}",
        },
    }
    assert result["output"] == expected_outputs
