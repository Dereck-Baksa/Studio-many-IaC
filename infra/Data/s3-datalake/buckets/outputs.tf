output "bronze_bucket_name" {
  description = "Nome do bucket Bronze criado"
  value       = aws_s3_bucket.bronze.bucket
}

output "silver_bucket_name" {
  description = "Nome do bucket Silver criado"
  value       = aws_s3_bucket.silver.bucket
}

output "gold_bucket_name" {
  description = "Nome do bucket Gold criado"
  value       = aws_s3_bucket.gold.bucket
}
