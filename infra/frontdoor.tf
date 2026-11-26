data "archive_file" "frontdoor" {
  type        = "zip"
  source_dir  = "${path.module}/../frontdoor"
  output_path = "${path.module}/.build/frontdoor.zip"
  excludes    = ["__pycache__", "tests"]
}

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "frontdoor" {
  name               = "${var.name}-frontdoor"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_iam_role_policy_attachment" "frontdoor_logs" {
  role       = aws_iam_role.frontdoor.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

data "aws_iam_policy_document" "frontdoor" {
  count = var.enable_gpu ? 1 : 0

  statement {
    actions = ["sagemaker:InvokeEndpoint"]
    resources = [
      aws_sagemaker_endpoint.decider[0].arn,
      aws_sagemaker_inference_component.decider[0].arn,
    ]
  }
  statement {
    actions = [
      "sagemaker:DescribeInferenceComponent",
      "sagemaker:UpdateInferenceComponentRuntimeConfig",
    ]
    resources = [aws_sagemaker_inference_component.decider[0].arn]
  }
}

resource "aws_iam_role_policy" "frontdoor" {
  count  = var.enable_gpu ? 1 : 0
  role   = aws_iam_role.frontdoor.id
  policy = data.aws_iam_policy_document.frontdoor[0].json
}

resource "aws_cloudwatch_log_group" "frontdoor" {
  name              = "/aws/lambda/${var.name}-frontdoor"
  retention_in_days = var.log_retention_days
}

resource "aws_lambda_function" "frontdoor" {
  function_name                  = "${var.name}-frontdoor"
  role                           = aws_iam_role.frontdoor.arn
  runtime                        = "python3.13"
  architectures                  = ["arm64"]
  handler                        = "handler.handler"
  filename                       = data.archive_file.frontdoor.output_path
  source_code_hash               = data.archive_file.frontdoor.output_base64sha256
  memory_size                    = 256
  timeout                        = 70
  reserved_concurrent_executions = var.frontdoor_concurrency

  environment {
    variables = {
      DEMO_KEY            = local.demo_key
      ADMIN_KEY           = local.admin_key
      BACKEND             = var.enable_gpu ? "sagemaker" : "http"
      ENDPOINT_NAME       = var.enable_gpu ? aws_sagemaker_endpoint.decider[0].name : ""
      INFERENCE_COMPONENT = var.enable_gpu ? aws_sagemaker_inference_component.decider[0].name : ""
      DECIDER_URL         = var.decider_url
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.frontdoor,
    aws_iam_role_policy_attachment.frontdoor_logs,
  ]
}

resource "aws_lambda_function_url" "frontdoor" {
  function_name      = aws_lambda_function.frontdoor.function_name
  authorization_type = "NONE"

  cors {
    allow_origins = local.allowed_origins
    allow_methods = ["GET", "POST"]
    allow_headers = ["content-type", "x-demo-key", "x-admin-key"]
    max_age       = 300
  }
}

resource "aws_lambda_permission" "frontdoor_url" {
  statement_id           = "FunctionURLAllowPublicAccess"
  action                 = "lambda:InvokeFunctionUrl"
  function_name          = aws_lambda_function.frontdoor.function_name
  principal              = "*"
  function_url_auth_type = "NONE"
}

resource "aws_lambda_permission" "frontdoor_invoke" {
  statement_id             = "FunctionURLInvokeAllowPublicAccess"
  action                   = "lambda:InvokeFunction"
  function_name            = aws_lambda_function.frontdoor.function_name
  principal                = "*"
  invoked_via_function_url = true
}
