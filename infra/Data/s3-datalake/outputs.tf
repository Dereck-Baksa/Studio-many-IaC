
output "bronze_bucket_name" {
  description = "Nome do bucket s3-bronze"
  value       = aws_s3_bucket.s3_bronze.bucket
}

output "silver_bucket_name" {
  description = "Nome do bucket s3-silver"
  value       = aws_s3_bucket.s3_silver.bucket
}

output "gold_bucket_name" {
  description = "Nome do bucket s3-gold"
  value       = aws_s3_bucket.s3_gold.bucket
}

output "scripts_bucket_name" {
  description = "Nome do bucket onde o script do Glue é armazenado"
  value       = aws_s3_bucket.s3_scripts.bucket
}

output "glue_etl_job_name" {
  description = "Nome do Glue ETL Job (Bronze -> Silver)"
  value       = aws_glue_job.glue_etl_job.name
}

output "glue_gold_job_name" {
  description = "Nome do Glue Job (Silver -> Gold)"
  value       = aws_glue_job.glue_gold_job.name
}

output "glue_crawler_name" {
  description = "Nome do Glue Crawler (Silver)"
  value       = aws_glue_crawler.glue_crawler.name
}

output "glue_crawler_gold_name" {
  description = "Nome do Glue Crawler (Gold)"
  value       = aws_glue_crawler.glue_crawler_gold.name
}

output "glue_catalog_database" {
  description = "Nome do banco no Glue Data Catalog"
  value       = aws_glue_catalog_database.glue_data_catalog.name
}

output "athena_workgroup" {
  description = "Nome do Workgroup do Athena"
  value       = aws_athena_workgroup.athena_sql.name
}