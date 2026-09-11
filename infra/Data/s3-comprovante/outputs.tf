output "website_url" {
  description = "Website URL"
  value       = "http://${aws_instance.webserver.public_dns}"
}
