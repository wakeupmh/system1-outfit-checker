SHELL := bash
.SHELLFLAGS := -euo pipefail -c
.DEFAULT_GOAL := help

TF     := terraform -chdir=infra
IMAGES := infra/images.auto.tfvars

# Reads a value from tfvars or state without needing a full apply first.
tfval = echo '$(1)' | $(TF) console | tr -d '"'
# Content hash of a directory, so an unchanged directory is not rebuilt or redeployed.
dirhash = find $(1) -type f ! -path '*/__pycache__/*' -print0 | LC_ALL=C sort -z | xargs -0 cksum | cksum | cut -d' ' -f1

DECIDER_BASE ?=

.PHONY: help up down init repos images decider-image stylist-image apply web warm sleep status plan plan-offline fmt validate

help:
	@echo "make up | down | warm | sleep | status | plan | plan-offline | fmt | validate"

infra/terraform.tfvars:
	@echo "Copy infra/terraform.tfvars.example to infra/terraform.tfvars and fill it in." >&2
	@exit 1

up: infra/terraform.tfvars init repos images apply web

init:
	$(TF) init -input=false

repos:
	$(TF) apply -input=false -auto-approve \
		-target=aws_ecr_repository.decider \
		-target=google_artifact_registry_repository.stylist

images: decider-image stylist-image
	decider_tag=$$($(call dirhash,decider)); \
	stylist_tag=$$($(call dirhash,stylist)); \
	stylist_repo=$$($(TF) output -raw stylist_repo_url); \
	printf 'decider_image_tag = "%s"\nstylist_image     = "%s/stylist:%s"\n' \
		"$$decider_tag" "$$stylist_repo" "$$stylist_tag" > $(IMAGES)

decider-image:
	if [ "$$($(call tfval,var.enable_gpu))" != true ]; then echo "enable_gpu is false, skipping the decider image"; exit 0; fi; \
	tag=$$($(call dirhash,decider)); \
	repo=$$($(TF) output -raw ecr_repo_url); \
	region=$$($(call tfval,var.aws_region)); \
	if aws ecr describe-images --region "$$region" --repository-name "$${repo#*/}" --image-ids imageTag="$$tag" >/dev/null 2>&1; then \
		echo "decider:$$tag is already in ECR"; \
	else \
		aws ecr get-login-password --region "$$region" | docker login --username AWS --password-stdin "$${repo%%/*}"; \
		docker build --platform linux/amd64 $(if $(DECIDER_BASE),--build-arg BASE=$(DECIDER_BASE)) -t "$$repo:$$tag" decider; \
		docker push "$$repo:$$tag"; \
	fi

stylist-image:
	tag=$$($(call dirhash,stylist)); \
	image=$$($(TF) output -raw stylist_repo_url)/stylist:$$tag; \
	project=$$($(call tfval,var.gcp_project)); \
	if gcloud artifacts docker images describe "$$image" --project "$$project" >/dev/null 2>&1; then \
		echo "$$image is already in Artifact Registry"; \
	else \
		gcloud builds submit stylist --tag "$$image" --project "$$project" --quiet; \
	fi

apply:
	$(TF) apply -input=false -auto-approve

web:
	printf 'window.OUTFIT_CONFIG = {frontdoorUrl: %s, stylistUrl: %s, demoKey: %s};\n' \
		"$$($(TF) output -json frontdoor_url)" "$$($(TF) output -json stylist_url)" "$$($(TF) output -json demo_key)" > web/config.js
	printf '{"hosting": {"site": %s, "public": "web", "ignore": ["**/.*"]}}\n' "$$($(TF) output -json hosting_site_id)" > firebase.json
	firebase deploy --only hosting --non-interactive --project "$$($(call tfval,var.gcp_project))"
	@echo "Open $$($(TF) output -raw hosting_url)"

down: infra/terraform.tfvars init
	$(TF) destroy -input=false -auto-approve
	rm -f web/config.js firebase.json

warm sleep:
	@curl -sS -X POST -w ' %{http_code}\n' -H "x-admin-key: $$($(TF) output -raw admin_key)" "$$($(TF) output -raw frontdoor_url)/$@"

status:
	@curl -sS -w ' %{http_code}\n' -H "x-demo-key: $$($(TF) output -raw demo_key)" "$$($(TF) output -raw frontdoor_url)/status"

plan: infra/terraform.tfvars init
	$(TF) plan -input=false

plan-offline:
	infra/plan-offline.sh

fmt:
	$(TF) fmt -recursive

validate:
	$(TF) fmt -check -recursive
	$(TF) init -input=false -backend=false
	$(TF) validate
