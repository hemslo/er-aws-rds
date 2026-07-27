from collections.abc import Sequence
from typing import Any, Literal, Self

from external_resources_io.input import AppInterfaceProvision
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    field_validator,
    model_validator,
)

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
    def transform(cls, v: Any) -> str:  # ruff: ignore[any-type]
        """values come as int|str|float|bool from App-Interface, but terraform only allows str"""
        return str(v)


class ParameterGroup(BaseModel):
    "db_parameter_group"

    family: str
    name: str | None = None
    description: str | None = None
    parameters: list[Parameter] | None = Field(default=None)


class BlueGreenDeploymentTarget(BaseModel):
    "AppInterface BlueGreenDeployment.Target"

    allocated_storage: int | None = None
    engine_version: str | None = None
    instance_class: str | None = None
    iops: int | None = None
    parameter_group: ParameterGroup | None = None
    storage_throughput: int | None = None
    storage_type: str | None = None


class BlueGreenDeployment(BaseModel):
    "AppInterface BlueGreenDeployment"

    enabled: bool | None = None
    switchover: bool | None = None
    delete: bool | None = None
    switchover_timeout: int | None = None
    target: BlueGreenDeploymentTarget | None = None


class ReplicaSource(BaseModel):
    "AppInterface ReplicaSource"

    region: str
    identifier: str
    blue_green_deployment: BlueGreenDeployment | None = None


class DBInstanceTimeouts(BaseModel):
    "DBInstance timeouts"

    create: str | None = None
    delete: str | None = None
    update: str | None = None


