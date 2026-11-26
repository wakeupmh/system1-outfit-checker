# Deploy

`make up` builds and deploys the whole system to AWS and Google. `make down` deletes all of it.
Terraform in `infra/` keeps both clouds in one local state file, `infra/terraform.tfstate`. Keep that
file: `make down` needs it.

| Part | Cloud | Resource |
|---|---|---|
| Decider | AWS | SageMaker endpoint on `ml.g6.xlarge`, one inference component that scales between 0 and 1 copies |
| Front door | AWS | Lambda with a public function URL |
| Stylist | Google | Cloud Run service, Gemini key in Secret Manager |
| Web page | Google | Firebase Hosting site |

## Prerequisites

1. **AWS credentials** for an account that can create IAM roles, ECR, SageMaker, Lambda and CloudWatch
   resources. `aws sts get-caller-identity` must work.
2. **GPU quota.** New accounts often have 0. Check the SageMaker quota `ml.g6.xlarge for endpoint usage`
   in the region you deploy to, and request 1 if it is 0:

   ```bash
   aws service-quotas list-service-quotas --service-code sagemaker --region us-east-1 \
     --query "Quotas[?QuotaName=='ml.g6.xlarge for endpoint usage'].Value"
   ```

3. **A GCP project with a billing account linked.** Cloud Run and Cloud Build need one even inside the
   free tier. Then:

   ```bash
   gcloud auth login
   gcloud auth application-default login
   gcloud auth application-default set-quota-project YOUR_PROJECT
   ```

4. **A Gemini API key** from [AI Studio](https://aistudio.google.com/apikey).
5. **Firebase CLI**, logged in: `npm install -g firebase-tools && firebase login`.
6. **Docker** with `buildx`. The decider image is built for `linux/amd64`, so on Apple Silicon the build
   runs under emulation and is slow.
7. **Terraform 1.9 or later**, the AWS CLI, `gcloud` and `curl`.

## Configure

```bash
cp infra/terraform.tfvars.example infra/terraform.tfvars
```

Set `gcp_project` and `gemini_api_key`. Everything else has a default. `infra/terraform.tfvars` is
gitignored.

| Variable | Default | Use |
|---|---|---|
| `aws_region` | `us-east-1` | Where the GPU runs. `ml.g6.xlarge` costs the same in `us-west-2` |
| `gcp_region` | `us-central1` | Cloud Run and Artifact Registry |
| `demo_key` | generated | Value of the `x-demo-key` header. It ships inside `web/config.js`, so it only keeps out casual callers |
| `enable_gpu` | `true` | `false` skips SageMaker. The front door then calls `decider_url` |
| `instance_type` | `ml.g6.xlarge` | |
| `frontdoor_concurrency` | `4` | Caps Lambda cost. Set `-1` if the account's concurrency limit is 10, which rejects any reservation |
| `hosting_site_id` | `outfit-<random>` | Pin it to keep one URL across `down` and `up` |

To build the decider on another base image, run `make up DECIDER_BASE=<image>`.

## Commands

| Command | Does |
|---|---|
| `make up` | Creates the image repos, pushes the decider to ECR, builds the stylist with Cloud Build, applies everything, writes `web/config.js` and deploys the page. Safe to rerun: unchanged images are not rebuilt |
| `make warm` | Sets the decider to one copy. Returns 202 `{"state": "warming"}` |
| `make status` | Prints `cold`, `warming` or `live` |
| `make sleep` | Sets the decider to zero copies. The GPU instance goes away |
| `make down` | Deletes every resource on both clouds, image repos included |
| `make plan` | Shows what `make up` would change |
| `make plan-offline` | Plans the whole stack with no credentials, for checking the Terraform |
| `make fmt`, `make validate` | Format and validate the Terraform |

`make up` prints the page URL at the end. `terraform -chdir=infra output` shows the rest.

## Cold start

The decider scales to zero. At zero, SageMaker rejects every request and the front door answers
`503 {"state": "cold"}`. Two things start it:

- `POST /warm`, which the page's "Warm up" button and `make warm` call.
- Any `/score` call while cold. That raises the `NoCapacityInvocationFailures` alarm, and a step scaling
  policy adds a copy within about a minute of the alarm.

Either way SageMaker has to start a GPU instance, pull the image and download about 10 GB of weights from
Hugging Face. AWS says this takes several minutes. Its health check allows 15 minutes.

A target tracking policy removes the copy after a stretch with no traffic. Application Auto Scaling's
scale-in alarm usually wants about 15 minutes of low invocations, plus the 5 minute cooldown, so an idle
copy should live for roughly 15 to 20 minutes. This is not measured yet; see the checklist.

**Before a talk:** run `make warm` 20 minutes ahead and `make status` until it says `live`. Then open the
page so frames keep the copy busy, or run `make warm` again close to the start. Run `make sleep` after.

`make up` itself creates the endpoint with one live instance, so the GPU bills from the end of `make up`
until the copy scales in or you run `make sleep`.

## Costs

| Item | Cost |
|---|---|
| `ml.g6.xlarge` while a copy runs | $1.1267 per hour in `us-east-1` and `us-west-2` (AWS price list, see `docs/unknowns.md` C5) |
| GPU at zero copies | nothing |
| Lambda, Cloud Run, Firebase Hosting | nothing at idle, free tiers at demo traffic |
| Gemini | free tier; inputs may be used by Google, so the stylist only sees text |

What still bills at idle, at list prices not checked in this session:

- ECR storage, about $0.10 per GB-month. The CUDA decider image is several GB and the repo keeps the
  last 3 images.
- Artifact Registry storage past the free 0.5 GB, about $0.10 per GB-month.
- Secret Manager, $0.06 per secret version per month past the free 6.
- CloudWatch, $0.10 per month for the scale-out alarm, plus log storage kept 7 days.

`make down` removes all of these.

## First-run checklist

These items from `docs/unknowns.md` need a real account. Record the results there.

- [ ] **C4 quota.** The quota check above returns at least 1 before `make up`.
- [ ] **M3 GPU fit.** The inference component reaches `InService` and `make status` says `live`. If
      SageMaker reports a memory or GPU error, check the CloudWatch log groups under `/aws/sagemaker/` for the endpoint and inference component.
- [ ] **M4 latency.** The `ms` field of `/score` replies on the GPU, and the time the page sees per frame.
- [ ] **C3 scale from zero.** Time from `make warm` at zero copies to `live`. Time it a second time from a
      `/score` call while cold, which goes through the alarm instead.
- [ ] **Scale in.** How long an idle copy lives before `make status` says `cold`.
- [ ] **C8 function URL.** A browser call from the hosting URL succeeds, so both Lambda permissions are in
      place.

## When Firebase does not work from Terraform

Terraform adds Firebase to the project with `google_firebase_project` and creates the hosting site. If
that step fails, usually because the account has not accepted the Firebase terms, add Firebase once by
hand and rerun `make up`:

```bash
firebase projects:addfirebase YOUR_PROJECT
```

If the project already had Firebase, import it first:
`terraform -chdir=infra import google_firebase_project.this projects/YOUR_PROJECT`.
