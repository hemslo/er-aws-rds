# Integration tests

The scenarios use [`erv2-itest`](https://github.com/app-sre/erv2-itest) and a
local `.erv2_itest.yml` configuration file. Run the commands below from the
repository root.

## Setup

Create the local configuration from the committed example and set the Vault
paths for your environment:

```shell
cp .erv2_itest.yml.example .erv2_itest.yml
```

`target_account` identifies the Vault KVv2 path containing the target AWS
credentials, and `tf_state_account` identifies the path containing the
Terraform state credentials. The local `.erv2_itest.yml` is ignored and must
not be committed because these paths are environment-specific.

Before running scenarios, ensure that:

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

## Read replica storage increase

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

Do not pass `--keep` to the cleanup command. Scenario logs and working
directories are stored under `.erv2-itests/`.

## Password reset during a storage update

The primary-instance storage-guard scenario increases storage, then attempts a
password reset immediately afterward while RDS is in `storage-optimization`.
The reset step is a dry-run and expects the post-plan guard to stop Terraform
before apply, so it does not change the database password. Rebuild the local
module image after switching worktrees or changing the hook source:

```shell
make build
erv2-itest --dry-run integration-tests/storage-update-password-guard/scenario.yaml
erv2-itest integration-tests/storage-update-password-guard/scenario.yaml
```

RDS enters `storage-optimization` after a storage size change, and this state
can last several hours. See [AWS storage scaling](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/USER_PIOPS.ModifyingExisting.ScalingUp.html).

## Blue/Green major upgrade

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