class BlueGreenUpdate(BaseModel):
    enabled: bool = False


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
    blue_green_deployment: BlueGreenDeployment | None = Field(
        default=None, exclude=True
    )
    replica_source: ReplicaSource | None = Field(default=None, exclude=True)
    enhanced_monitoring: bool | None = Field(default=None, exclude=True)
    reset_password: str | None = Field(default="", exclude=True)
    ca_cert: VaultSecret | None = Field(default=None, exclude=True)
    annotations: str | None = Field(default=None, exclude=True)
    event_notifications: list[EventNotification] | None = Field(
        default=None, exclude=True
    )
    data_classification: DataClassification | None = Field(default=None, exclude=True)
    # This value is use to override the db_name set in the outputs
    output_resource_db_name: str | None = Field(default=None, exclude=True)
    # Output_resource_name is redundant
    output_resource_name: str | None = Field(default=None, exclude=True)
    # output_prefix is not necessary since now each resources has it own state.
    output_prefix: str = Field(exclude=True)
    tags: dict[str, str] = Field(default_factory=dict, exclude=True)


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
    engine: str = "postgres"
    allow_major_version_upgrade: bool | None = False
    availability_zone: str | None = None
    monitoring_interval: int | None = None
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
    timeouts: DBInstanceTimeouts | None = None
    blue_green_update: BlueGreenUpdate | None = None
    deletion_protection: bool | None = None
    allocated_storage: int | None = None
    engine_version: str | None = None
    instance_class: str | None = None
    iops: int | None = None
    storage_throughput: int | None = None
    storage_type: str | None = None
    copy_tags_to_snapshot: bool | None = True
    vpc_security_group_ids: Sequence[str] | None = None

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
    def db_name(self) -> str | None:
        """db_name"""
        return self.name

    @model_validator(mode="after")
    def az_belongs_to_region(self) -> Self:
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
    def unset_az_if_multi_region(self) -> Self:
        """Remove az for multi_region instances"""
        if self.multi_az:
            self.availability_zone = None
        return self

    @model_validator(mode="after")
    def unset_replica_or_snapshot_not_allowed_attrs(self) -> Self:
        """
        Some attributes are not allowed if the instance is a read replica or is created from a snapshot.

        engine is not removed because it's needed in the plan validation.
        """
        if self.replica_source or self.replicate_source_db or self.snapshot_identifier:
            self.username = None
            self.password = None
            self.name = None
            self.allocated_storage = None
        return self

    @model_validator(mode="after")
    def replication(self) -> Self:
        """
        Validation and transformation for read replicas.

        replica_source and replicate_source_db are mutually exclusive.

        https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/db_instance#replicate_source_db-1
        If replicating an Amazon RDS Database Instance in the same region, use the identifier of the source DB, unless also specifying the db_subnet_group_name.
        If specifying the db_subnet_group_name in the same region, use the arn of the source DB.
        If replicating an Instance in a different region, use the arn of the source DB.
        Note that if you are creating a cross-region replica of an encrypted database you will also need to specify a kms_key_id.

        The ARN is resolved in the module using a Datasource.

        https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/db_instance#db_subnet_group_name-1
        When working with read replicas created in the same region, defaults to the Subnet Group Name of the source DB.
        When working with read replicas created in a different region, defaults to the default Subnet Group.

        backup_retention_period is left unmanaged (None) for replicas to avoid
        conflicting with AWS Backup when it controls the retention period.
        """
        if not self.replica_source:
            return self

        if self.replicate_source_db:
            raise ValueError(
                "Only one of replicate_source_db or replica_source can be defined"
            )

        if self.replica_source.region != self.region:
            if not self.db_subnet_group_name:
                raise ValueError(
                    "db_subnet_group_name must be defined for cross-region replicas"
                )
            if self.storage_encrypted and not self.kms_key_id:
                raise ValueError(
                    "storage_encrypted ignored for cross-region read replica. Set kms_key_id"
                )
        elif not self.db_subnet_group_name:
            self.replicate_source_db = self.replica_source.identifier

        self.backup_retention_period = None
        return self

    @model_validator(mode="after")
    def _validate_major_version_upgrade_for_replica(self) -> Self:
        """
        Major Version Upgrade not supported for Postgres Read Replica DB Instances

        doc: https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/USER_UpgradeDBInstance.PostgreSQL.html
        """
        if (
            self.is_read_replica
            and self.engine == "postgres"
            and self.allow_major_version_upgrade
        ):
            raise ValueError(
                "allow_major_version_upgrade is not supported for postgres read replica instances"
            )
        return self

    @model_validator(mode="after")
    def parameter_groups(self) -> Self:
        """
        Sets the right parameter group names. The instance identifier is used as prefix on each pg.

        This way each instance will have its own parameter group, without re-using them on multiple instances.
        """
        if self.parameter_group:
            name = f"{self.identifier}-{self.parameter_group.name or 'pg'}"
            self.parameter_group.name = name
            self.parameter_group_name = name

        if (
            self.blue_green_deployment
            and self.blue_green_deployment.target
            and (pg := self.blue_green_deployment.target.parameter_group)
        ):
            pg.name = f"{self.identifier}-{pg.name or 'pg'}"
            if (
                self.parameter_group
                and pg.name == self.parameter_group.name
                and pg != self.parameter_group
            ):
                raise ValueError(
                    "Blue/Green Deployment Parameter Group name already exist"
                )
        return self

    @property
    def is_read_replica(self) -> bool:
        """Returns true if the instance is a read replica"""
        return self.replica_source is not None or self.replicate_source_db is not None

    @model_validator(mode="after")
    def enhanced_monitoring_attributes(self) -> Self:
        """
        Enhanced monitoring validation:

        * If em is disabled, related parameters are removed.
        * If em is enabled and no monitoring_inverval specificied, set the default value (60)
        * If em is enabled and monitoring_interval is set to 0. Raise Validation Error
        """
        if self.enhanced_monitoring and self.monitoring_interval == 0:
            raise ValueError(
                "Monitoring interval can not be 0 when enhanced monitoring is enabled."
                "Set enhanced_monitoring=0 to disable Enhanced monitoring."
            )
        if self.enhanced_monitoring and self.monitoring_interval is None:
            self.monitoring_interval = 60

        if not self.enhanced_monitoring:
            self.monitoring_interval = None
            self.monitoring_role_arn = None

        return self

    @model_validator(mode="after")
    def kms_key_id_remove_alias_prefix(self) -> Self:
        """Remove alias prefix from kms_key_id"""
        if self.kms_key_id:
            self.kms_key_id = self.kms_key_id.removeprefix("alias/")
        return self

    @model_validator(mode="after")
    def _validate_blue_green_update(self) -> Self:
        if self.blue_green_update and self.blue_green_update.enabled:
            raise ValueError(
                "blue_green_update is not supported, use blue_green_deployment instead"
            )
        return self

    @model_validator(mode="after")
    def _validate_blue_green_deployment_for_replica(self) -> Self:
        """
        Validate the blue_green_deployment for read replicas

        * blue_green_deployment is not supported for read replica instance (only supported for primary instance)
        * If the replica_source has blue_green_deployment enabled
          * parameter_group must be None
          * deletion_protection must be False
          * region must match replica_source region
          * engine_version must match replica_source engine_version if specified in target after switchover and delete,
            note only engine_version is applied to all instances,
            instance-class is supposed to be applied to all instances but actually only applied to primary instance,
            so we only validate engine_version.
            doc: https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/blue-green-deployments-creating.html#create-blue-green-settings
        """
        if (
            self.replica_source
            and (blue_green_deployment := self.replica_source.blue_green_deployment)
            and blue_green_deployment.enabled
        ):
            if self.parameter_group:
                raise ValueError(
                    "parameter_group is not supported when replica_source has blue_green_deployment enabled"
                )
            if self.deletion_protection:
                raise ValueError(
                    "deletion_protection must be disabled when replica_source has blue_green_deployment enabled"
                )
            if self.region != self.replica_source.region:
                raise ValueError(
                    "Cross-region read replicas are not currently supported for Blue Green Deployments"
                )
            if (
                blue_green_deployment.switchover
                and blue_green_deployment.delete
                and blue_green_deployment.target
                and (engine_version := blue_green_deployment.target.engine_version)
                and engine_version != self.engine_version
            ):
                not_matched = {
                    "engine_version": engine_version,
                }
                raise ValueError(
                    f"desired config not match replica_source blue_green_deployment.target, update: {not_matched}"
                )
        if self.is_read_replica and self.blue_green_deployment:
            raise ValueError(
                "blue_green_deployment is not supported for replica instance"
            )
        return self

    @model_validator(mode="after")
    def _validate_blue_green_deployment_target(self) -> Self:
        if (
            self.blue_green_deployment
            and self.blue_green_deployment.target
            and self.blue_green_deployment.enabled
            and self.blue_green_deployment.switchover
            and self.blue_green_deployment.delete
        ):
            desired_config = BlueGreenDeploymentTarget(
                allocated_storage=self.allocated_storage,
                engine_version=self.engine_version,
                instance_class=self.instance_class,
                iops=self.iops,
                storage_throughput=self.storage_throughput,
                storage_type=self.storage_type,
                parameter_group=self.parameter_group,
            ).model_dump()
            target = self.blue_green_deployment.target.model_dump(exclude_none=True)
            not_matched = {k: v for k, v in target.items() if desired_config[k] != v}
            if not_matched:
                raise ValueError(
                    f"desired config not match blue_green_deployment.target after delete, update: {not_matched}"
                )
        return self


