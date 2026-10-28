# Exportação SQL para S3

O script `ingestao_sql_s3.py` exporta como JSON as tabelas de origem dos
indicadores de agenda, serviços, faturamento e disponibilidade da dashboard.
As linhas são lidas sem agregações ou joins; tabelas não relacionadas à
dashboard (como usuários e comprovantes) não são exportadas. A única coluna
removida dessas tabelas é `clientes.total_no_shows`, pois a ingestão de no-show
é calculada na camada de dashboard a partir dos status históricos. Para manter
os agendamentos futuros e o histórico necessário aos indicadores, as tabelas
`agendamento_itens` e `agendamentos` abrangem de 365 dias antes até 30 dias
depois do horário atual do MySQL. O limite inicial é incluído e o limite final,
excluído. As demais tabelas são exportadas sem filtro de data. Valores SQL como
datas e decimais são representados como texto no JSON para preservar sua
representação.

## Dependências

```powershell
python -m pip install boto3 PyMySQL
```

## Testes

Execute os testes automatizados na pasta `lambda-py`:

```powershell
python -m unittest discover -s tests -v
```

Os testes usam mocks para MySQL e S3; não conectam a serviços reais.

## Configuração e execução (PowerShell)

Defina as variáveis de conexão e o destino:

```powershell
$env:DB_HOST = "endereco-do-mysql"
$env:DB_PORT = "3307"
$env:DB_NAME = "studiomanydb"
$env:DB_USER = "usuario-somente-leitura"
$env:DB_PASSWORD = "senha"
$env:S3_BUCKET = "nome-do-bucket-bronze"
$env:S3_PREFIX = "sql-data"
$env:AWS_REGION = "us-east-1"
python .\lambda_function\ingestao_sql_s3.py
```

O SDK da AWS usa a cadeia padrão de credenciais (por exemplo, perfil AWS CLI ou
IAM role). A identidade AWS precisa de `s3:PutObject` no prefixo configurado; o
usuário do banco deve ter permissão somente de leitura nas tabelas necessárias.
Cada execução atualiza os mesmos arquivos do dia, por exemplo:
`sql-data/agendamentos/data=2026-10-26/agendamentos.json`. A coleta usa o fuso
`America/Sao_Paulo` e grava `_SUCCESS.json` somente depois de enviar todas as
tabelas obrigatórias. O job Silver usa esse marcador para não ler uma coleta
parcial. As tabelas `faturamentos` e `disponibilidades` são exportadas quando
existem; as demais tabelas requeridas pela dashboard são obrigatórias.

O Terraform agenda a Lambda SQL cinco minutos após a hora cheia, para que a
coleta termine antes dos Glue Jobs. A implantação da Lambda empacota
`PyMySQL` junto ao handler `ingestao_sql_s3.lambda_handler`.
