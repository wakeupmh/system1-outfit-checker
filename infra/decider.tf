resource "aws_ecr_repository" "decider" {
  name                 = "${var.name}-decider"
  force_delete         = true
  image_tag_mutability = "MUTABLE"
}

resource "aws_ecr_lifecycle_policy" "decider" {
  repository = aws_ecr_repository.decider.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last 3 images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 3
      }
      action = { type = "expire" }
    }]
  })
}

data "aws_iam_policy_document" "sagemaker_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["sagemaker.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "sagemaker" {
  count              = var.enable_gpu ? 1 : 0
  name               = "${var.name}-sagemaker"
  assume_role_policy = data.aws_iam_policy_document.sagemaker_assume.json
}

data "aws_iam_policy_document" "sagemaker" {
  statement {
    actions   = ["ecr:GetAuthorizationToken", "cloudwatch:PutMetricData"]
    resources = ["*"]
  }
  statement {
    actions   = ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer", "ecr:BatchCheckLayerAvailability"]
    resources = [aws_ecr_repository.decider.arn]
  }
  statement {
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
      "logs:DescribeLogStreams",
    ]
    resources = ["arn:aws:logs:*:*:log-group:/aws/sagemaker/*"]
  }
}

resource "aws_iam_role_policy" "sagemaker" {
  count  = var.enable_gpu ? 1 : 0
  role   = aws_iam_role.sagemaker[0].id
  policy = data.aws_iam_policy_document.sagemaker.json
}

resource "aws_sagemaker_endpoint_configuration" "decider" {
  count              = var.enable_gpu ? 1 : 0
  name_prefix        = "${var.name}-decider-"
  execution_role_arn = aws_iam_role.sagemaker[0].arn

  production_variants {
    variant_name           = "AllTraffic"
    instance_type          = var.instance_type
    initial_instance_count = 1

    managed_instance_scaling {
      status             = "ENABLED"
      min_instance_count = 0
      max_instance_count = 1
    }

    routing_config {
      routing_strategy = "LEAST_OUTSTANDING_REQUESTS"
    }
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_sagemaker_endpoint" "decider" {
  count                = var.enable_gpu ? 1 : 0
  name                 = "${var.name}-decider"
  endpoint_config_name = aws_sagemaker_endpoint_configuration.decider[0].name
}

resource "aws_sagemaker_inference_component" "decider" {
  count         = var.enable_gpu ? 1 : 0
  name          = "${var.name}-decider"
  endpoint_name = aws_sagemaker_endpoint.decider[0].name
  variant_name  = "AllTraffic"

  specification {
    container {
      image = "${aws_ecr_repository.decider.repository_url}:${var.decider_image_tag}"
      environment = {
        DECIDER_MODEL = var.decider_model
      }
    }

    compute_resource_requirements {
      number_of_accelerator_devices_required = 1
      min_memory_required_in_mb              = var.decider_memory_mb
    }

    startup_parameters {
      container_startup_health_check_timeout_in_seconds = 900
      model_data_download_timeout_in_seconds            = 900
    }
  }

  runtime_config {
    copy_count = 1
  }

  lifecycle {
    ignore_changes = [runtime_config[0].copy_count]
  }

  depends_on = [aws_iam_role_policy.sagemaker]
}

resource "aws_appautoscaling_target" "decider" {
  count              = var.enable_gpu ? 1 : 0
  service_namespace  = "sagemaker"
  resource_id        = "inference-component/${aws_sagemaker_inference_component.decider[0].name}"
  scalable_dimension = "sagemaker:inference-component:DesiredCopyCount"
  min_capacity       = 0
  max_capacity       = 1
}

resource "aws_appautoscaling_policy" "decider_scale_in" {
  count              = var.enable_gpu ? 1 : 0
  name               = "${var.name}-decider-tracking"
  policy_type        = "TargetTrackingScaling"
  service_namespace  = aws_appautoscaling_target.decider[0].service_namespace
  resource_id        = aws_appautoscaling_target.decider[0].resource_id
  scalable_dimension = aws_appautoscaling_target.decider[0].scalable_dimension

  target_tracking_scaling_policy_configuration {
    target_value       = 1
    scale_in_cooldown  = 300
    scale_out_cooldown = 300

    predefined_metric_specification {
      predefined_metric_type = "SageMakerInferenceComponentInvocationsPerCopy"
    }
  }
}

resource "aws_appautoscaling_policy" "decider_scale_out" {
  count              = var.enable_gpu ? 1 : 0
  name               = "${var.name}-decider-from-zero"
  policy_type        = "StepScaling"
  service_namespace  = aws_appautoscaling_target.decider[0].service_namespace
  resource_id        = aws_appautoscaling_target.decider[0].resource_id
  scalable_dimension = aws_appautoscaling_target.decider[0].scalable_dimension

  step_scaling_policy_configuration {
    adjustment_type         = "ChangeInCapacity"
    metric_aggregation_type = "Maximum"
    cooldown                = 60

    step_adjustment {
      metric_interval_lower_bound = 0
      scaling_adjustment          = 1
    }
  }
}

resource "aws_cloudwatch_metric_alarm" "decider_no_capacity" {
  count               = var.enable_gpu ? 1 : 0
  alarm_name          = "${var.name}-decider-no-capacity"
  alarm_description   = "Invocations failed because the inference component has no copy"
  namespace           = "AWS/SageMaker"
  metric_name         = "NoCapacityInvocationFailures"
  dimensions          = { InferenceComponentName = aws_sagemaker_inference_component.decider[0].name }
  statistic           = "Sum"
  period              = 60
  evaluation_periods  = 1
  datapoints_to_alarm = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_appautoscaling_policy.decider_scale_out[0].arn]
}
