from typing import Any

from cdktf import Testing

from er_aws_rds.input import AppInterfaceInput

Testing.__test__ = False


def deep_merge(dict1: dict[str, Any], dict2: dict[str, Any]) -> dict[str, Any]:
    """Merge two dictionaries recursively"""
    return dict1.copy() | {
        key: (
            deep_merge(dict1[key], value)
            if key in dict1 and isinstance(dict1[key], dict) and isinstance(value, dict)
            else value
        )
        for key, value in dict2.items()
    }


def input_data(additional_data: dict[str, Any] | None = None) -> dict:
    """Returns a parsed JSON input as dict"""
    data = {
        "data": {
            "engine": "postgres",
            "engine_version": "14.6",
            "name": "postgres",
            "username": "postgres",
            "instance_class": "db.t3.micro",
            "allocated_storage": 20,
            "auto_minor_version_upgrade": False,
            "skip_final_snapshot": True,
            "backup_retention_period": 7,
            "storage_type": "gp2",
            "multi_az": False,
            "ca_cert_identifier": "rds-ca-rsa2048-g1",
            "publicly_accessible": True,
            "apply_immediately": True,
            "identifier": "test-rds",
            "enhanced_monitoring": True,
            "monitoring_interval": 60,
            "parameter_group": {
                "name": "postgres-14",
                "family": "postgres14",
                "description": "Parameter Group for PostgreSQL 14",
                "parameters": [
                    {
                        "name": "log_statement",
                        "value": "none",
                        "apply_method": "pending-reboot",
                    },
                    {
                        "name": "log_min_duration_statement",
                        "value": "-1",
                        "apply_method": "pending-reboot",
                    },
                    {
                        "name": "log_min_duration_statement",
                        "value": "60000",
                        "apply_method": "pending-reboot",
                    },
                ],
            },
            "output_resource_name": "test-rds-credentials",
            "ca_cert": {
                "path": "app-interface/global/rds-ca-cert",
                "field": "us-east-1",
                "version": 2,
                "q_format": None,
            },
            "output_prefix": "prefixed-test-rds",
            "region": "us-east-1",
            "tags": {
                "app": "external-resources-poc",
                "cluster": "appint-ex-01",
                "environment": "stage",
                "managed_by_integration": "external_resources",
                "namespace": "external-resources-poc",
            },
            "default_tags": [{"tags": {"app": "app-sre-infra"}}],
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
                "tf_state_key": "aws/app-int-example-01/rds/test-rds/terraform.tfstate",
            },
        },
    }

    if additional_data:
        data = deep_merge(data, additional_data)
    return data


def input_object(additional_data: dict[str, Any] | None = None) -> AppInterfaceInput:
    """Returns an AppInterfaceInput object"""
    return AppInterfaceInput.model_validate(input_data(additional_data))
