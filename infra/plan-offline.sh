#!/usr/bin/env bash
# Plan the whole stack with no cloud credentials, against a throwaway copy of infra/.
# The credential skips live only in an override file inside that copy.
set -euo pipefail

infra="$(cd "$(dirname "$0")" && pwd)"
repo="$(dirname "$infra")"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

mkdir -p "$work/infra"
cp "$infra"/*.tf "$infra/.terraform.lock.hcl" "$work/infra/"

if [ -f "$repo/frontdoor/handler.py" ]; then
  cp -r "$repo/frontdoor" "$work/frontdoor"
else
  mkdir "$work/frontdoor"
  printf 'def handler(event, context):\n    return {"statusCode": 200}\n' > "$work/frontdoor/handler.py"
  echo "plan-offline: frontdoor/ missing, using a stub handler" >&2
fi

cat > "$work/infra/offline_override.tf" <<'EOF'
provider "aws" {
  skip_credentials_validation = true
  skip_requesting_account_id  = true
  skip_metadata_api_check     = true
  skip_region_validation      = true
}
EOF

cat > "$work/infra/offline.tfvars" <<'EOF'
gcp_project    = "offline-plan-project"
gemini_api_key = "offline-not-a-key"
EOF

export AWS_ACCESS_KEY_ID=AKIAOFFLINEPLAN00000 AWS_SECRET_ACCESS_KEY=offline AWS_SESSION_TOKEN=
export AWS_PROFILE= AWS_CONFIG_FILE=/dev/null AWS_SHARED_CREDENTIALS_FILE=/dev/null
export GOOGLE_OAUTH_ACCESS_TOKEN=offline-token GOOGLE_APPLICATION_CREDENTIALS=
export TF_PLUGIN_CACHE_DIR="${TF_PLUGIN_CACHE_DIR:-$HOME/.terraform.d/plugin-cache}"
mkdir -p "$TF_PLUGIN_CACHE_DIR"

cd "$work/infra"
terraform init -input=false -backend=false >/dev/null
terraform plan -input=false -refresh=false -lock=false -var-file=offline.tfvars "$@"
