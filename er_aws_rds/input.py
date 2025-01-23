from collections.abc import Sequence
from typing import Any, Literal

from external_resources_io.input import AppInterfaceProvision
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    field_validator,
    model_validator,
)

from er_aws_rds.errors import RDSLogicalReplicationError

ENHANCED_MONITORING_ROLE_NAME_MAX_LENGTH = 64


class EventNotification(BaseModel):
    "db_event_subscription for SNS"

    destination: str = Field(..., alias="destination")
    source_type: str | None = Field(default="all", alias="source_type")
    event_categories: list[str] | None = Field(..., alias="event_categories")


class DataClassification(BaseModel):
    """DataClassification check. NOT Implemented"""

    loss_impact: str | None = Field(..., alias="loss_impact")


class VaultSecret(BaseModel):
    """VaultSecret spec"""

    path: str
    field: str
    version: int | None = 1
    q_format: str | None = Field(default=None)

    def to_vault_ref(self) -> str:
        """Generates a JSON vault ref"""
        json = self.model_dump_json()
        return "__vault__:" + json


class Parameter(BaseModel):
    """db_parameter_group_parameter"""

    name: str
    value: Any
    apply_method: Literal["immediate", "pending-reboot"] | None = Field(default=None)

    @field_validator("value", mode="before")
    @classmethod
    def transform(cls, v: Any) -> str:  # noqa: ANN401
        """values come as int|str|float|bool from App-Interface, but terraform only allows str"""
        return str(v)


class ParameterGroup(BaseModel):
    "db_parameter_group"

    family: str
    name: str | None = None
    description: str | None = None
    parameters: list[Parameter] | None = Field(default=None, exclude=True)

    # This attribute is set by a model_validator in the RDS class
    computed_pg_name: str = Field(default="", exclude=True)

    # This was used to populate DbParameterGroup(self, **pg.model_dump()) directy
    # but it did not work. "parameters" come from App-Interface but terraform needs "parameter" (singular)
    # @computed_field
    # def parameter(self) -> list[Parameter] | None:
    #     if self.parameters:
    #         return self.parameters
    #     return None

    # @computed_field
    # def id_(self) -> str:
    #     return self.name or ""


class ReplicaSource(BaseModel):
    "AppInterface ReplicaSource"

    region: str
    identifier: str


class RdsAppInterface(BaseModel):
    """AppInterface Input parameters

    Class with Input parameters from App-Interface that are not part of the
    Terraform aws_db_instance object.
    """

    # Name is deprecated. db_name is included as a computed_field
    name: str | None = Field(
        max_length=63, pattern=r"^[a-zA-Z][a-zA-Z0-9_]+$", exclude=True, default=None
    )
    aws_partition: str | None = Field(default="aws", exclude=True)
    region: str = Field(exclude=True)
    parameter_group: ParameterGroup | None = Field(default=None, exclude=True)
    old_parameter_group: ParameterGroup | None = Field(default=None, exclude=True)
    replica_source: ReplicaSource | None = Field(default=None, exclude=True)
    enhanced_monitoring: bool | None = Field(default=None, exclude=True)
    reset_password: str | None = Field(default=None, exclude=True)
    ca_cert: VaultSecret | None = Field(default=None, exclude=True)
    annotations: str | None = Field(default=None, exclude=True)
    event_notifications: list[EventNotification] | None = Field(
        default=None, exclude=True
    )
    data_classification: DataClassification | None = Field(default=None, exclude=True)
    output_resource_db_name: str | None = Field(default=None, exclude=True)
    # Output_resource_name is redundant
    output_resource_name: str | None = Field(default=None, exclude=True)
    output_prefix: str = Field(exclude=True)
    default_tags: Sequence[dict[str, Any]] = Field(default=None, exclude=True)


