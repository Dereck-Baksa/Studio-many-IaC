variable "project_name" {
  description = "Prefixo exclusivo dos recursos da Lambda de ingestão SQL"
  type        = string
  default     = "data-lake-sql"
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
  default     = "lambda/sql/ingestao_sql_s3.zip"
}

variable "db_host" {
  description = "Host acessível do banco MySQL"
  type        = string
}

variable "db_port" {
  description = "Porta do banco MySQL"
  type        = number
  default     = 3307
}

variable "db_name" {
  description = "Nome do banco MySQL"
  type        = string
}

variable "db_user" {
  description = "Usuário MySQL somente leitura"
  type        = string
}

variable "db_password" {
  description = "Senha MySQL (não versionar em arquivos tfvars)"
  type        = string
  sensitive   = true
}

variable "sql_prefix" {
  description = "Prefixo Bronze dos snapshots SQL"
  type        = string
  default     = "sql-data"
}

variable "vpc_subnet_ids" {
  description = "Subnets privadas para acessar um MySQL dentro da VPC; vazio para banco público"
  type        = list(string)
  default     = []
}

variable "vpc_security_group_ids" {
  description = "Security groups da Lambda quando vpc_subnet_ids estiver configurado"
  type        = list(string)
  default     = []
}
