# Terraform de buckets

Este módulo cria os buckets com prefixos fixos e um sufixo informado pelo
usuário. O mesmo sufixo é aplicado aos três nomes:

- `s3-bronze-<sufixo>`
- `s3-silver-<sufixo>`
- `s3-gold-<sufixo>`

Informe o sufixo ao aplicar:

```powershell
terraform init
terraform plan -var="bucket_suffix=q0vep5"
terraform apply -var="bucket_suffix=q0vep5"
terraform output
```

Escolha um sufixo globalmente disponível e composto apenas por letras
minúsculas, números e hífens. Use o mesmo valor `bucket_suffix` no Terraform
principal de Glue.

**Limitação da AWS Academy:** a conta deste projeto nega
`s3:GetBucketObjectLockConfiguration`. O provider AWS pode chamar essa API ao
ler um recurso `aws_s3_bucket`, mesmo sem Object Lock habilitado. Portanto, o
`apply` pode continuar falhando devido à política da conta, independentemente
do sufixo.
