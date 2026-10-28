locals {
  code_artifact_bucket_name = "code-artifact-bucket-studio-essencia"
  bronze_bucket_name        = "s3-bronze-${var.bucket_suffix}"
  silver_bucket_name        = "s3-silver-${var.bucket_suffix}"
  gold_bucket_name          = "s3-gold-${var.bucket_suffix}"
}

data "aws_s3_bucket" "s3_bronze" {
  bucket = local.bronze_bucket_name
}

resource "aws_s3_object" "logs" {
  bucket  = data.aws_s3_bucket.s3_bronze.id
  key     = "logs/"
  content = ""
}

data "aws_s3_bucket" "s3_silver" {
  bucket = local.silver_bucket_name
}

resource "aws_s3_object" "silver_prefix" {
  bucket  = data.aws_s3_bucket.s3_silver.id
  key     = "dados-no-show/"
  content = ""
}

resource "aws_s3_object" "silver_dashboard_prefix" {
  bucket  = data.aws_s3_bucket.s3_silver.id
  key     = "dashboard/"
  content = ""
}

data "aws_s3_bucket" "s3_gold" {
  bucket = local.gold_bucket_name
}

resource "aws_s3_object" "gold_prefix" {
  bucket  = data.aws_s3_bucket.s3_gold.id
  key     = "dados-no-show/"
  content = ""
}

resource "aws_s3_object" "gold_dashboard_prefix" {
  bucket  = data.aws_s3_bucket.s3_gold.id
  key     = "dashboard/"
  content = ""
}

data "aws_iam_role" "glue_role" {
  name = var.glue_role_name
}

resource "aws_glue_job" "glue_silver_job" {
  name     = "glue-etl-job"
  role_arn = data.aws_iam_role.glue_role.arn

  command {
    name            = "pythonshell"
    script_location = "s3://${local.code_artifact_bucket_name}/${var.glue_bronze_silver_script_key}"
    python_version  = "3.9"
  }

  default_arguments = {
    "--bronze-bucket" = data.aws_s3_bucket.s3_bronze.bucket
    "--silver-bucket" = data.aws_s3_bucket.s3_silver.bucket
  }

  depends_on = [data.aws_iam_role.glue_role]
}

resource "aws_glue_job" "glue_gold_job" {
  name     = "${var.project_name}-etl-calculo-no-show"
  role_arn = data.aws_iam_role.glue_role.arn

  command {
    name            = "pythonshell"
    script_location = "s3://${local.code_artifact_bucket_name}/${var.glue_silver_gold_script_key}"
    python_version  = "3.9"
  }

  default_arguments = {
    "--silver-bucket" = data.aws_s3_bucket.s3_silver.bucket
    "--gold-bucket"   = data.aws_s3_bucket.s3_gold.bucket
  }

  depends_on = [data.aws_iam_role.glue_role]
}

resource "aws_glue_job" "glue_dashboard_silver_job" {
  name     = "${var.project_name}-dashboard-bronze-silver"
  role_arn = data.aws_iam_role.glue_role.arn

  command {
    name            = "pythonshell"
    script_location = "s3://${local.code_artifact_bucket_name}/${var.glue_dashboard_bronze_silver_script_key}"
    python_version  = "3.9"
  }

  default_arguments = {
    "--bronze-bucket"  = data.aws_s3_bucket.s3_bronze.bucket
    "--silver-bucket"  = data.aws_s3_bucket.s3_silver.bucket
    "--sql-prefix"     = "sql-data"
    "--weather-prefix" = "dados-no-show/"
  }

  depends_on = [data.aws_iam_role.glue_role]
}

resource "aws_glue_trigger" "silver_hourly" {
  name     = "${var.project_name}-silver-hourly"
  type     = "SCHEDULED"
  schedule = "cron(30 * * * ? *)"

  actions {
    job_name = aws_glue_job.glue_silver_job.name
  }
}

resource "aws_glue_trigger" "silver_follow_up" {
  name              = "${var.project_name}-silver-follow-up"
  type              = "CONDITIONAL"
  start_on_creation = true

  predicate {
    conditions {
      job_name = aws_glue_job.glue_silver_job.name
      state    = "SUCCEEDED"
    }
  }

  actions {
    job_name = aws_glue_job.glue_gold_job.name
  }

  actions {
    job_name = aws_glue_job.glue_dashboard_silver_job.name
  }
}

