variable "region" {
  description = "Região da AWS"
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Prefixo dos recursos do projeto"
  type        = string
  default     = "data-lake"
}

variable "glue_role_name" {
  description = "Nome da role IAM já criada pelo ambiente AWS Academy (não tenta criar nem alterar políticas)"
  type        = string
  default     = "LabRole"
}

variable "bucket_suffix" {
  description = "Sufixo usado nos buckets Bronze, Silver e Gold"
  type        = string

  validation {
    condition     = length(var.bucket_suffix) > 0 && length(var.bucket_suffix) <= 52 && can(regex("^[a-z0-9]([a-z0-9-]*[a-z0-9])?$", var.bucket_suffix))
    error_message = "O sufixo deve ter até 52 caracteres, conter apenas letras minúsculas, números e hífens, e começar/terminar com letra ou número."
  }
}

variable "glue_bronze_silver_script_key" {
  description = "Chave S3 do script externo Bronze -> Silver"
  type        = string
  default     = "etl_unir_fontes.py"
}

variable "glue_silver_gold_script_key" {
  description = "Chave S3 do cálculo de chance de no-show Silver -> Gold"
  type        = string
  default     = "etl_calculo_no_show.py"
}

variable "glue_dashboard_bronze_silver_script_key" {
  description = "Chave S3 do ETL de snapshots SQL e meteorologia para Silver/dashboard"
  type        = string
  default     = "etl_dashboard_silver.py"
}

variable "glue_dashboard_silver_gold_script_key" {
  description = "Chave S3 do ETL que gera os JSONs da dashboard na Gold"
  type        = string
  default     = "etl_dashboard_gold.py"
}

variable "dashboard_schema_key" {
  description = "Chave S3 do JSON Schema publicado com os dados da dashboard"
  type        = string
  default     = "dashboard-data.schema.json"
}
