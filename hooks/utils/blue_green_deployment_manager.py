import logging
from functools import cached_property
from typing import TYPE_CHECKING, Any, Literal

from hooks.utils.blue_green_deployment_model import (
    POSTGRES_LOGICAL_REPLICATION_PARAMETER_NAME,
    TERMINAL_FAILURE_STATES,
    TERMINAL_FAILURE_STATUS_STATES,
    BlueGreenDeploymentModel,
)
from hooks.utils.models import (
    ActionType,
    BaseAction,
    CreateAction,
    DeleteAction,
    DeleteSourceDBInstanceAction,
    DeleteWithoutSwitchoverAction,
    NoOpAction,
    State,
    SwitchoverAction,
    WaitForAvailableAction,
    WaitForDeletedAction,
    WaitForSourceDBInstancesDeletedAction,
    WaitForSwitchoverCompletedAction,
)
from hooks.utils.wait import wait_for

if TYPE_CHECKING:
    from collections.abc import Callable

    from mypy_boto3_rds.type_defs import (
        BlueGreenDeploymentTypeDef,
        DBInstanceTypeDef,
        ParameterOutputTypeDef,
    )

    from er_aws_rds.input import (
        AppInterfaceInput,
        Rds,
    )
    from hooks.utils.aws_api import AWSApi

AWS_DEFAULT_SWITCHOVER_TIMEOUT = 300


