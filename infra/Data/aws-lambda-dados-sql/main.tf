
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
  handler       = "ingestao_sql_s3.lambda_handler"
  timeout       = 900
  memory_size   = 512

  s3_bucket = local.code_artifact_bucket_name
  s3_key    = var.lambda_artifact_key

  dynamic "vpc_config" {
    for_each = length(var.vpc_subnet_ids) > 0 ? [true] : []
    content {
      subnet_ids         = var.vpc_subnet_ids
      security_group_ids = var.vpc_security_group_ids
    }
  }

  environment {
    variables = {
      DB_HOST     = var.db_host
      DB_PORT     = tostring(var.db_port)
      DB_NAME     = var.db_name
      DB_USER     = var.db_user
      DB_PASSWORD = var.db_password
      S3_BUCKET   = var.bronze_bucket_name
      S3_PREFIX   = var.sql_prefix
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
  description         = "Executa a ingestao SQL a cada hora"
  schedule_expression = "cron(5 * * * ? *)"
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
