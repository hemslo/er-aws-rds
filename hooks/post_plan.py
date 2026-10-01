#!/usr/bin/env python
import logging
import sys
from typing import TYPE_CHECKING

from external_resources_io.input import parse_model, read_input_from_file
from external_resources_io.terraform import (
    Action,
    Change,
    Plan,
    ResourceChange,
    TerraformJsonPlanParser,
)

from er_aws_rds.input import (
    AppInterfaceInput,
    Parameter,
)
from hooks.utils.aws_api import AWSApi
from hooks.utils.envvars import RuntimeEnvVars
from hooks.utils.logger import setup_logging

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from mypy_boto3_rds.type_defs import ParameterOutputTypeDef


class RDSPlanValidator:
    """The plan validator class"""

    def __init__(self, plan: Plan, app_interface_input: AppInterfaceInput) -> None:
        self.plan = plan
        self.input = app_interface_input
        self.aws_api = AWSApi(region_name=app_interface_input.data.region)
        self.errors: list[str] = []

    @property
    def output_deletions(self) -> list[Change]:
        return [
            c
            for c in self.plan.output_changes.values()
            if Action.ActionDelete in c.actions
        ]

    @property
    def output_creations(self) -> list[Change]:
        return [
            c
            for c in self.plan.output_changes.values()
            if Action.ActionCreate in c.actions
        ]

    @staticmethod
    def _filter_by_actions(
        resource_changes: Iterable[ResourceChange],
        actions: set[Action],
    ) -> Iterator[ResourceChange]:
        return (
            c
            for c in resource_changes
            if c.change and actions.intersection(c.change.actions)
        )

    @staticmethod
    def _filter_by_type(
        resource_changes: Iterable[ResourceChange],
        resource_type: str,
    ) -> Iterator[ResourceChange]:
        return (c for c in resource_changes if c.type == resource_type)

    @property
    def resource_updates(self) -> list[ResourceChange]:
        return list(
            self._filter_by_actions(self.plan.resource_changes, {Action.ActionUpdate})
        )

    @property
    def resource_deletions(self) -> list[ResourceChange]:
        return list(
            self._filter_by_actions(self.plan.resource_changes, {Action.ActionDelete})
        )

    @property
    def resource_creations(self) -> list[ResourceChange]:
        return list(
            self._filter_by_actions(self.plan.resource_changes, {Action.ActionCreate})
        )

    @property
    def aws_db_instances(self) -> Iterator[ResourceChange]:
        return self._filter_by_type(self.plan.resource_changes, "aws_db_instance")

    @property
    def aws_db_instance_creations(self) -> list[ResourceChange]:
        return list(
            self._filter_by_actions(self.aws_db_instances, {Action.ActionCreate})
        )

    @property
    def aws_db_instance_updates(self) -> list[ResourceChange]:
        return list(
            self._filter_by_actions(self.aws_db_instances, {Action.ActionUpdate})
        )

    @property
    def aws_db_instance_deletions(self) -> list[ResourceChange]:
        return list(
            self._filter_by_actions(self.aws_db_instances, {Action.ActionDelete})
        )

    @property
    def aws_db_parameter_groups(self) -> Iterator[ResourceChange]:
        return self._filter_by_type(
            self.plan.resource_changes, "aws_db_parameter_group"
        )

    def _validate_version_on_create(self) -> None:
        """Validates the RDS instance desired version (new instance)"""
        for u in self.aws_db_instance_creations:
            if not u.change or not u.change.after:
                continue
            engine = self.input.data.engine
            version = u.change.after["engine_version"]
            if not self.aws_api.is_rds_engine_version_available(
                engine=engine, version=version
            ):
                self.errors.append(f"{engine} version {version} is not available.")

    def _validate_version_upgrade(self) -> None:
        for u in self.aws_db_instance_updates:
            if not u.change or not u.change.before or not u.change.after:
                continue
            current_version = u.change.before["engine_version"]
            desired_version = u.change.after["engine_version"]
            if current_version != desired_version:
                valid_upgrade_targets = self.aws_api.get_rds_valid_upgrade_targets(
                    u.change.before["engine"], current_version
                )
                if desired_version not in valid_upgrade_targets:
                    self.errors.append(
                        "Engine version cannot be updated. "
                        f"Current_version: {current_version}, "
                        f"Desired_version: {desired_version}, "
                        f"Valid update versions: {valid_upgrade_targets.keys()}"
                    )

                # Major version upgrade validation
                if (
                    valid_upgrade_targets[desired_version]["IsMajorVersionUpgrade"]
                    and not self.input.data.allow_major_version_upgrade
                ):
                    self.errors.append(
                        "To enable major version upgrade, allow_major_version_upgrade attribute must be set to True"
                    )

    def _validate_region_change(self) -> None:
        """Validates that RDS instances don't change regions during updates"""
        for db in self.aws_db_instances:
            if not db.change or not db.change.before:
                continue

            after_region = self.input.data.region
            before_region = db.change.before["region"]

            if before_region != after_region:
                self.errors.append(
                    f"Region change detected for RDS instance. "
                    f"Current region: {before_region}, Desired region: {after_region}. "
                    "RDS instances cannot change regions in-place."
                )

    def _validate_password_reset_availability(self) -> None:
        """Reject generated password resets while the RDS instance is unavailable."""
        # Keep non-password recovery updates, such as storage increases, available.
        password_reset_planned = any(
            resource.type == "random_password"
            and resource.change
            and Action.ActionCreate in resource.change.actions
            for resource in self.plan.resource_changes
        )
        if not self.aws_db_instance_updates or not password_reset_planned:
            return

        identifier = self.input.data.identifier
        db_instance = self.aws_api.get_db_instance(identifier)
        if db_instance is None:
            self.errors.append(
                f"Cannot reset password for RDS instance {identifier}: it was not found in AWS. "
                "Refresh the Terraform plan before applying."
            )
            return

        status = db_instance.get("DBInstanceStatus")
        if status != "available":
            status_message = (
                f"AWS reports status '{status}'"
                if status is not None
                else "AWS did not report DBInstanceStatus"
            )
            self.errors.append(
                f"Cannot reset password for RDS instance {identifier}: {status_message}. "
                "Terraform apply was not started. Please wait until AWS reports "
                "the RDS instance as 'available', then retry the reconciliation."
            )

    def _validate_deletion_protection_not_enabled_on_destroy(self) -> None:
        for u in self.aws_db_instance_deletions:
            if not u.change or not u.change.before:
                continue
            if u.change.before.get("deletion_protection", False):
                self.errors.append(
                    "Deletion protection cannot be enabled on destroy. Disable deletion_protection first to remove the instance"
                )

    def _validate_resource_renaming(self) -> None:
        # This validation was used to migrate resources from CDKTF to HCL
        if (
            len(self.resource_deletions) != 0
            and len(self.resource_creations) != 0
            and any([
                (len(self.resource_creations) != len(self.resource_deletions)),
                (len(self.output_creations) != len(self.output_deletions)),
            ])
        ):
            self.errors.append("Deletions and Creations mismatch")

    def _validate_no_changes_when_blue_green_deployment_enabled(self) -> None:
        if (
            self.input.data.blue_green_deployment is None
            or not self.input.data.blue_green_deployment.enabled
            or not self.input.data.blue_green_deployment.delete
        ):
            return
        changed_actions = {
            Action.ActionCreate,
            Action.ActionUpdate,
        }
        resource_changes = list(
            self._filter_by_actions(self.plan.resource_changes, changed_actions)
        )
        if resource_changes:
            self.errors.append(
                "There are pending resource changes after a Blue/Green Deployment. "
                "Check the Terraform plan output."
            )

    @staticmethod
    def _is_apply_method_change_only(
        before_parameter: Parameter,
        after_parameter: Parameter,
    ) -> bool:
        return (
            before_parameter.name == after_parameter.name
            and before_parameter.value == after_parameter.value
            and before_parameter.apply_method != after_parameter.apply_method
        )

    def _validate_parameter_group_change(self, change: Change) -> None:
        if not change.after:
            return

        parameter_group_name = change.after["name"]
        if (
            Action.ActionCreate in change.actions
            and self.aws_api.get_db_parameter_group(parameter_group_name)
        ):
            self.errors.append(
                f"Parameter group {parameter_group_name} already exists, use a different name"
            )

        after_parameter_by_name = {
            parameter["name"]: Parameter.model_validate(parameter)
            for parameter in change.after.get("parameter") or []
        }

        if not after_parameter_by_name:
            return

        default_parameter_by_name = self.aws_api.get_engine_default_parameters(
            change.after["family"],
            list(after_parameter_by_name.keys()),
        )

        for name, parameter in after_parameter_by_name.items():
            self._validate_parameter_in_parameter_group(
                parameter=parameter,
                default_parameter=default_parameter_by_name.get(name),
            )

        before_parameter_by_name = (
            {
                parameter["name"]: Parameter.model_validate(parameter)
                for parameter in change.before.get("parameter") or []
            }
            if change.before and Action.ActionCreate not in change.actions
            else {
                parameter["ParameterName"]: Parameter(
                    name=parameter["ParameterName"],
                    value=parameter.get("ParameterValue", ""),
                    apply_method=parameter.get("ApplyMethod", "pending-reboot"),
                )
                for parameter in default_parameter_by_name.values()
            }
        )

        self._validate_apply_method_change_only(
            before_parameter_by_name, after_parameter_by_name
        )

    def _validate_apply_method_change_only(
        self,
        before_parameter_by_name: dict[str, Parameter],
        after_parameter_by_name: dict[str, Parameter],
    ) -> None:
        common_names = before_parameter_by_name.keys() & after_parameter_by_name.keys()
        apply_method_change_only_parameter_names = [
            name
            for name in common_names
            if self._is_apply_method_change_only(
                before_parameter_by_name[name],
                after_parameter_by_name[name],
            )
        ]
        if apply_method_change_only_parameter_names:
            parameters = ", ".join(apply_method_change_only_parameter_names)
            self.errors.append(
                f"Problematic plan changes for parameter group detected for parameters: {parameters}. "
                "Parameter with only apply_method toggled while value is same as before or default is not allowed, "
                "remove the parameter OR change value OR align apply_method with AWS default pending-reboot, "
                "checkout details at https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/db_parameter_group#problematic-plan-changes"
            )

    def _validate_parameter_in_parameter_group(
        self,
        parameter: Parameter,
        default_parameter: ParameterOutputTypeDef | None,
    ) -> None:
        if default_parameter is None:
            self.errors.append(
                f"Unknown parameter detected in parameter group: {parameter.name}"
            )
            return

        if (
            parameter.apply_method == "immediate"
            and default_parameter.get("ApplyType") == "static"
        ):
            self.errors.append(
                f"Cannot use immediate apply method for static parameter, "
                f"must be set to pending-reboot: {parameter.name}"
            )

    def _validate_parameter_group_changes(self) -> None:
        changed_actions = {
            Action.ActionCreate,
            Action.ActionUpdate,
        }
        for c in self._filter_by_actions(self.aws_db_parameter_groups, changed_actions):
            if c.change:
                self._validate_parameter_group_change(c.change)

    def _validate_parameter_group_deletion(self) -> None:
        delete_parameter_group_names = {
            name
            for c in self._filter_by_actions(
                self.aws_db_parameter_groups,
                {Action.ActionDelete},
            )
            if c.change and c.change.before and (name := c.change.before.get("name"))
        }
        aws_db_instance = next(
            self.aws_db_instances,
            None,
        )
        if (
            aws_db_instance
            and aws_db_instance.change
            and aws_db_instance.change.after
            and (
                parameter_group_name := aws_db_instance.change.after.get(
                    "parameter_group_name"
                )
            )
            and parameter_group_name in delete_parameter_group_names
        ):
            self.errors.append(
                f"Cannot delete parameter group {parameter_group_name} via unset parameter_group, specify a different parameter group. "
                "If this is the preparation for a blue/green deployment on read replica, then unset parameter_group when source instance has enabled blue_green_deployment."
            )

    def _validate_vpc_security_group_ids(self) -> None:
        if (
            not self.input.data.vpc_security_group_ids
            or not self.input.data.db_subnet_group_name
        ):
            return
        # Check if there are any DB instance creations that need validation
        # Note, we dont need to check existing DBs so we can save AWS queries
        if not any(
            c.type == "aws_db_instance"
            and c.change
            and c.change.after
            and Action.ActionCreate in c.change.actions
            for c in self.plan.resource_changes
        ):
            return
        valid_security_group_ids = (
            self.aws_api.get_security_group_ids_for_db_subnet_group(
                db_subnet_group_name=self.input.data.db_subnet_group_name
            )
        )
        if (
            invalid_security_group_ids := set(self.input.data.vpc_security_group_ids)
            - valid_security_group_ids
        ):
            # We convert to sorted list for consistent test output. Overhead is neglegible here.
            self.errors.append(
                f"The following VPC Security Group IDs do not exist in the AWS Account: {sorted(invalid_security_group_ids)}. "
                f"Valid VPC Security Group IDs for the given subnet group name '{self.input.data.db_subnet_group_name}' are {sorted(valid_security_group_ids)}. "
                "Try querying app-interface for other RDS instances for that AWS account and compare their VPC Security Group ID."
            )

    def validate(self) -> list[str]:
        """Validate method, return validation errors"""
        self.errors.clear()
        self._validate_password_reset_availability()
        self._validate_version_on_create()
        self._validate_version_upgrade()
        self._validate_region_change()
        self._validate_deletion_protection_not_enabled_on_destroy()
        self._validate_no_changes_when_blue_green_deployment_enabled()
        self._validate_parameter_group_changes()
        self._validate_parameter_group_deletion()
        self._validate_vpc_security_group_ids()
        return self.errors


if __name__ == "__main__":  # pragma: no cover
    setup_logging()
    logger = logging.getLogger(__name__)

    RuntimeEnvVars.check([RuntimeEnvVars.PLAN_FILE_JSON])
    terraform_plan_json = RuntimeEnvVars.PLAN_FILE_JSON.get() or ""

    app_interface_input: AppInterfaceInput = parse_model(
        AppInterfaceInput,
        read_input_from_file(),
    )

    logger.info("Running RDS terraform plan validation")
    parser = TerraformJsonPlanParser(plan_path=terraform_plan_json)
    validator = RDSPlanValidator(parser.plan, app_interface_input)
    if errors := validator.validate():
        logger.error(errors)
        sys.exit(1)
    else:
        logger.info("Validation ended successfully")
        sys.exit(0)
