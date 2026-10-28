variable "region" {
  description = "Região da AWS onde os buckets serão criados"
  type        = string
  default     = "us-east-1"
}

variable "bucket_suffix" {
  description = "Sufixo digitado pelo usuário e compartilhado pelos três buckets"
  type        = string

  validation {
    condition     = length(var.bucket_suffix) > 0 && length(var.bucket_suffix) <= 52 && can(regex("^[a-z0-9]([a-z0-9-]*[a-z0-9])?$", var.bucket_suffix))
    error_message = "O sufixo deve ter até 52 caracteres, conter apenas letras minúsculas, números e hífens, e começar/terminar com letra ou número."
  }
}