class Rds(RdsAppInterface):
    """RDS Input parameters

    Input parameters from App-Interface that are part
    of the Terraform aws_db_instance object. Generally speaking, these
    parameters come from the rds defaults attributes.

    The class only defines the parameters that are changed or tweaked in the module, other
    attributes are included as extra_attributes.
    """

    model_config = ConfigDict(extra="allow")
    identifier: str
    engine: str | None = None
    allow_major_version_upgrade: bool | None = False
    availability_zone: str | None = None
    monitoring_interval: int | None = 0
    monitoring_role_arn: str | None = None
    apply_immediately: bool | None = False
    multi_az: bool | None = False
    replicate_source_db: str | None = None
    snapshot_identifier: str | None = None
    backup_retention_period: int | None = None
    db_subnet_group_name: str | None = None
    storage_encrypted: bool | None = None
    kms_key_id: str | None = None
    username: str | None = None
    # _password is not in the input, the field is used to populate the random password
    password: str | None = None
    parameter_group_name: str | None = None
    tags: dict[str, Any]

    @property
    def enhanced_monitoring_role_name(self) -> str:
        """Id/Name for enhanced monitoring role"""
        base_name = self.identifier + "-enhanced-monitoring"
        return (
            base_name
            if len(base_name) <= ENHANCED_MONITORING_ROLE_NAME_MAX_LENGTH
            else self.identifier[:61].rstrip("-") + "-em"
        )

    @computed_field
    def id_(self) -> str:
        """id_"""
        return self.identifier

    @computed_field
    def db_name(self) -> str | None:
        """db_name"""
        return self.name

    @model_validator(mode="after")
    def az_belongs_to_region(self) -> "Rds":
        """Check if a the AZ belongs to a region"""
        if self.availability_zone:
            az_region = self.availability_zone[:-1]
            if self.region != az_region:
                msg = "Availability_zone does not belong to the region"
                raise ValueError(
                    msg,
                    self.availability_zone,
                    self.region,
                )
        return self

    @model_validator(mode="after")
    def unset_az_if_multi_region(self) -> "Rds":
        """Remove az for multi_region instances"""
        if self.multi_az:
            self.availability_zone = None
        return self

    @model_validator(mode="after")
    def unset_replica_or_snapshot_not_allowed_attrs(self) -> "Rds":
        """Some attributes are not allowed if the instance is a replica or needs to be created from a snapshot"""
        if self.replica_source or self.replicate_source_db or self.snapshot_identifier:
            self.username = None
            self.password = None
            self.name = None
            self.engine = None
            self.allocated_storage = None
        return self

    @model_validator(mode="after")
    def replication(self) -> "Rds":
        """replica_source and replicate_source_db are mutually excluive"""
        if self.replica_source and self.replicate_source_db:
            msg = "Only one of replicate_source_db or replica_source can be defined"
            raise ValueError(msg)
        if self.replica_source and self.replica_source.region != self.region:
            # CROSS-REGION Replication
            if not self.db_subnet_group_name:
                msg = "db_subnet_group_name must be defined for cross-region replicas"
                raise ValueError(msg)
            if self.storage_encrypted and not self.kms_key_id:
                msg = "storage_encrypted ignored for cross-region read replica. Set kms_key_id"
                raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def validate_parameter_group_parameters(self) -> "Rds":
        """Validate that every parameter complies with our requirements"""
        if not self.parameter_group:
            return self
        for parameter in self.parameter_group.parameters or []:
            if (
                parameter.name == "rds.logical_replication"
                and parameter.apply_method != "pending-reboot"
            ):
                msg = "rds.logical_replication must be set to pending-reboot"
                raise RDSLogicalReplicationError(msg)
        return self

    @model_validator(mode="after")
    def parameter_groups(self) -> "Rds":
        "Sets the right parameter group names. The instance identifier is used as prefix on each pg"
        "This way each instance will have its own parameter group, withouth re-using them on multiple instances"
        if self.parameter_group:
            self.parameter_group.computed_pg_name = (
                f"{self.identifier}-{self.parameter_group.name or 'pg'}"
            )

        if self.old_parameter_group and not self.parameter_group:
            msg = "old_parameter_group must be used with parameter_group. old_parameter_group is only used for RDS major version upgrades"
            raise ValueError(msg)

        if self.old_parameter_group and self.parameter_group:
            self.old_parameter_group.computed_pg_name = (
                f"{self.identifier}-{self.old_parameter_group.name or 'pg'}"
            )

            if (
                self.old_parameter_group.computed_pg_name
                == self.parameter_group.computed_pg_name
            ):
                msg = "Parameter group and old parameter group have the same name. Assign a name to the new parameter group"
                raise ValueError(msg)

        return self

    @property
    def is_read_replica(self) -> bool:
        """Returns true if the instance is a read replica"""
        return self.replica_source is not None or self.replicate_source_db is not None

    @model_validator(mode="after")
    def enhanced_monitoring_attributes_require_enhanced_monitoring(self) -> "Rds":
        """If monitoring_interval is set, enhanced_monitoring must be enabled"""
        if not self.enhanced_monitoring and (
            self.monitoring_interval != 0 or self.monitoring_role_arn
        ):
            raise ValueError(
                "Enhanced monitoring attributes requires enhanced_monitoring to be true"
            )
        return self

    @model_validator(mode="after")
    def monitoring_role_arn_requires_monitoring_interval(self) -> "Rds":
        """If monitoring_role_arn is set, monitoring_interval must be != 0"""
        if self.monitoring_role_arn and self.monitoring_interval == 0:
            raise ValueError("monitoring_role_arn requires a monitoring_interval != 0")
        return self

    @model_validator(mode="after")
    def enhanced_monitoring_requires_monitoring_inverval(self) -> "Rds":
        """If monitoring_role_arn is set, monitoring_interval must be != 0"""
        if self.enhanced_monitoring and self.monitoring_interval == 0:
            raise ValueError("enhanced_monitoring requires a monitoring_interval != 0")
        return self

    @model_validator(mode="after")
    def kms_key_id_remove_alias_prefix(self) -> "Rds":
        """Remove alias prefix from kms_key_id"""
        if self.kms_key_id:
            self.kms_key_id = self.kms_key_id.removeprefix("alias/")
        return self


class AppInterfaceInput(BaseModel):
    """The input model class"""

    data: Rds
    provision: AppInterfaceProvision
