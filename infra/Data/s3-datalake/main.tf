
resource "random_string" "sufixo" {
  length  = 6
  special = false
  upper   = false
}

 
resource "aws_s3_bucket" "s3_bronze" {
  bucket        = "${var.bronze_bucket_name}-${random_string.sufixo.result}"
  force_destroy = true

  tags = {
    Name    = "s3-bronze"
    Project = var.project_name
  }
}

resource "aws_s3_object" "logs" {
  bucket = aws_s3_bucket.s3_bronze.id
  key    = "logs/"
  source = "/dev/null"
}


resource "aws_s3_bucket" "s3_silver" {
  bucket        = "${var.silver_bucket_name}-${random_string.sufixo.result}"
  force_destroy = true

  tags = {
    Name    = "s3-silver"
    Project = var.project_name
  }
}

resource "aws_s3_object" "silver_prefix" {
  bucket = aws_s3_bucket.s3_silver.id
  key    = "dados/"
  source = "/dev/null"
}

 
resource "aws_s3_bucket" "s3_gold" {
  bucket        = "${var.gold_bucket_name}-${random_string.sufixo.result}"
  force_destroy = true

  tags = {
    Name    = "s3-gold"
    Project = var.project_name
  }
}

resource "aws_s3_object" "gold_prefix" {
  bucket = aws_s3_bucket.s3_gold.id
  key    = "dados/"
  source = "/dev/null"
}

resource "aws_s3_bucket" "s3_scripts" {
  bucket        = "s3-glue-scripts-${random_string.sufixo.result}"
  force_destroy = true

  tags = {
    Name    = "s3-glue-scripts"
    Project = var.project_name
  }
}


resource "aws_s3_object" "glue_etl_script" {
  bucket = aws_s3_bucket.s3_scripts.id
  key    = var.glue_etl_script_key
  source = var.glue_etl_script_path != "" ? var.glue_etl_script_path : "/dev/null"
  etag   = var.glue_etl_script_path != "" ? filemd5(var.glue_etl_script_path) : null
}


resource "aws_iam_role" "glue_role" {
  name = "${var.project_name}-glue-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "glue.amazonaws.com"
        }
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "glue_service_policy" {
  role       = aws_iam_role.glue_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSGlueServiceRole"
}

resource "aws_iam_role_policy" "glue_s3_access" {
  name = "${var.project_name}-glue-s3-access"
  role = aws_iam_role.glue_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:ListBucket",
          "s3:DeleteObject"
        ]
        Resource = [
          aws_s3_bucket.s3_bronze.arn,
          "${aws_s3_bucket.s3_bronze.arn}/*",
          aws_s3_bucket.s3_silver.arn,
          "${aws_s3_bucket.s3_silver.arn}/*",
          aws_s3_bucket.s3_gold.arn,
          "${aws_s3_bucket.s3_gold.arn}/*",
          aws_s3_bucket.s3_scripts.arn,
          "${aws_s3_bucket.s3_scripts.arn}/*"
        ]
      }
    ]
  })
}

#
resource "aws_glue_job" "glue_etl_job" {
  name         = "glue-etl-job"
  role_arn     = aws_iam_role.glue_role.arn
  glue_version = var.glue_job_glue_version

  command {
    name            = "glueetl"
    script_location = "s3://${aws_s3_bucket.s3_scripts.bucket}/${var.glue_etl_script_key}"
    python_version  = "3"
  }

  default_arguments = {
    "--input_path"  = "s3://${aws_s3_bucket.s3_bronze.bucket}/logs/"
    "--output_path" = "s3://${aws_s3_bucket.s3_silver.bucket}/dados/"
  }

  number_of_workers = 2
  worker_type       = "G.1X"

  depends_on = [aws_s3_object.glue_etl_script]
}

#  Glue Job (Silver -> Gold) 
resource "aws_glue_job" "glue_gold_job" {
  name         = "glue-gold-job"
  role_arn     = aws_iam_role.glue_role.arn
  glue_version = var.glue_job_glue_version

  command {
    name            = "glueetl"
    script_location = "s3://${aws_s3_bucket.s3_scripts.bucket}/${var.glue_etl_script_key}"
    python_version  = "3"
  }

  default_arguments = {
    "--input_path"  = "s3://${aws_s3_bucket.s3_silver.bucket}/dados/"
    "--output_path" = "s3://${aws_s3_bucket.s3_gold.bucket}/dados/"
  }

  number_of_workers = 2
  worker_type       = "G.1X"

  depends_on = [aws_s3_object.glue_etl_script]
}

#  Glue Data Catalog 
resource "aws_glue_catalog_database" "glue_data_catalog" {
  name = "glue_data_catalog"
}

#  Glue Crawler (Silver) 
resource "aws_glue_crawler" "glue_crawler" {
  name          = "glue-crawler"
  role          = aws_iam_role.glue_role.arn
  database_name = aws_glue_catalog_database.glue_data_catalog.name

  s3_target {
    path = "s3://${aws_s3_bucket.s3_silver.bucket}/dados/"
  }

  schema_change_policy {
    update_behavior = "UPDATE_IN_DATABASE"
    delete_behavior = "LOG"
  }

  depends_on = [aws_glue_job.glue_etl_job]
}

resource "aws_glue_crawler" "glue_crawler_gold" {
  name          = "glue-crawler-gold"
  role          = aws_iam_role.glue_role.arn
  database_name = aws_glue_catalog_database.glue_data_catalog.name

  s3_target {
    path = "s3://${aws_s3_bucket.s3_gold.bucket}/dados/"
  }

  schema_change_policy {
    update_behavior = "UPDATE_IN_DATABASE"
    delete_behavior = "LOG"
  }

  depends_on = [aws_glue_job.glue_gold_job]
}

resource "aws_athena_workgroup" "athena_sql" {
  name = "${var.project_name}-athena-wg"

  configuration {
    result_configuration {
      output_location = "s3://${aws_s3_bucket.s3_gold.bucket}/athena-results/"
    }
  }
}