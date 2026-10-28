variable "project_name" {
  description = "Prefixo exclusivo dos recursos da Lambda de análise de no-show"
  type        = string
  default     = "data-lake-no-show"
}

variable "bronze_bucket_name" {
  description = "Nome do bucket Bronze criado pelo módulo s3-datalake"
  type        = string
}

variable "lambda_role_arn" {
  description = "ARN da role existente usada pela Lambda"
  type        = string
  default     = "arn:aws:iam::674063328358:role/LabRole"
}

variable "lambda_artifact_key" {
  description = "Chave S3 do pacote ZIP inicial da Lambda"
  type        = string
  default     = "lambda/no-show/lambda_function.zip"
}

variable "spring_api_base_url" {
  description = "URL acessível pela Lambda para a API Spring, sem o caminho /analise"
  type        = string
}

variable "latitude" {
  description = "Latitude usada na consulta Open-Meteo"
  type        = number
  default     = -23.55
}

variable "longitude" {
  description = "Longitude usada na consulta Open-Meteo"
  type        = number
  default     = -46.63
}
