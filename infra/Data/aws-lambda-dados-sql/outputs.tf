output "lambda_function_name" {
  description = "Nome da Lambda de ingestão"
  value       = aws_lambda_function.ingestao.function_name
}
