variable "name" {
  description = "Prefix for every resource name."
  type        = string
  default     = "outfit"
}

variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "gcp_project" {
  description = "GCP project id. Needs a linked billing account for Cloud Run and Cloud Build."
  type        = string
}

variable "gcp_region" {
  type    = string
  default = "us-central1"
}

variable "gemini_api_key" {
  description = "Gemini API key from AI Studio."
  type        = string
  sensitive   = true
}

variable "demo_key" {
  description = "Value of the x-demo-key header. Generated when null."
  type        = string
  default     = null
  sensitive   = true
}

variable "enable_gpu" {
  description = "Create the SageMaker endpoint. false brings up only the front door and the Google side."
  type        = bool
  default     = true
}

variable "decider_url" {
  description = "Decider base URL the front door calls when enable_gpu is false."
  type        = string
  default     = ""
}

variable "decider_image_tag" {
  description = "Tag of the decider image in the ECR repo. make up sets it."
  type        = string
  default     = "latest"
}

variable "decider_model" {
  type    = string
  default = "StrandsAgents/strands-decider-E2B-gemma4-v2-2611"
}

variable "instance_type" {
  type    = string
  default = "ml.g6.xlarge"
}

variable "decider_memory_mb" {
  description = "Host RAM reserved for one decider copy. ml.g6.xlarge has 16 GiB."
  type        = number
  default     = 8192
}

variable "frontdoor_concurrency" {
  description = "Reserved concurrency for the front door Lambda. -1 removes the cap (needed on accounts whose concurrency limit is 10)."
  type        = number
  default     = 4
}

variable "stylist_image" {
  description = "Full stylist image URI. make up sets it; the default is Google's sample so a plan works before the first build."
  type        = string
  default     = "us-docker.pkg.dev/cloudrun/container/hello"
}

variable "stylist_model" {
  type    = string
  default = "gemini-flash-latest"
}

variable "hosting_site_id" {
  description = "Firebase Hosting site id, globally unique. Defaults to <name>-<random hex>, new after each make down."
  type        = string
  default     = null
}

variable "log_retention_days" {
  type    = number
  default = 7
}
