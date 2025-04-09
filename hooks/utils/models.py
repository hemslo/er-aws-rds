from abc import ABC
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, field_serializer


class CreateBlueGreenDeploymentParams(BaseModel):
    """CreateBlueGreenDeploymentParams"""

    name: str = Field(serialization_alias="BlueGreenDeploymentName")
    source_arn: str = Field(serialization_alias="Source")
    allocated_storage: int | None = Field(
        serialization_alias="TargetAllocatedStorage", default=None
    )
    engine_version: str | None = Field(
        serialization_alias="TargetEngineVersion", default=None
    )
    instance_class: str | None = Field(
        serialization_alias="TargetDBInstanceClass", default=None
    )
    iops: int | None = Field(serialization_alias="TargetIops", default=None)
    parameter_group_name: str | None = Field(
        serialization_alias="TargetDBParameterGroupName", default=None
    )
    storage_throughput: int | None = Field(
        serialization_alias="TargetStorageThroughput", default=None
    )
    storage_type: str | None = Field(
        serialization_alias="TargetStorageType", default=None
    )
    tags: dict[str, str] | None = Field(serialization_alias="Tags", default=None)

    @field_serializer("tags")
    def serialize_tags(  # noqa: PLR6301
        self,
        tags: dict[str, str] | None,
    ) -> list[dict[str, str]] | None:
        """Serialize tags as AWS API format"""
        if tags is None:
            return None
        return [{"Key": k, "Value": v} for k, v in tags.items()]


class State(StrEnum):
    """State Enum"""

    INIT = "init"
    REPLICA_SOURCE_ENABLED = "replica_source_enabled"
    NOT_ENABLED = "not_enabled"
    PROVISIONING = "provisioning"
    AVAILABLE = "available"
    SWITCHOVER_IN_PROGRESS = "switchover_in_progress"
    SWITCHOVER_COMPLETED = "switchover_completed"
    DELETING_SOURCE_DB_INSTANCES = "deleting_source_db_instances"
    SOURCE_DB_INSTANCES_DELETED = "source_db_instances_deleted"
    DELETING = "deleting"
    NO_OP = "no_op"
    PENDING_PREPARE = "pending_prepare"


class PendingPrepare(StrEnum):
    """Pending Prepare Enum"""

    TARGET_PARAMETER_GROUP = "target_parameter_group"
    DELETION_PROTECTION = "deletion_protection"
    BACKUP_RETENTION_PERIOD = "backup_retention_period"


class ActionType(StrEnum):
    """Action Enum"""

    NO_OP = "no_op"
    CREATE = "create"
    WAIT_FOR_AVAILABLE = "wait_for_available"
    SWITCHOVER = "switchover"
    WAIT_FOR_SWITCHOVER_COMPLETED = "wait_for_switchover_completed"
    DELETE_SOURCE_DB_INSTANCE = "delete_source_db_instance"
    WAIT_FOR_SOURCE_DB_INSTANCES_DELETED = "wait_for_source_db_instances_deleted"
    DELETE_WITHOUT_SWITCHOVER = "delete_without_switchover"
    DELETE = "delete"
    WAIT_FOR_DELETED = "wait_for_deleted"


class BaseAction(BaseModel, ABC):
    """Base Action"""

    type: ActionType
    next_state: State


class NoOpAction(BaseAction):
    """No Operation Action, just for State Transition"""

    type: Literal[ActionType.NO_OP] = ActionType.NO_OP


class CreateAction(BaseAction):
    """Create Action"""

    type: Literal[ActionType.CREATE] = ActionType.CREATE
    payload: CreateBlueGreenDeploymentParams


class WaitForAvailableAction(BaseAction):
    """Wait For Available Action"""

    type: Literal[ActionType.WAIT_FOR_AVAILABLE] = ActionType.WAIT_FOR_AVAILABLE


class SwitchoverAction(BaseAction):
    """Switchover Action"""

    type: Literal[ActionType.SWITCHOVER] = ActionType.SWITCHOVER


class WaitForSwitchoverCompletedAction(BaseAction):
    """Wait For Switchover Completed Action"""

    type: Literal[ActionType.WAIT_FOR_SWITCHOVER_COMPLETED] = (
        ActionType.WAIT_FOR_SWITCHOVER_COMPLETED
    )


class DeleteSourceDBInstanceAction(BaseAction):
    """Delete Source DB Instance Action"""

    type: Literal[ActionType.DELETE_SOURCE_DB_INSTANCE] = (
        ActionType.DELETE_SOURCE_DB_INSTANCE
    )


class WaitForSourceDBInstancesDeletedAction(BaseAction):
    """Wait For Source DB Instances Deleted Action"""

    type: Literal[ActionType.WAIT_FOR_SOURCE_DB_INSTANCES_DELETED] = (
        ActionType.WAIT_FOR_SOURCE_DB_INSTANCES_DELETED
    )


class DeleteAction(BaseAction):
    """Delete Action"""

    type: Literal[ActionType.DELETE] = ActionType.DELETE


class DeleteWithoutSwitchoverAction(BaseAction):
    """Delete Without Switchover Action"""

    type: Literal[ActionType.DELETE_WITHOUT_SWITCHOVER] = (
        ActionType.DELETE_WITHOUT_SWITCHOVER
    )


class WaitForDeletedAction(BaseAction):
    """Wait For Delete Action"""

    type: Literal[ActionType.WAIT_FOR_DELETED] = ActionType.WAIT_FOR_DELETED
