output "bronze_bucket_name" {
  description = "Nome do bucket Bronze"
  value       = data.aws_s3_bucket.s3_bronze.bucket
}

output "silver_bucket_name" {
  description = "Nome do bucket Silver"
  value       = data.aws_s3_bucket.s3_silver.bucket
}

output "gold_bucket_name" {
  description = "Nome do bucket Gold"
  value       = data.aws_s3_bucket.s3_gold.bucket
}

output "scripts_bucket_name" {
  description = "Nome do bucket existente de artefatos dos scripts"
  value       = local.code_artifact_bucket_name
}

output "glue_etl_job_name" {
  description = "Nome do Glue Job Bronze -> Silver"
  value       = aws_glue_job.glue_silver_job.name
}

output "glue_gold_job_name" {
  description = "Nome do Glue Job de cálculo de no-show Silver -> Gold"
  value       = aws_glue_job.glue_gold_job.name
}

output "glue_dashboard_silver_job_name" {
  description = "Nome do Glue Job SQL + meteorologia -> Silver/dashboard"
  value       = aws_glue_job.glue_dashboard_silver_job.name
}

output "glue_dashboard_gold_job_name" {
  description = "Nome do Glue Job Silver/dashboard -> Gold/dashboard"
  value       = aws_glue_job.glue_dashboard_gold_job.name
}

output "glue_crawler_name" {
  description = "Nome do Glue Crawler da camada Silver"
  value       = aws_glue_crawler.glue_crawler.name
}

output "glue_crawler_gold_name" {
  description = "Nome do Glue Crawler da camada Gold"
  value       = aws_glue_crawler.glue_crawler_gold.name
}

output "glue_crawler_dashboard_silver_name" {
  description = "Nome do Glue Crawler da dashboard na Silver"
  value       = aws_glue_crawler.glue_crawler_dashboard.name
}

output "glue_crawler_dashboard_gold_name" {
  description = "Nome do Glue Crawler da dashboard na Gold"
  value       = aws_glue_crawler.glue_crawler_dashboard_gold.name
}

output "glue_catalog_database" {
  description = "Nome do banco no Glue Data Catalog"
  value       = aws_glue_catalog_database.glue_data_catalog.name
}

output "athena_workgroup" {
  description = "Nome do Workgroup do Athena"
  value       = aws_athena_workgroup.athena_sql.name
}
