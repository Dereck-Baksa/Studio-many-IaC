variable "region" {
  description = "Região da AWS"
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Nome do projeto, usado como prefixo dos recursos"
  type        = string
  default     = "data-lake"
}

variable "bronze_bucket_name" {
  description = "Nome do bucket S3 bronze (dados brutos/logs)"
  type        = string
  default     = "s3-bronze"
}

variable "silver_bucket_name" {
  description = "Nome do bucket S3 silver (dados tratados)"
  type        = string
  default     = "s3-silver"
}

variable "gold_bucket_name" {
  description = "Nome do bucket S3 gold (dados agregados/prontos para consumo)"
  type        = string
  default     = "s3-gold"
}

variable "glue_job_glue_version" {
  description = "Versão do Glue usada pelo Job"
  type        = string
  default     = "4.0"
}

variable "glue_etl_script_path" {
  description = "Caminho LOCAL do script Python do Glue ETL Job (ex: ./scripts/glue_etl_job.py). Se vazio, cria um placeholder vazio."
  type        = string
  default     = ""
}

variable "glue_etl_script_key" {
  description = "Chave (path) do script dentro do bucket de scripts no S3"
  type        = string
  default     = "scripts/glue_etl_job.py"
}