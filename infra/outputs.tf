output "frontdoor_url" {
  value = aws_lambda_function_url.frontdoor.function_url
}

output "stylist_url" {
  value = google_cloud_run_v2_service.stylist.uri
}

output "hosting_url" {
  value = google_firebase_hosting_site.web.default_url
}

output "hosting_site_id" {
  value = google_firebase_hosting_site.web.site_id
}

output "demo_key" {
  value     = local.demo_key
  sensitive = true
}

output "ecr_repo_url" {
  value = aws_ecr_repository.decider.repository_url
}

output "stylist_repo_url" {
  value = "${var.gcp_region}-docker.pkg.dev/${var.gcp_project}/${google_artifact_registry_repository.stylist.repository_id}"
}

output "endpoint_name" {
  value = one(aws_sagemaker_endpoint.decider[*].name)
}

output "inference_component_name" {
  value = one(aws_sagemaker_inference_component.decider[*].name)
}
