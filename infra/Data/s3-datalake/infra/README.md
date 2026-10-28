# Data Lake: implantação e processamento

## Fluxo

Os dados ficam em três buckets (Bronze, Silver e Gold), com prefixos por fonte
e produto dentro de cada bucket. Todas as partições diárias usam o fuso
`America/Sao_Paulo`. A cada execução horária, o objeto do dia é sobrescrito; a
partição muda à meia-noite local, preservando os arquivos dos dias anteriores.

1. A Lambda de coleta consulta a API Studio Many e o Open-Meteo e atualiza no
   Bronze:
   - `studio-many-api/data=AAAA-MM-DD/agendamentos.json`
   - `clima/data=AAAA-MM-DD/previsao.json`
   - `studio-many-api/data=AAAA-MM-DD/_SUCCESS.json`, escrito por último para
     indicar que as duas respostas foram gravadas.
2. A Lambda SQL atualiza `sql-data/<tabela>/data=AAAA-MM-DD/<tabela>.json`.
   Agendamentos e itens incluem os 365 dias anteriores e até 30 dias futuros.
   `sql-data/data=AAAA-MM-DD/_SUCCESS.json` só é escrito depois das tabelas
   obrigatórias da dashboard, para evitar que a Silver leia uma coleta parcial.
3. O Glue `Bronze -> Silver` lê as fontes da Studio Many e do clima após
   validar o marcador Bronze. Atualiza
   `dados-no-show/data=AAAA-MM-DD/agendamentos.json` na Silver.
4. Após o job anterior concluir com sucesso, o Glue de dashboard Silver lê o
   marcador e os arquivos SQL do dia, combina as tabelas com os dados de
   `dados-no-show/` e atualiza
   `dashboard/data=AAAA-MM-DD/dashboard.json`.
5. Os dois jobs Gold são iniciados após os respectivos dados Silver estarem
   prontos:
   - No-show: `dados-no-show/data=AAAA-MM-DD/agendamentos.json`.
   - Dashboard: `dashboard/data=AAAA-MM-DD/dashboard-data.json` e o schema
     estático `dashboard/dashboard-data.schema.json`.

O EventBridge executa a Lambda Studio Many na hora cheia e a Lambda SQL cinco
minutos depois. Um trigger agendado inicia o primeiro Glue às 30 minutos; após
sucesso, triggers condicionais executam o cálculo de no-show e a Silver da
dashboard, e depois a Gold da dashboard. Isso dá tempo para as duas coletas
terminarem antes de os ETLs lerem o Bronze.

A chance (`chance`, em percentual) usa a fórmula existente em
`etl_calculo_no_show.py`:

```text
taxa_faltas = 1 - (concluídos / (concluídos + no_shows))
chance = (0,60 * taxa_faltas + 0,25 * fator_tempo + 0,15 * fator_chuva) * 100
fator_tempo = min(max(dias_ate_consulta, 0) / 30, 1)
fator_chuva = probabilidade_chuva / 100
```

Quando não há histórico (nenhum concluído nem falta), a taxa de comparecimento
é 50%, portanto a taxa de faltas também é 50%. O resultado é arredondado para
duas casas decimais. `qtd_agendamentos_nao_finalizados` não entra no histórico.
Na dashboard, o mapa de calor e a variação comparam os 90 dias anteriores aos
90 dias precedentes. As chances da lista `atRisk` usam a mesma função do ETL
existente e só exibem riscos médios (a partir de 40%) e altos (a partir de 70%).
Os totais históricos por cliente presentes na Silver meteorológica são usados
como entrada da função de chance; quando não existem, são calculados dos status
SQL dos últimos 180 dias. O heatmap conta agendamentos únicos cujo status indica
falta. O faturamento conta pagamentos com status pago/aprovado/recebido e é
alocado aos serviços proporcionalmente aos preços cadastrados (divisão igual
quando não há preços). A capacidade usa os horários de trabalho, desconta
bloqueios e durações dos atendimentos.

Os testes locais usam mocks e não acessam AWS:

```powershell
Set-Location ..\glue-jobs
python -m unittest tests.test_dashboard_jobs -v
```

## Separação entre Terraform e deploy de código

Este Terraform lê os três buckets criados pelo módulo `../buckets`, cria os
Glue Jobs, os triggers, os crawlers e o workgroup Athena. Para contas AWS
Academy, ele reutiliza a role existente `LabRole` por meio de `data` e não cria
nem altera IAM roles. As Lambdas são gerenciadas nos módulos
`infra/Data/aws-lambda-dados-no-show` e
`infra/Data/aws-lambda-dados-sql`. O bucket de artefatos
`code-artifact-bucket-studio-essencia` é preexistente e está fixado nos módulos
Terraform; ele não é criado nem recebe upload pelo Terraform. Os scripts Python,
o schema e os pacotes Lambda devem ser publicados nele por `deploy.sh`.

Prática recomendada para produção:

- Manter os scripts versionados no Git e executar validações/testes no CI.
- Usar GitHub Actions com OIDC para assumir uma role AWS de deploy, sem chaves
  AWS permanentes em secrets.
- Publicar os arquivos Glue no bucket de artefatos antes de executar os Jobs.
- Empacotar a Lambda em ZIP e usar `aws lambda update-function-code` no pipeline.
- Usar artefatos versionados por commit, restringir acesso ao bucket e manter
  logs de deploy. Terraform não deve ser usado para atualizar o código.

