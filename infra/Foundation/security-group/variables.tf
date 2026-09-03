variable "instance_type" {
  description = "WebServer EC2 instance type"
  type        = string
  default     = "t3.micro"
  validation {
    condition     = contains(["t3.micro", "t3.small", "t3.medium"], var.instance_type)
    error_message = "Tipo da instancia deve ser t3.micro, t3.small ou t3.medium."
  }
}

variable "my_ip" {
  description = "IP address formato em CIDR (e.g. 203.0.113.1/32)."
  type        = string
  default     = "0.0.0.0/0"
  validation {
    condition     = can(regex("^(\\d{1,3}\\.){3}\\d{1,3}\\/\\d{1,2}$", var.my_ip))
    error_message = "Deve ser um IP CIDR válido na forma de x.x.x.x/x."
  }
}
