#!/usr/bin/env python
import logging
import sys

from external_resources_io.exit_status import EXIT_ERROR, EXIT_OK, EXIT_SKIP
from external_resources_io.input import parse_model, read_input_from_file

from er_aws_rds.input import AppInterfaceInput
from hooks.utils.aws_api import AWSApi
from hooks.utils.blue_green_deployment_manager import BlueGreenDeploymentManager
from hooks.utils.logger import setup_logging
from hooks.utils.models import State
from hooks.utils.runtime import is_dry_run, mark_rerun


def main() -> None:
    """Manage Blue/Green Deployment"""
    setup_logging()
    logger = logging.getLogger(__name__)
    app_interface_input = parse_model(AppInterfaceInput, read_input_from_file())
    aws_api = AWSApi(region_name=app_interface_input.data.region)
    dry_run = is_dry_run()
    manager = BlueGreenDeploymentManager(
        aws_api=aws_api,
        app_interface_input=app_interface_input,
        dry_run=dry_run,
    )
    try:
        state = manager.run()
    except Exception:
        logger.exception("Error during Blue/Green Deployment management")
        sys.exit(EXIT_ERROR)
    match state:
        case State.NOT_ENABLED | State.NO_OP:
            logger.info("Continue to the next step")
            sys.exit(EXIT_OK)
        case (
            State.INIT
            | State.REPLICA_SOURCE_ENABLED
            | State.PROVISIONING
            | State.AVAILABLE
            | State.SWITCHOVER_IN_PROGRESS
            | State.SWITCHOVER_COMPLETED
            | State.DELETING_SOURCE_DB_INSTANCES
            | State.SOURCE_DB_INSTANCES_DELETED
            | State.DELETING
        ):
            logger.info("Blue/Green Deployment in progress, skip all other steps")
            sys.exit(EXIT_SKIP)
        case State.PENDING_PREPARE:
            if not dry_run:
                mark_rerun()
            logger.info("Pending prepare, continue to the next step")
            sys.exit(EXIT_OK)


if __name__ == "__main__":
    main()
