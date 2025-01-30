# External Resources RDS Module

External Resources module to provision and manage RDS instances in AWS with App-Interface.

## Tech stack

* Terraform CDKTF
* AWS provider
* Random provider
* Python 3.11
* Pydantic

## Development

Ensure `uv` is installed.

Create `venv`:

```shell
uv venv
```

Activate `venv`:

```shell
source .venv/bin/activate
```

> :warning: **Attention**
>
> The CDKTF Python module generation needs at least 12GB of memory and takes around 5 minutes to complete.

Prepare your local development environment:

```shell
make dev
```

See the `Makefile` for more details.

## Debugging

Ensure `cdktf` is installed

```shell
npm install --global cdktf-cli@0.20.11
```

Export `input.json` via `qontract-cli` and place it in the current project root dir.

```shell
qontract-cli --config $CONFIG external-resources --provisioner $PROVISIONER --provider $PROVIDER --identifier $IDENTIFIER get-input > input.json
```

Generate terraform config.

```shell
ER_INPUT_FILE="$PWD"/input.json cdktf synth
```

Ensure AWS credentials set in current shell, then use `terraform` to verify.

```shell
cd cdktf.out/stakcs/CDKTF
terraform init
terraform plan -o plan
terraform show -json plan > plan.json
```

Test validation logic

```shell
ER_INPUT_FILE="$PWD"/input.json python validate_plan.py cdktf.out/stacks/CDKTF/plan.json
```