Antes do primeiro `terraform apply`, execute `deploy.sh` com Bash (Git Bash ou
WSL) para publicar os dois ZIPs iniciais, os scripts Glue e o schema. Aplique
`infra/Data/s3-datalake/infra` e use o output `bronze_bucket_name` ao aplicar
`infra/Data/aws-lambda-dados-no-show` e `infra/Data/aws-lambda-dados-sql`.
Configure `spring_api_base_url` no módulo no-show. No módulo SQL, informe
`db_host`, `db_name`, `db_user` e `db_password`; o segredo é sensível no Terraform,
mas continua armazenado no state, portanto use backend remoto criptografado e
nunca versione `tfvars` com a senha. Para MySQL privado, informe também
`vpc_subnet_ids` e `vpc_security_group_ids`, e assegure que a role Lambda possa
criar interfaces de rede e acessar o bucket Bronze. Após a criação, `deploy.sh`
atualiza o código das duas Lambdas sem `terraform apply`.

Como a conta AWS Academy nega `s3:GetBucketObjectLockConfiguration`, este
módulo não cria nem gerencia os buckets. Execute primeiro o módulo
`../buckets` com um sufixo escolhido por você. Os nomes são formados como
`s3-bronze-<sufixo>`, `s3-silver-<sufixo>` e `s3-gold-<sufixo>`. Informe o mesmo
valor em `bucket_suffix` neste módulo.
Os recursos Glue podem então referenciar os buckets por `data "aws_s3_bucket"`
sem executar a API bloqueada.

Antes do apply, confira `terraform state list`. Recursos já existentes na AWS
que não aparecem no state devem ser importados, não recriados nem apagados. No
diretório `infra/Data/s3-datalake/infra`, importe os três recursos indicados
pelos erros:

```powershell
$catalogId = aws sts get-caller-identity --query Account --output text
terraform import aws_glue_job.glue_dashboard_silver_job "data-lake-dashboard-bronze-silver"
terraform import aws_glue_catalog_database.glue_data_catalog "${catalogId}:glue_data_catalog"
terraform import aws_athena_workgroup.athena_sql "data-lake-athena-wg"
terraform plan
```

O import apenas associa os recursos existentes ao state. Revise o plano antes
de aplicar, pois ele pode propor atualizações de configuração. Se algum recurso
já estiver administrado por outro state Terraform, pare e migre o state em vez
de importar o mesmo recurso em dois lugares.

## Publicação de artefatos (PowerShell)

O bucket de artefatos é fixo: `code-artifact-bucket-studio-essencia`. Crie-o
antes do primeiro deploy (o nome precisa estar disponível globalmente na AWS)
e publique os scripts e o schema:

```powershell
aws s3 mb s3://code-artifact-bucket-studio-essencia --region us-east-1
aws s3 cp ..\glue-jobs\etl_unir_fontes.py "s3://code-artifact-bucket-studio-essencia/etl_unir_fontes.py"
aws s3 cp ..\glue-jobs\etl_calculo_no_show.py "s3://code-artifact-bucket-studio-essencia/etl_calculo_no_show.py"
aws s3 cp ..\glue-jobs\etl_dashboard_silver.py "s3://code-artifact-bucket-studio-essencia/etl_dashboard_silver.py"
aws s3 cp ..\glue-jobs\etl_dashboard_gold.py "s3://code-artifact-bucket-studio-essencia/etl_dashboard_gold.py"
aws s3 cp ..\dashboard-data.schema.json "s3://code-artifact-bucket-studio-essencia/dashboard-data.schema.json"
```

O job de dashboard Gold usa o schema na chave configurada por
`dashboard_schema_key`. Para publicar tudo, incluindo os dois ZIPs e PyMySQL,
execute `deploy.sh` com Bash (Git Bash ou WSL) a partir da pasta `s3-datalake`.

Escolha um sufixo e informe o mesmo valor nos dois módulos. Por exemplo:

```powershell
Set-Location ..\buckets
terraform init
terraform plan -var="bucket_suffix=q0vep5"
terraform apply -var="bucket_suffix=q0vep5"
terraform output

Set-Location ..\infra
$env:TF_VAR_bucket_suffix = "q0vep5"
terraform init
terraform plan
terraform apply
```

Depois, aplique os dois módulos Lambda com o nome do bucket Bronze obtido acima:

```powershell
Set-Location ..\..\aws-lambda-dados-no-show
$env:TF_VAR_bronze_bucket_name = "<nome-do-bucket-bronze>"
$env:TF_VAR_spring_api_base_url = "https://api.exemplo.com"
terraform init
terraform plan
terraform apply

Set-Location ..\aws-lambda-dados-sql
$env:TF_VAR_bronze_bucket_name = "<nome-do-bucket-bronze>"
$env:TF_VAR_db_host = "<host-mysql>"
$env:TF_VAR_db_name = "studiomanydb"
$env:TF_VAR_db_user = "<usuario-somente-leitura>"
# Configure TF_VAR_db_password por um secret manager/CI seguro, sem salvar em tfvars.
terraform init
terraform plan
terraform apply
```

As Lambdas são agendadas no minuto 0 (Studio Many) e no minuto 5 (SQL). O Glue
inicia no minuto 30 e encadeia as etapas seguintes após sucesso. Assim, os jobs
não precisam ser iniciados manualmente a cada hora. O agendamento usa UTC; as
partições e a data de execução usam `America/Sao_Paulo`.

Não há API Gateway configurado. A Lambda Studio Many também pode ser invocada
manualmente com um evento como `{"data":"AAAA-MM-DD"}`.

`spring_api_base_url` precisa ser acessível pela Lambda implantada. O endereço
local `host.docker.internal` não é acessível a partir da AWS; uma API privada
exigirá também configuração de rede/VPC apropriada.
