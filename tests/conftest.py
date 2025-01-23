import json
from collections.abc import Iterable

from cdktf import Testing

from er_aws_rds.input import AppInterfaceInput, Parameter

Testing.__test__ = False


def input_data(
    parameters: Iterable[Parameter] | None,
    snapshot_identifier: str | None = None,
) -> dict:
    """Returns a parsed JSON input as dict"""
    if not parameters:
        parameters = [
            Parameter(
                name="log_statement", value="none", apply_method="pending-reboot"
            ),
            Parameter(
                name="log_min_duration_statement",
                value="-1",
                apply_method="pending-reboot",
            ),
            Parameter(name="log_min_duration_statement", value=60000),
        ]

    parameters_json_string = json.dumps([
        param.model_dump(by_alias=True) for param in parameters
    ])
    """Returns a JSON input data"""
    return json.loads(
        """{
        "data": {
            "engine": "postgres",
            "engine_version": "14.6",
            "name": "postgres",
            "username": "postgres",
            "instance_class": "db.t3.micro",
            "allocated_storage": 20,
            "auto_minor_version_upgrade": false,
            "skip_final_snapshot": true,
            "backup_retention_period": 7,
            "storage_type": "gp2",
            "multi_az": false,
            "ca_cert_identifier": "rds-ca-rsa2048-g1",
            "publicly_accessible": true,
            "apply_immediately": true,
            "identifier": "test-rds",
            "enhanced_monitoring": true,"""
        f"""
            "snapshot_identifier": {json.dumps(snapshot_identifier)},"""
        """
            "parameter_group": {
                "name": "postgres-14",
                "family": "postgres14",
                "description": "Parameter Group for PostgreSQL 14",
                "parameters": """
        + parameters_json_string
        + """
            },
            "output_resource_name": "test-rds-credentials",
            "ca_cert": {
                "path": "app-interface/global/rds-ca-cert",
                "field": "us-east-1",
                "version": 2,
                "q_format": null
            },
            "output_prefix": "prefixed-test-rds",
            "region": "us-east-1",
            "tags": {
                "app": "external-resources-poc",
                "cluster": "appint-ex-01",
                "environment": "stage",
                "managed_by_integration": "external_resources",
                "namespace": "external-resources-poc"
            },
            "default_tags": [
                {
                    "tags": {
                        "app": "app-sre-infra"
                    }
                }
            ]
        },
        "provision": {
            "provision_provider": "aws",
            "provisioner": "app-int-example-01",
            "provider": "rds",
            "identifier": "test-rds",
            "target_cluster": "appint-ex-01",
            "target_namespace": "external-resources-poc",
            "target_secret_name": "test-rds-credentials",
            "module_provision_data": {
                "tf_state_bucket": "external-resources-terraform-state-dev",
                "tf_state_region": "us-east-1",
                "tf_state_dynamodb_table": "external-resources-terraform-lock",
                "tf_state_key": "aws/app-int-example-01/rds/test-rds/terraform.tfstate"
            }
        }
    }
    """
    )


def input_object(snapshot_identifier: str | None = None) -> AppInterfaceInput:
    """Returns an AppInterfaceInput object"""
    return AppInterfaceInput.model_validate(
        input_data(
            parameters=None,
            snapshot_identifier=snapshot_identifier,
        )
    )
