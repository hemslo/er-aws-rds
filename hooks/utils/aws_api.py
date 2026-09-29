from typing import TYPE_CHECKING

from boto3 import Session

if TYPE_CHECKING:
    from mypy_boto3_ec2 import EC2Client
    from mypy_boto3_rds import RDSClient
    from mypy_boto3_rds.type_defs import (
        BlueGreenDeploymentTypeDef,
        DBInstanceTypeDef,
        DBParameterGroupTypeDef,
        DeleteBlueGreenDeploymentRequestTypeDef,
        DescribeDBParametersMessagePaginateTypeDef,
        DescribeEngineDefaultParametersMessagePaginateTypeDef,
        FilterTypeDef,
        ParameterOutputTypeDef,
        SwitchoverBlueGreenDeploymentRequestTypeDef,
        UpgradeTargetTypeDef,
    )

    from hooks.utils.models import CreateBlueGreenDeploymentParams


class AWSApi:
    """AWS Api Class"""

    def __init__(self, region_name: str | None = None) -> None:
        self.session = Session(region_name=region_name)
        self.rds_client: RDSClient = self.session.client("rds")
        self.ec2_client: EC2Client = self.session.client("ec2")

    def get_security_group_ids_for_db_subnet_group(
        self, db_subnet_group_name: str
    ) -> set[str]:
        """
        Get all available security group IDs for a given DB subnet group

        :param db_subnet_group_name: Name of the DB subnet group
        :return: Set of security group IDs available in the VPC of the DB subnet group
        """
        try:
            response = self.rds_client.describe_db_subnet_groups(
                DBSubnetGroupName=db_subnet_group_name
            )
        except self.rds_client.exceptions.DBSubnetGroupNotFoundFault:
            return set()

        if not response["DBSubnetGroups"]:
            return set()

        # Get the VPC ID from the first subnet in the group
        vpc_id = response["DBSubnetGroups"][0].get("VpcId")
        if not vpc_id:
            return set()

        # Get all security groups in that VPC
        paginator = self.ec2_client.get_paginator("describe_security_groups")
        page_iterator = paginator.paginate(
            Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]
        )

        return {
            sg["GroupId"]
            for page in page_iterator
            for sg in page.get("SecurityGroups", [])
        }

    def is_rds_engine_version_available(self, engine: str, version: str) -> bool:
        """Checks if the engine version is available"""
        data = self.rds_client.describe_db_engine_versions(
            Engine=engine,
            EngineVersion=version,
        ).get("DBEngineVersions", [])

        return len(data) == 1 and data[0].get("EngineVersion") == version

    def get_rds_valid_upgrade_targets(
        self,
        engine: str,
        version: str,
    ) -> dict[str, UpgradeTargetTypeDef]:
        """Get RDS valid upgrade targets"""
        data = self.rds_client.describe_db_engine_versions(
            Engine=engine,
            EngineVersion=version,
            IncludeAll=True,
        )
        if not data.get("DBEngineVersions"):
            return {}

        return {
            item["EngineVersion"]: item
            for item in data["DBEngineVersions"][0].get("ValidUpgradeTarget", [])
        }

    def get_blue_green_deployment_valid_upgrade_targets(
        self,
        engine: str,
        version: str,
    ) -> dict[str, UpgradeTargetTypeDef]:
        """Get Blue/Green Deployment valid upgrade targets"""
        current_version_as_target: UpgradeTargetTypeDef = {
            "Engine": engine,
            "EngineVersion": version,
            "IsMajorVersionUpgrade": False,
        }
        candidate_upgrade_targets = {
            version: current_version_as_target
        } | self.get_rds_valid_upgrade_targets(engine, version)
        filters: list[FilterTypeDef] = [
            {
                "Name": "engine-version",
                "Values": list(candidate_upgrade_targets.keys()),
            },
        ]
        data = self.rds_client.describe_db_engine_versions(
            Engine=engine,
            Filters=filters,
        )
        if not data["DBEngineVersions"]:
            return {}
        available_versions = {
            item["EngineVersion"] for item in data["DBEngineVersions"]
        }
        return {
            version: item
            for version, item in candidate_upgrade_targets.items()
            if version in available_versions
        }

    def get_db_parameter_group(self, name: str) -> DBParameterGroupTypeDef | None:
        """Get DB parameter group info"""
        try:
            data = self.rds_client.describe_db_parameter_groups(
                DBParameterGroupName=name
            )
        except self.rds_client.exceptions.DBParameterGroupNotFoundFault:
            return None
        return data["DBParameterGroups"][0] if data["DBParameterGroups"] else None

    def get_db_parameters(
        self,
        parameter_group_name: str,
        parameter_names: list[str] | None = None,
    ) -> dict[str, ParameterOutputTypeDef]:
        """Get DB parameters"""
        kwargs: DescribeDBParametersMessagePaginateTypeDef = {
            "DBParameterGroupName": parameter_group_name,
        }
        if parameter_names:
            kwargs["Filters"] = [
                {
                    "Name": "parameter-name",
                    "Values": parameter_names,
                }
            ]
        paginator = self.rds_client.get_paginator("describe_db_parameters")
        page_iterator = paginator.paginate(**kwargs)
        return {
            item["ParameterName"]: item
            for data in page_iterator
            for item in data["Parameters"] or []
        }

    def get_engine_default_parameters(
        self,
        parameter_group_family: str,
        parameter_names: list[str] | None = None,
    ) -> dict[str, ParameterOutputTypeDef]:
        """Get engine default parameters"""
        kwargs: DescribeEngineDefaultParametersMessagePaginateTypeDef = {
            "DBParameterGroupFamily": parameter_group_family,
        }
        if parameter_names:
            kwargs["Filters"] = [
                {
                    "Name": "parameter-name",
                    "Values": parameter_names,
                }
            ]
        paginator = self.rds_client.get_paginator("describe_engine_default_parameters")
        page_iterator = paginator.paginate(**kwargs)
        return {
            item["ParameterName"]: item
            for data in page_iterator
            for item in data.get("EngineDefaults", {}).get("Parameters") or []
        }

    def get_db_instance(self, identifier: str) -> DBInstanceTypeDef | None:
        """Get DB instance info"""
        try:
            data = self.rds_client.describe_db_instances(
                DBInstanceIdentifier=identifier
            )
        except self.rds_client.exceptions.DBInstanceNotFoundFault:
            return None
        if not data["DBInstances"]:
            return None
        db_instance = data["DBInstances"][0]
        # ReplicaMode can contain unknown ReplicaModeType values like read-write
        # exclude it to avoid Pydantic validation error
        db_instance.pop("ReplicaMode", None)
        return db_instance

    def delete_db_instance(self, identifier: str) -> None:
        self.rds_client.delete_db_instance(
            DBInstanceIdentifier=identifier,
            SkipFinalSnapshot=True,
        )

    def create_blue_green_deployment(
        self, params: CreateBlueGreenDeploymentParams
    ) -> None:
        """Create Blue/Green Deployment"""
        kwargs = params.model_dump(by_alias=True, exclude_none=True)
        self.rds_client.create_blue_green_deployment(**kwargs)

    def get_blue_green_deployment(self, name: str) -> BlueGreenDeploymentTypeDef | None:
        """Get Blue/Green Deployment"""
        data = self.rds_client.describe_blue_green_deployments(
            Filters=[
                {
                    "Name": "blue-green-deployment-name",
                    "Values": [name],
                }
            ]
        )
        return data["BlueGreenDeployments"][0] if data["BlueGreenDeployments"] else None

    def switchover_blue_green_deployment(
        self,
        identifier: str,
        timeout: int | None = None,
    ) -> BlueGreenDeploymentTypeDef:
        """Switchover Blue/Green Deployment"""
        kwargs: SwitchoverBlueGreenDeploymentRequestTypeDef = {
            "BlueGreenDeploymentIdentifier": identifier,
        }
        if timeout is not None:
            kwargs["SwitchoverTimeout"] = timeout
        response = self.rds_client.switchover_blue_green_deployment(**kwargs)
        return response["BlueGreenDeployment"]

    def delete_blue_green_deployment(
        self,
        identifier: str,
        *,
        delete_target: bool | None = None,
    ) -> None:
        """
        Delete Blue/Green Deployment

        :param identifier: Blue/Green Deployment Identifier
        :param delete_target: Specifies whether to delete the resources in the green environment.
                              You can not specify this option if the blue/green deployment
                              status is SWITCHOVER_COMPLETED.
        """
        kwargs: DeleteBlueGreenDeploymentRequestTypeDef = {
            "BlueGreenDeploymentIdentifier": identifier
        }
        if delete_target is not None:
            kwargs["DeleteTarget"] = delete_target
        self.rds_client.delete_blue_green_deployment(**kwargs)
