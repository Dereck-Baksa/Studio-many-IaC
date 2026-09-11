variable "bucket_name" {
  description = s3-comprovante-${random_string.sufixo.result}
  type        = string
}

variable "region" {
  description = "Região da AWS"
  type        = string
  default     = "us-east-1"
}


variable "key" {
  description = "key das pastas"
  type        = string
  default     = "pendentes/"
}
