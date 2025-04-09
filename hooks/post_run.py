#!/usr/bin/env python
import logging
import sys

from external_resources_io.exit_status import EXIT_ERROR, EXIT_OK

from hooks.utils.logger import setup_logging
from hooks.utils.runtime import should_rerun


def main() -> None:
    """Determine if required to rerun the job"""
    setup_logging()
    logger = logging.getLogger(__name__)
    if should_rerun():
        logger.info("rerun marker exists, exiting with error")
        sys.exit(EXIT_ERROR)
    else:
        logger.info("run completed successfully")
        sys.exit(EXIT_OK)


if __name__ == "__main__":
    main()
