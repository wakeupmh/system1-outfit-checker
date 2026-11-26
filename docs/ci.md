# CI and deploys

Two GitHub Actions workflows:

| Workflow | Runs on | Does |
|---|---|---|
| `ci` | every pull request, and pushes to `main` | `pytest`, the browser e2e check with mock models, `terraform validate`, the offline plan, and a check of `infra/bootstrap` |
| `deploy` | merges to `main`, or by hand | `make up` on both clouds, then `make sleep` so the GPU does not bill idle. By hand it also runs `warm`, `sleep`, `status` or `down` |

`ci` needs no settings. `deploy` needs the setup below once.

## Where the credentials go

No cloud key is stored in GitHub. Each cloud trusts GitHub's own identity token for one repository and one
GitHub environment (`production`), and hands the job short-lived credentials:

| Cloud | How the job signs in | What GitHub stores |
|---|---|---|
| AWS | OIDC: the job assumes the role `outfit-github-deploy` through `aws-actions/configure-aws-credentials` | The role ARN, as a variable |
| Google | Workload Identity Federation: the job impersonates the service account `outfit-github-deploy` through `google-github-actions/auth` | The provider name and service account email, as variables |

The only secret is the Gemini API key, which is an app setting rather than a cloud login.

All of it lives in the GitHub environment named `production`
(Settings > Environments > production):

| Name | Kind | Value |
|---|---|---|
| `GEMINI_API_KEY` | Secret | The key from Google AI Studio |
| `AWS_DEPLOY_ROLE_ARN` | Variable | From the bootstrap output |
| `AWS_REGION` | Variable | From the bootstrap output, for example `us-east-1` |
| `TF_STATE_BUCKET` | Variable | From the bootstrap output |
| `GCP_PROJECT` | Variable | From the bootstrap output |
| `GCP_WIF_PROVIDER` | Variable | From the bootstrap output |
| `GCP_DEPLOY_SA` | Variable | From the bootstrap output |
| `GCP_REGION` | Variable, optional | Default `us-central1` |
| `KEEP_WARM` | Variable, optional | `true` skips the `make sleep` after a deploy |

Putting them on the environment rather than the repository means you can add required reviewers to
`production`, so a merge waits for your approval before it spends money.

## One-time setup

Run this once from a laptop that is logged in to both clouds as an admin (`aws configure` or SSO, and
`gcloud auth application-default login`):

```bash
cp infra/bootstrap/terraform.tfvars.example infra/bootstrap/terraform.tfvars   # repo and GCP project
terraform -chdir=infra/bootstrap init
terraform -chdir=infra/bootstrap apply
terraform -chdir=infra/bootstrap output github_variables
```

It creates:

- An S3 bucket for Terraform state, versioned, encrypted and private. Laptops and CI share it.
- The GitHub OIDC provider in AWS (set `create_github_oidc_provider = false` if the account already has
  one), and the role `outfit-github-deploy`. The role can only be assumed by this repository's
  `production` environment, and its IAM rights only reach roles named `outfit-*`.
- A Workload Identity pool and provider in Google that only accept this repository's `production`
  environment, and the service account `outfit-github-deploy` with the roles the stack needs.

Then create the `production` environment in GitHub and copy the outputs into it, plus the
`GEMINI_API_KEY` secret. The bootstrap state stays in `infra/bootstrap/` on your laptop; keep it, since
`terraform -chdir=infra/bootstrap destroy` needs it.

The Google project still needs a billing account linked (Cloud Run requires it), and the AWS account
still needs the `ml.g6.xlarge for endpoint usage` quota. See `docs/deploy.md`.

## Sharing state with your laptop

CI keeps state in the bucket. To run `make` targets against the same deployment from a laptop, set the
bucket first; `make init` then writes `infra/backend_override.tf` (gitignored) pointing at S3:

```bash
export TF_STATE_BUCKET=<from the bootstrap output> TF_STATE_REGION=us-east-1
make status
```

Without `TF_STATE_BUCKET`, `make` keeps state in a local file, as before. Do not mix the two for one
deployment: a laptop with local state cannot see what CI created.

## Running deploy by hand

Actions > deploy > Run workflow, then pick:

- `warm` before a talk, then `status` until it says `live`.
- `sleep` after.
- `down` with confirm `destroy` to delete everything on both clouds. The state bucket and the bootstrap
  resources stay.

## What is not verified

The workflows have not run against real accounts yet. Untested on a real run: the OIDC and Workload
Identity sign-ins, Firebase Hosting deploys with Workload Identity credentials, whether the deploy role's
IAM rights cover every call Terraform makes, and building the CUDA decider image on a hosted runner's
disk.
