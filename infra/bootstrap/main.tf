# One-time setup for GitHub Actions deploys: a state bucket, an AWS role GitHub can assume through OIDC,
# and a Google service account GitHub can use through Workload Identity Federation. No long-lived keys.
# Run once with admin credentials; state stays local in this folder.

terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
    google = {
      source  = "hashicorp/google"
      version = "~> 8.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.7"
    }
  }
}

variable "github_repo" {
  description = "owner/name of the repository whose main branch may deploy."
  type        = string
}

variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "gcp_project" {
  type = string
}

variable "name" {
  description = "Must match var.name in infra/. Resource names and IAM scopes start with it."
  type        = string
  default     = "outfit"
}

variable "create_github_oidc_provider" {
  description = "false when the account already has token.actions.githubusercontent.com as an OIDC provider."
  type        = bool
  default     = true
}

provider "aws" {
  region = var.aws_region
}

provider "google" {
  project = var.gcp_project
}

data "aws_caller_identity" "me" {}

resource "random_id" "bucket" {
  byte_length = 4
}

resource "aws_s3_bucket" "state" {
  bucket = "${var.name}-tfstate-${random_id.bucket.hex}"
}

resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "state" {
  bucket = aws_s3_bucket.state.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "state" {
  bucket                  = aws_s3_bucket.state.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_iam_openid_connect_provider" "github" {
  count          = var.create_github_oidc_provider ? 1 : 0
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}

locals {
  oidc_provider_arn = var.create_github_oidc_provider ? aws_iam_openid_connect_provider.github[0].arn : "arn:aws:iam::${data.aws_caller_identity.me.account_id}:oidc-provider/token.actions.githubusercontent.com"
  account           = data.aws_caller_identity.me.account_id
}

data "aws_iam_policy_document" "github_assume" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [local.oidc_provider_arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repo}:environment:production"]
    }
  }
}

resource "aws_iam_role" "github_deploy" {
  name                 = "${var.name}-github-deploy"
  assume_role_policy   = data.aws_iam_policy_document.github_assume.json
  max_session_duration = 7200
}

data "aws_iam_policy_document" "github_deploy" {
  statement {
    sid       = "State"
    actions   = ["s3:ListBucket", "s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = [aws_s3_bucket.state.arn, "${aws_s3_bucket.state.arn}/*"]
  }
  statement {
    sid = "Services"
    actions = [
      "ecr:*",
      "sagemaker:*",
      "lambda:*",
      "logs:*",
      "cloudwatch:*",
      "application-autoscaling:*",
    ]
    resources = ["*"]
  }
  statement {
    sid = "OwnRoles"
    actions = [
      "iam:CreateRole", "iam:DeleteRole", "iam:GetRole", "iam:TagRole", "iam:UntagRole",
      "iam:UpdateAssumeRolePolicy", "iam:PutRolePolicy", "iam:GetRolePolicy", "iam:DeleteRolePolicy",
      "iam:ListRolePolicies", "iam:ListAttachedRolePolicies", "iam:AttachRolePolicy",
      "iam:DetachRolePolicy", "iam:ListInstanceProfilesForRole", "iam:PassRole",
    ]
    resources = ["arn:aws:iam::${local.account}:role/${var.name}-*"]
  }
  statement {
    sid       = "AutoscalingServiceRole"
    actions   = ["iam:CreateServiceLinkedRole"]
    resources = ["arn:aws:iam::${local.account}:role/aws-service-role/sagemaker.application-autoscaling.amazonaws.com/*"]
  }
}

resource "aws_iam_role_policy" "github_deploy" {
  role   = aws_iam_role.github_deploy.id
  policy = data.aws_iam_policy_document.github_deploy.json
}

resource "google_project_service" "bootstrap" {
  for_each           = toset(["iam.googleapis.com", "iamcredentials.googleapis.com", "sts.googleapis.com", "cloudresourcemanager.googleapis.com"])
  service            = each.value
  disable_on_destroy = false
}

resource "google_iam_workload_identity_pool" "github" {
  workload_identity_pool_id = "${var.name}-github"
  display_name              = "GitHub Actions"
  depends_on                = [google_project_service.bootstrap]
}

resource "google_iam_workload_identity_pool_provider" "github" {
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "github"
  attribute_mapping = {
    "google.subject"        = "assertion.sub"
    "attribute.repository"  = "assertion.repository"
    "attribute.environment" = "assertion.environment"
  }
  attribute_condition = "assertion.repository == '${var.github_repo}' && assertion.environment == 'production'"
  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

resource "google_service_account" "github_deploy" {
  account_id   = "${var.name}-github-deploy"
  display_name = "GitHub Actions deploys"
}

resource "google_service_account_iam_member" "github_wif" {
  service_account_id = google_service_account.github_deploy.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repository/${var.github_repo}"
}

resource "google_project_iam_member" "github_deploy" {
  for_each = toset([
    "roles/run.admin",
    "roles/artifactregistry.admin",
    "roles/cloudbuild.builds.editor",
    "roles/secretmanager.admin",
    "roles/firebase.admin",
    "roles/serviceusage.serviceUsageAdmin",
    "roles/iam.serviceAccountAdmin",
    "roles/iam.serviceAccountUser",
    "roles/storage.admin",
    "roles/logging.viewer",
  ])
  project = var.gcp_project
  role    = each.value
  member  = "serviceAccount:${google_service_account.github_deploy.email}"
}

output "github_variables" {
  description = "Set these as repository variables (Settings > Secrets and variables > Actions > Variables)."
  value = {
    AWS_DEPLOY_ROLE_ARN = aws_iam_role.github_deploy.arn
    AWS_REGION          = var.aws_region
    TF_STATE_BUCKET     = aws_s3_bucket.state.bucket
    GCP_PROJECT         = var.gcp_project
    GCP_WIF_PROVIDER    = google_iam_workload_identity_pool_provider.github.name
    GCP_DEPLOY_SA       = google_service_account.github_deploy.email
  }
}
