# External Resources RDS Module

External Resources module to provision and manage RDS instances in AWS with App-Interface.

## Tech stack

* Terraform
* AWS provider
* Random provider
* Python 3.12
* Pydantic

## Development

Ensure `uv` is installed.

Prepare local development environment:

```shell
make dev
```

This will auto create a `venv`, to activate in shell:

```shell
source .venv/bin/activate
```

The commands below assume this virtual environment is active; `erv2-itest` is
installed as a development dependency.

### Manage Terraform Providers

* update versions in [versions.tf](./module/versions.tf)
* refresh [.terraform.lock.hcl](./module/.terraform.lock.hcl) with:

  ```shell
  make providers-lock
  ```

## Debugging

Export `input.json` via `qontract-cli` and place it in the current project root dir.

```shell
qontract-cli --config $CONFIG external-resources --provisioner $PROVISIONER --provider $PROVIDER --identifier $IDENTIFIER get-input > input.json
```

Get `credentials`

```shell
qontract-cli --config $CONFIG external-resources --provisioner $PROVISIONER --provider $PROVIDER --identifier $IDENTIFIER get-credentials > credentials
```

Optional config `.env`:

```shell
cp .env.example .env
```

Populate `.env` values with absolute path

Export to current shell

```shell
export $(cat .env | xargs)
```

### Integration tests

The integration-test scenarios use [`erv2-itest`](https://github.com/app-sre/erv2-itest)
and a local `.erv2_itest.yml` configuration file. Create it from the committed
example and set the Vault paths for your environment:

```shell
cp .erv2_itest.yml.example .erv2_itest.yml
```

`target_account` identifies the Vault KVv2 path containing the target AWS
credentials, and `tf_state_account` identifies the path containing the
Terraform state credentials. The local `.erv2_itest.yml` is ignored and must
not be committed because these paths are environment-specific.

Before running the scenarios, make sure that:

* Vault CLI is authenticated so `erv2-itest` can obtain the AWS credentials.
* Your AWS credentials can access the target account and Terraform state bucket.
* A local Docker or Podman installation is available.

Install the development dependencies and build the module image:

```shell
make dev
make build
```

Preview a scenario without contacting Vault, Docker, or AWS:

```shell
erv2-itest --dry-run integration-tests/basic/scenario.yaml
```

To exercise the replica storage update, first create and retain a basic source
instance. Copy the `Run ID` printed by this command:

```shell
erv2-itest --keep integration-tests/basic/scenario.yaml
```

Use that run ID for the replica scenario. The replica input uses the run ID for
the source identifier and automatically gives the replica its own identifier
and Terraform state key. It creates the replica at 20 GiB, changes it to 30 GiB,
verifies the following reconcile is a no-op, and destroys the replica during
cleanup.

```shell
SOURCE_RUN_ID="<source-run-id-from-output>"
erv2-itest \
  --run-id "$SOURCE_RUN_ID" \
  integration-tests/read-replica-storage-increase/scenario.yaml
```

Finally, clean up the retained basic source instance by selecting only its
cleanup step:

```shell
erv2-itest \
  --run-id "$SOURCE_RUN_ID" \
  --select '::destroy database' \
  integration-tests/basic/scenario.yaml
```

Do not pass `--keep` to the cleanup command. The scenario logs and working
directories are stored under `.erv2-itests/`.

The Blue/Green major-upgrade scenarios use their own PostgreSQL 16.14 base
input and target PostgreSQL 17.11. Run both cases with:

```shell
erv2-itest \
  integration-tests/blue-green-deployment/scenario.yaml \
  integration-tests/blue-green-deployment/abort.yaml
```

The switchover scenario promotes the PostgreSQL 17 green instance and verifies
steady state. The abort scenario deletes green without switchover and verifies
that the PostgreSQL 16 source remains unchanged. Both scenarios clean up the
database and parameter groups. If a switchover fails, the manager preserves the
source instance; retain the run ID and use the manual cleanup procedure if the
scenario cleanup also fails. These scenarios do not verify that AWS accepts
deletion in `INVALID_CONFIGURATION`; verify that path in non-production.

### On Host

Generate terraform config.

```shell
generate-tf-config
```

Ensure AWS credentials set in current shell, then use `terraform` to verify.

```shell
cd module
terraform init
terraform plan -out=plan
terraform show -json plan > plan.json
```

Test hooks

```shell
hooks/post_plan.py
```

### In Container

Build image first

```shell
make build
```

Start container

```shell
docker run --rm -ti \
  --entrypoint /bin/bash \
  -v $PWD/input.json:/inputs/input.json:Z \
  -v $PWD/credentials:/credentials:Z \
  -e AWS_SHARED_CREDENTIALS_FILE=/credentials \
  -e WORK=/tmp/work \
  er-aws-rds:prod
```

Run the whole process

```shell
./entrypoint.sh
```
