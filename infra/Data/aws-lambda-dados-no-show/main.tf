
provider "aws" {
  region = "us-east-1"
}

locals {
  code_artifact_bucket_name = "code-artifact-bucket-studio-essencia"
}

resource "aws_lambda_function" "ingestao" {
  function_name = "${var.project_name}-ingestao"
  role          = var.lambda_role_arn
  runtime       = "python3.12"
  handler       = "lambda_function.lambda_handler"
  timeout       = 60
  memory_size   = 256

  s3_bucket = local.code_artifact_bucket_name
  s3_key    = var.lambda_artifact_key

  environment {
    variables = {
      BRONZE_BUCKET       = var.bronze_bucket_name
      SPRING_API_BASE_URL = var.spring_api_base_url
      LATITUDE            = tostring(var.latitude)
      LONGITUDE           = tostring(var.longitude)
    }
  }

  lifecycle {
    ignore_changes = [
      s3_key,
      s3_object_version
    ]
  }
}

resource "aws_cloudwatch_event_rule" "ingestao_horaria" {
  name                = "${var.project_name}-hourly"
  description         = "Executa a coleta de no-show a cada hora"
  schedule_expression = "cron(0 * * * ? *)"
}

resource "aws_cloudwatch_event_target" "ingestao_horaria" {
  rule      = aws_cloudwatch_event_rule.ingestao_horaria.name
  target_id = "${var.project_name}-ingestao"
  arn       = aws_lambda_function.ingestao.arn
}

resource "aws_lambda_permission" "allow_eventbridge" {
  statement_id  = "AllowExecutionFromEventBridgeHourly"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ingestao.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.ingestao_horaria.arn
}
