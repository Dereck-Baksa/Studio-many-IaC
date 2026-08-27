
provider "aws" {
  region = "us-east-1" 
}

resource "aws_security_group" "webserver_sg" {
  name        = "webserver-security-group"
  description = "Allow HTTP access via my IP address"

  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = [var.my_ip]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "webserver-security-group"
  }
}

resource "aws_instance" "webserver" {
  ami           = "ami-0cb5cf49019e79c51" # Amazon Linux 2023 kernel-6.18 us-east-1
  instance_type = var.instance_type
  vpc_security_group_ids = [aws_security_group.webserver_sg.id]

  user_data = <<-EOF
              #!/bin/bash
              dnf update -y
              dnf install -y httpd
              systemctl s
              tart httpd
              systemctl enable httpd
              echo "<html><body><h1>Hello World!</h1></body></html>" > /var/www/html/index.html
              EOF

  tags = {
    Name = "WebServer"
  }
}