resource "aws_glue_trigger" "dashboard_gold_after_silver" {
  name              = "${var.project_name}-dashboard-gold-after-silver"
  type              = "CONDITIONAL"
  start_on_creation = true

  predicate {
    conditions {
      job_name = aws_glue_job.glue_dashboard_silver_job.name
      state    = "SUCCEEDED"
    }
  }

  actions {
    job_name = aws_glue_job.glue_dashboard_gold_job.name
  }
}

resource "aws_glue_job" "glue_dashboard_gold_job" {
  name     = "${var.project_name}-dashboard-silver-gold"
  role_arn = data.aws_iam_role.glue_role.arn

  command {
    name            = "pythonshell"
    script_location = "s3://${local.code_artifact_bucket_name}/${var.glue_dashboard_silver_gold_script_key}"
    python_version  = "3.9"
  }

  default_arguments = {
    "--silver-bucket"  = data.aws_s3_bucket.s3_silver.bucket
    "--gold-bucket"    = data.aws_s3_bucket.s3_gold.bucket
    "--schema-s3-uri"  = "s3://${local.code_artifact_bucket_name}/${var.dashboard_schema_key}"
    "--extra-py-files" = "s3://${local.code_artifact_bucket_name}/${var.glue_silver_gold_script_key}"
  }

  depends_on = [data.aws_iam_role.glue_role]
}

resource "aws_glue_catalog_database" "glue_data_catalog" {
  name = "glue_data_catalog"
}

resource "aws_glue_crawler" "glue_crawler" {
  name          = "glue-crawler"
  role          = data.aws_iam_role.glue_role.arn
  database_name = aws_glue_catalog_database.glue_data_catalog.name

  s3_target {
    path = "s3://${data.aws_s3_bucket.s3_silver.bucket}/dados-no-show/"
  }

  schema_change_policy {
    update_behavior = "UPDATE_IN_DATABASE"
    delete_behavior = "LOG"
  }

  depends_on = [data.aws_iam_role.glue_role]
}

resource "aws_glue_crawler" "glue_crawler_dashboard" {
  name          = "glue-crawler-dashboard-silver"
  role          = data.aws_iam_role.glue_role.arn
  database_name = aws_glue_catalog_database.glue_data_catalog.name

  s3_target {
    path = "s3://${data.aws_s3_bucket.s3_silver.bucket}/dashboard/"
  }

  schema_change_policy {
    update_behavior = "UPDATE_IN_DATABASE"
    delete_behavior = "LOG"
  }

  depends_on = [data.aws_iam_role.glue_role]
}

resource "aws_glue_crawler" "glue_crawler_gold" {
  name          = "glue-crawler-gold"
  role          = data.aws_iam_role.glue_role.arn
  database_name = aws_glue_catalog_database.glue_data_catalog.name

  s3_target {
    path = "s3://${data.aws_s3_bucket.s3_gold.bucket}/dados-no-show/"
  }

  schema_change_policy {
    update_behavior = "UPDATE_IN_DATABASE"
    delete_behavior = "LOG"
  }

  depends_on = [data.aws_iam_role.glue_role]
}

resource "aws_glue_crawler" "glue_crawler_dashboard_gold" {
  name          = "glue-crawler-dashboard-gold"
  role          = data.aws_iam_role.glue_role.arn
  database_name = aws_glue_catalog_database.glue_data_catalog.name

  s3_target {
    path = "s3://${data.aws_s3_bucket.s3_gold.bucket}/dashboard/"
  }

  schema_change_policy {
    update_behavior = "UPDATE_IN_DATABASE"
    delete_behavior = "LOG"
  }

  depends_on = [data.aws_iam_role.glue_role]
}

resource "aws_athena_workgroup" "athena_sql" {
  name = "${var.project_name}-athena-wg"

  configuration {
    result_configuration {
      output_location = "s3://${data.aws_s3_bucket.s3_gold.bucket}/athena-results/"
    }
  }
}
