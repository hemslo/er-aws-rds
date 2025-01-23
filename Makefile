SITE_PACKAGES_DIR ?= $(shell .venv/bin/python3 -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')
CONTAINER_ENGINE ?= $(shell which podman >/dev/null 2>&1 && echo podman || echo docker)

.PHONY: format
format:
	uv run ruff check
	uv run ruff format

.PHONY: image_tests
image_tests:
	# test /tmp must be empty
	[ -z "$(shell ls -A /tmp)" ]
	# validate_plan.py must exist
	[ -f "validate_plan.py" ]

.PHONY: code_tests
code_tests:
	uv run ruff check --no-fix
	uv run ruff format --check
	uv run mypy
	uv run pytest -vv --cov=er_aws_rds --cov-report=term-missing --cov-report xml

.PHONY: dependency_tests
dependency_tests:
	python -c "import cdktf_cdktf_provider_random"
	python -c "import cdktf_cdktf_provider_aws"

.PHONY: test
test: image_tests code_tests dependency_tests

.PHONY: build
build:
	$(CONTAINER_ENGINE) build --progress plain -t er-aws-rds:test .

.PHONY: dev
dev:
	# Prepare local development environment
	uv sync
	# The CDKTF python module generation needs at least 12GB of memory!
	mkdir -p .gen
	$(CONTAINER_ENGINE) run --rm -it -v $(PWD)/:/home/app/src -v $(PWD)/.gen:/cdktf-providers:z --entrypoint cdktf-provider-sync quay.io/redhat-services-prod/app-sre-tenant/er-base-cdktf-main/er-base-cdktf-main:latest /cdktf-providers
	cp sitecustomize.py $(SITE_PACKAGES_DIR)