class AppInterfaceInput(BaseModel):
    """The input model class"""

    data: Rds
    provision: AppInterfaceProvision


class TerraformModuleData(BaseModel):
    """Variables to feed the Terraform Module"""

    ai_input: AppInterfaceInput = Field(exclude=True)

    @computed_field
    def rds_instance(self) -> Rds | None:
        """The db_instance variable"""
        return self.ai_input.data

    @computed_field
    def output_resource_db_name(self) -> str | None:
        """Output resource db_name"""
        return self.ai_input.data.output_resource_db_name

    @computed_field
    def parameter_groups(self) -> list[ParameterGroup] | None:
        """Parameter groups to create"""
        parameter_group = self.ai_input.data.parameter_group
        parameter_groups = [parameter_group] if parameter_group else []
        if (
            self.ai_input.data.blue_green_deployment
            and self.ai_input.data.blue_green_deployment.target
            and (pg := self.ai_input.data.blue_green_deployment.target.parameter_group)
            and (pg != parameter_group)
        ):
            parameter_groups.append(pg)
        return parameter_groups

    @computed_field
    def reset_password(self) -> str | None:
        """Terraform password variable"""
        return self.ai_input.data.reset_password

    @computed_field
    def enhanced_monitoring_role(self) -> str | None:
        """Sets the enhanced monitoring terraform variable if needed"""
        if (
            self.ai_input.data.enhanced_monitoring
            and self.ai_input.data.monitoring_role_arn is None
        ):
            return self.ai_input.data.enhanced_monitoring_role_name
        return None

    @computed_field
    def replica_source(self) -> ReplicaSource | None:
        """ReplicaSource terraform variable"""
        return self.ai_input.data.replica_source

    @computed_field
    def ca_cert(self) -> str | None:
        if self.ai_input.data.ca_cert:
            return self.ai_input.data.ca_cert.to_vault_ref()
        return None

    @computed_field
    def tags(self) -> dict[str, Any] | None:
        """Tags"""
        return self.ai_input.data.tags

    @computed_field
    def region(self) -> str:
        """Tags"""
        return self.ai_input.data.region

    @computed_field
    def provision(self) -> AppInterfaceProvision:
        """Provision"""
        return self.ai_input.provision