class BlueGreenDeploymentManager:
    """Blue/Green Deployment Manager"""

    def __init__(
        self,
        aws_api: AWSApi,
        app_interface_input: AppInterfaceInput,
        *,
        dry_run: bool,
    ) -> None:
        """Init"""
        self.aws_api = aws_api
        self.app_interface_input = app_interface_input
        self.dry_run = dry_run
        self.logger = logging.getLogger(__name__)
        self.model: BlueGreenDeploymentModel | None = None
        self._switchover_in_progress_observed = False

    @property
    def blue_green_deployment_name(self) -> str:
        """Get the Blue/Green Deployment name"""
        return self.app_interface_input.data.identifier

    def run(self) -> State:
        """Run Blue/Green Deployment Manager"""
        input_data = self.app_interface_input.data
        if (
            (replica_source := input_data.replica_source)
            and replica_source.blue_green_deployment
            and replica_source.blue_green_deployment.enabled
        ):
            self.logger.info("blue_green_deployment in replica_source enabled.")
            return State.REPLICA_SOURCE_ENABLED

        if (
            input_data.blue_green_deployment is None
            or not input_data.blue_green_deployment.enabled
        ):
            self.logger.info("blue_green_deployment not enabled.")
            return State.NOT_ENABLED

        self.model = self._build_model(input_data)
        self._switchover_in_progress_observed = (
            self.model.state == State.SWITCHOVER_IN_PROGRESS
        )
        self._raise_for_unhandled_terminal_failure()

        actions = self.model.plan_actions()
        if all(action.type == ActionType.NO_OP for action in actions):
            self.logger.info("No changes for Blue/Green Deployment.")
            for action in actions:
                self.model.state = action.next_state
            return self.model.state

        if pending_prepares := self.model.pending_prepares:
            self.logger.info(f"Pending prepares needed: {', '.join(pending_prepares)}")
            if self.dry_run:
                for action in actions:
                    self.logger.info(
                        f"Action {action.type}: {action.model_dump_json()}"
                    )
            return State.PENDING_PREPARE

        return self._run_actions(actions)

    def _run_actions(self, actions: list[BaseAction]) -> State:
        assert self.model
        for action in actions:
            self.logger.info(f"Action {action.type}: {action.model_dump_json()}")
            if self.dry_run:
                continue
            handler = self._action_handlers[action.type]
            previous_state = self.model.state
            handler(action)
            if self.model.state != previous_state:
                self._raise_for_unhandled_terminal_failure()
                return self._run_actions(self.model.plan_actions())
            self.model.state = action.next_state
        return self.model.state

    def _build_model(self, input_data: Rds) -> BlueGreenDeploymentModel:
        assert input_data.blue_green_deployment
        blue_green_deployment = self.aws_api.get_blue_green_deployment(
            self.blue_green_deployment_name
        )
        if blue_green_deployment and blue_green_deployment["Status"] in {
            "INVALID_CONFIGURATION",
            "SWITCHOVER_FAILED",
        }:
            return BlueGreenDeploymentModel(
                state=State.INIT,
                input_data=input_data,
                blue_green_deployment=blue_green_deployment,
            )

        db_instance = self.aws_api.get_db_instance(input_data.identifier)
        valid_upgrade_targets = (
            self.aws_api.get_blue_green_deployment_valid_upgrade_targets(
                engine=db_instance["Engine"],
                version=db_instance["EngineVersion"],
            )
            if db_instance
            else {}
        )
        target_parameter_group_name = (
            input_data.blue_green_deployment.target.parameter_group.name
            if input_data.blue_green_deployment.target
            and input_data.blue_green_deployment.target.parameter_group
            else None
        )
        target_db_parameter_group = (
            self.aws_api.get_db_parameter_group(target_parameter_group_name)
            if target_parameter_group_name
            else None
        )
        source_db_instances = self._fetch_source_db_instances(blue_green_deployment)
        target_db_instances = self._fetch_target_db_instances(blue_green_deployment)
        source_db_parameters = self._fetch_source_db_parameters(db_instance)
        return BlueGreenDeploymentModel(
            state=State.INIT,
            input_data=input_data,
            db_instance=db_instance,
            valid_upgrade_targets=valid_upgrade_targets,
            target_db_parameter_group=target_db_parameter_group,
            blue_green_deployment=blue_green_deployment,
            source_db_instances=source_db_instances,
            target_db_instances=target_db_instances,
            source_db_parameters=source_db_parameters,
        )

    def _fetch_source_db_parameters(
        self,
        db_instance: DBInstanceTypeDef | None,
    ) -> dict[str, ParameterOutputTypeDef]:
        if db_instance is None or db_instance["Engine"] != "postgres":
            return {}
        in_sync_parameter_group = next(
            (
                pg
                for pg in db_instance["DBParameterGroups"] or []
                if pg.get("ParameterApplyStatus") == "in-sync"
            ),
            None,
        )
        if in_sync_parameter_group is None:
            return {}
        return self.aws_api.get_db_parameters(
            parameter_group_name=in_sync_parameter_group["DBParameterGroupName"],
            parameter_names=[POSTGRES_LOGICAL_REPLICATION_PARAMETER_NAME],
        )

    def _fetch_blue_green_deployment_member_instances(
        self,
        blue_green_deployment: BlueGreenDeploymentTypeDef | None,
        key: Literal["SourceMember", "TargetMember"],
    ) -> list[DBInstanceTypeDef]:
        if blue_green_deployment is None:
            return []
        return list(
            filter(
                None,
                (
                    self.aws_api.get_db_instance(identifier)
                    for details in blue_green_deployment.get("SwitchoverDetails", [])
                    if (identifier := details.get(key))
                ),
            )
        )

    def _fetch_source_db_instances(
        self,
        blue_green_deployment: BlueGreenDeploymentTypeDef | None,
    ) -> list[DBInstanceTypeDef]:
        return self._fetch_blue_green_deployment_member_instances(
            blue_green_deployment, "SourceMember"
        )

    def _fetch_target_db_instances(
        self,
        blue_green_deployment: BlueGreenDeploymentTypeDef | None,
    ) -> list[DBInstanceTypeDef]:
        return self._fetch_blue_green_deployment_member_instances(
            blue_green_deployment, "TargetMember"
        )

    @cached_property
    def _action_handlers(self) -> dict[ActionType, Callable[[Any], None]]:
        return {
            ActionType.CREATE: self._handle_create,
            ActionType.WAIT_FOR_AVAILABLE: self._handle_wait_for_available,
            ActionType.SWITCHOVER: self._handle_switchover,
            ActionType.WAIT_FOR_SWITCHOVER_COMPLETED: self._handle_wait_for_switchover_completed,
            ActionType.DELETE_SOURCE_DB_INSTANCE: self._handle_delete_source_db_instance,
            ActionType.WAIT_FOR_SOURCE_DB_INSTANCES_DELETED: self._handle_wait_for_source_db_instances_deleted,
            ActionType.DELETE: self._handle_delete,
            ActionType.DELETE_WITHOUT_SWITCHOVER: self._handle_delete_without_switchover,
            ActionType.WAIT_FOR_DELETED: self._handle_wait_for_delete,
            ActionType.NO_OP: self._handle_no_op,
        }

    def _handle_create(self, action: CreateAction) -> None:
        self.aws_api.create_blue_green_deployment(action.payload)

    def _wait_for_available_condition(self) -> bool:
        assert self.model
        self.model.blue_green_deployment = self.aws_api.get_blue_green_deployment(
            self.blue_green_deployment_name
        )
        if self.model.blue_green_deployment is None:
            return False
        status = self.model.blue_green_deployment["Status"]
        if status in TERMINAL_FAILURE_STATUS_STATES:
            self.model.state = TERMINAL_FAILURE_STATUS_STATES[status]
            return True
        self.model.target_db_instances = self._fetch_target_db_instances(
            self.model.blue_green_deployment
        )
        return self.model.is_blue_green_deployment_available()

    def _handle_wait_for_available(self, _: WaitForAvailableAction) -> None:
        wait_for(self._wait_for_available_condition, logger=self.logger)
        assert self.model
        if self.model.state in TERMINAL_FAILURE_STATES:
            return
        endpoints = [
            endpoint
            for instance in self.model.target_db_instances
            if (endpoint := instance.get("Endpoint"))
        ]
        self.logger.info(f"Target DB instances endpoints: {endpoints}")

    def _handle_switchover(self, _: SwitchoverAction) -> None:
        assert self.model
        assert self.model.blue_green_deployment
        identifier = self.model.blue_green_deployment["BlueGreenDeploymentIdentifier"]
        self.aws_api.switchover_blue_green_deployment(
            identifier,
            timeout=self.model.config.switchover_timeout,
        )

    def _wait_for_switchover_completed_condition(self) -> bool:
        assert self.model
        self.model.blue_green_deployment = self.aws_api.get_blue_green_deployment(
            self.blue_green_deployment_name
        )
        deployment = self.model.blue_green_deployment
        if deployment is None:
            return False
        status = deployment["Status"]
        if status == "SWITCHOVER_IN_PROGRESS":
            self._switchover_in_progress_observed = True
        elif status == "SWITCHOVER_FAILED":
            raise self._switchover_failed_error(deployment)
        elif status == "AVAILABLE" and self._switchover_in_progress_observed:
            raise self._switchover_cancelled_error(deployment)
        return status == "SWITCHOVER_COMPLETED"

    def _handle_wait_for_switchover_completed(
        self, _: WaitForSwitchoverCompletedAction
    ) -> None:
        assert self.model
        timeout = self.model.config.switchover_timeout
        timeout_seconds = (
            timeout if timeout is not None else AWS_DEFAULT_SWITCHOVER_TIMEOUT
        )
        try:
            wait_for(
                self._wait_for_switchover_completed_condition,
                logger=self.logger,
                timeout=timeout_seconds,
            )
        except TimeoutError as error:
            deployment = self.model.blue_green_deployment
            identifier = (
                deployment.get("BlueGreenDeploymentIdentifier")
                or self.blue_green_deployment_name
                if deployment
                else self.blue_green_deployment_name
            )
            status = deployment.get("Status", "unknown") if deployment else "unknown"
            details = self._status_details_suffix(deployment) if deployment else ""
            raise TimeoutError(
                f"Blue/Green deployment {identifier} did not complete switchover "
                f"within {timeout_seconds} seconds; last observed status {status}"
                f"{details}. Set blue_green_deployment.switchover: false while "
                "replication catches up, then set it to true in a later run to "
                "start a new attempt."
            ) from error

    def _handle_delete_source_db_instance(
        self, _: DeleteSourceDBInstanceAction
    ) -> None:
        assert self.model
        self.model.source_db_instances = self._fetch_source_db_instances(
            self.model.blue_green_deployment
        )
        for instance in self.model.source_db_instances:
            self.aws_api.delete_db_instance(instance["DBInstanceIdentifier"])

    def _wait_for_source_db_instances_deleted_condition(self) -> bool:
        assert self.model
        self.model.source_db_instances = self._fetch_source_db_instances(
            self.model.blue_green_deployment
        )
        return len(self.model.source_db_instances) == 0

    def _handle_wait_for_source_db_instances_deleted(
        self, _: WaitForSourceDBInstancesDeletedAction
    ) -> None:
        wait_for(
            self._wait_for_source_db_instances_deleted_condition, logger=self.logger
        )

    def _handle_delete(self, _: DeleteAction) -> None:
        assert self.model
        assert self.model.blue_green_deployment
        identifier = self.model.blue_green_deployment["BlueGreenDeploymentIdentifier"]
        self.aws_api.delete_blue_green_deployment(identifier)

    def _handle_delete_without_switchover(
        self, _: DeleteWithoutSwitchoverAction
    ) -> None:
        assert self.model
        assert self.model.blue_green_deployment
        identifier = self.model.blue_green_deployment["BlueGreenDeploymentIdentifier"]
        self.aws_api.delete_blue_green_deployment(identifier, delete_target=True)

    def _wait_for_delete_condition_condition(self) -> bool:
        assert self.model
        self.model.blue_green_deployment = self.aws_api.get_blue_green_deployment(
            self.blue_green_deployment_name
        )
        return self.model.blue_green_deployment is None

    def _handle_wait_for_delete(self, _: WaitForDeletedAction) -> None:
        wait_for(self._wait_for_delete_condition_condition, logger=self.logger)

    @staticmethod
    def _handle_no_op(_: NoOpAction) -> None:
        return

    def _raise_for_unhandled_terminal_failure(self) -> None:
        assert self.model
        if self.model.state not in TERMINAL_FAILURE_STATES:
            return
        assert self.model.blue_green_deployment
        if self.model.state == State.INVALID_CONFIGURATION:
            if self.model.config.delete:
                return
            raise self._invalid_configuration_error(self.model.blue_green_deployment)
        raise self._switchover_failed_error(self.model.blue_green_deployment)

    def _invalid_configuration_error(
        self, deployment: BlueGreenDeploymentTypeDef
    ) -> RuntimeError:
        identifier = (
            deployment.get("BlueGreenDeploymentIdentifier")
            or self.blue_green_deployment_name
        )
        details = self._status_details_suffix(deployment)
        return RuntimeError(
            f"Blue/Green deployment {identifier} has terminal status "
            f"INVALID_CONFIGURATION{details}. Set blue_green_deployment.delete: "
            "true to request cleanup."
        )

    def _switchover_failed_error(
        self, deployment: BlueGreenDeploymentTypeDef
    ) -> RuntimeError:
        identifier = (
            deployment.get("BlueGreenDeploymentIdentifier")
            or self.blue_green_deployment_name
        )
        details = self._status_details_suffix(deployment)
        return RuntimeError(
            f"Blue/Green deployment {identifier} failed with status "
            f"SWITCHOVER_FAILED{details}. Set blue_green_deployment.switchover: "
            "false while replication catches up, then set it to true in a later "
            "run to start a new attempt."
        )

    def _switchover_cancelled_error(
        self, deployment: BlueGreenDeploymentTypeDef
    ) -> RuntimeError:
        identifier = (
            deployment.get("BlueGreenDeploymentIdentifier")
            or self.blue_green_deployment_name
        )
        details = self._status_details_suffix(deployment)
        return RuntimeError(
            f"Blue/Green deployment {identifier} returned to status AVAILABLE "
            f"after SWITCHOVER_IN_PROGRESS; the switchover was cancelled or rolled "
            f"back{details}. Set blue_green_deployment.switchover: false while "
            "replication catches up, then set it to true in a later run to start "
            "a new attempt."
        )

    @staticmethod
    def _status_details_suffix(deployment: BlueGreenDeploymentTypeDef) -> str:
        details = deployment.get("StatusDetails")
        return f"; StatusDetails: {details}" if details else ""
