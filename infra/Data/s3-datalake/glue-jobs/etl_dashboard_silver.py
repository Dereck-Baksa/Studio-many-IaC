import argparse
import json
import os
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import boto3
from botocore.exceptions import BotoCoreError, ClientError


TABLES = {
    "agendamento_itens",
    "agendamentos",
    "bloqueios",
    "categoria_servicos",
    "clientes",
    "dias_de_trabalho",
    "pagamentos",
    "profissionais",
    "servicos",
    "servicos_profissionais",
    "status_agendamentos",
    "status_pagamentos",
    "tipo_pagamentos",
}
TIMEZONE_NAME = "America/Sao_Paulo"
SUCCESS_PATTERN = re.compile(
    r"^.+/data=(\d{4}-\d{2}-\d{2})/_SUCCESS\.json$"
)


def data_local():
    return datetime.now(ZoneInfo(TIMEZONE_NAME)).strftime("%Y-%m-%d")


def criar_cliente_s3():
    configuracao = {"region_name": os.getenv("AWS_REGION", "us-east-1")}
    endpoint_url = os.getenv("S3_ENDPOINT_URL")
    if endpoint_url:
        configuracao.update(
            {
                "endpoint_url": endpoint_url,
                "aws_access_key_id": os.getenv("AWS_ACCESS_KEY_ID", "test"),
                "aws_secret_access_key": os.getenv("AWS_SECRET_ACCESS_KEY", "test"),
            }
        )
    return boto3.client("s3", **configuracao)


def ler_json_s3(cliente_s3, bucket, chave):
    resposta = cliente_s3.get_object(Bucket=bucket, Key=chave)
    with resposta["Body"] as corpo:
        return json.loads(corpo.read().decode("utf-8"))


def listar_objetos(cliente_s3, bucket, prefixo):
    paginator = cliente_s3.get_paginator("list_objects_v2")
    objetos = []
    for pagina in paginator.paginate(Bucket=bucket, Prefix=prefixo):
        objetos.extend(
            objeto
            for objeto in pagina.get("Contents", [])
            if objeto["Key"].lower().endswith(".json")
        )
    return objetos


def carregar_snapshot_sql(cliente_s3, bucket, prefixo, data=None):
    prefixo = prefixo.strip("/")
    if data:
        datetime.strptime(data, "%Y-%m-%d")
        snapshot = data
    else:
        snapshots = set()
        for objeto in listar_objetos(cliente_s3, bucket, f"{prefixo}/"):
            correspondencia = SUCCESS_PATTERN.fullmatch(objeto["Key"])
            if correspondencia:
                snapshots.add(correspondencia.group(1))
        if not snapshots:
            raise RuntimeError(
                f"Nenhum snapshot SQL concluído em s3://{bucket}/{prefixo}/"
            )
        snapshot = max(snapshots)

    chave_manifesto = (
        f"{prefixo}/data={snapshot}/_SUCCESS.json"
    )
    manifesto = ler_json_s3(cliente_s3, bucket, chave_manifesto)
    if not isinstance(manifesto, dict) or manifesto.get("data") != snapshot:
        raise ValueError(f"Manifesto SQL inválido: {chave_manifesto}")
    tabelas_manifesto = manifesto.get("tabelas")
    if not isinstance(tabelas_manifesto, list) or not TABLES.issubset(
        set(tabelas_manifesto)
    ):
        raise RuntimeError(
            f"Snapshot SQL incompleto no manifesto {chave_manifesto}"
        )

    return {
        tabela: ler_json_s3(
            cliente_s3,
            bucket,
            f"{prefixo}/{tabela}/data={snapshot}/{tabela}.json",
        )
        for tabela in TABLES
    }, snapshot


def _id(valor, campo):
    if valor is None:
        raise ValueError(f"Campo obrigatório ausente nos dados SQL: {campo}")
    try:
        return int(valor)
    except (TypeError, ValueError) as erro:
        raise ValueError(f"Identificador SQL inválido em {campo}: {valor}") from erro


def _status_por_id(linhas, campo_nome):
    resultado = {}
    for linha in linhas:
        resultado[_id(linha.get("id"), f"{campo_nome}.id")] = str(
            linha.get(campo_nome) or ""
        ).strip()
    return resultado


def _data_hora(valor, campo):
    if not valor:
        raise ValueError(f"Data/hora ausente em {campo}")
    try:
        if isinstance(valor, datetime):
            return valor.isoformat(timespec="seconds")
        return datetime.fromisoformat(str(valor).replace("Z", "+00:00")).isoformat(
            timespec="seconds"
        )
    except ValueError as erro:
        raise ValueError(f"Data/hora inválida em {campo}: {valor}") from erro


def _por_chave(linhas, campo):
    resultado = {}
    for linha in linhas:
        chave = linha.get(campo)
        if chave is not None:
            resultado.setdefault(str(chave), []).append(linha)
    return resultado


def carregar_dados_meteorologicos(cliente_s3, bucket, prefixo):
    por_agendamento = {}
    objetos = sorted(
        listar_objetos(cliente_s3, bucket, prefixo),
        key=lambda item: item.get("LastModified", datetime.min.replace(tzinfo=timezone.utc)),
    )
    for objeto in objetos:
        registros = ler_json_s3(cliente_s3, bucket, objeto["Key"])
        if not isinstance(registros, list):
            raise ValueError(
                f"JSON meteorológico deve conter uma lista: {objeto['Key']}"
            )
        for registro in registros:
            if not isinstance(registro, dict):
                raise ValueError(
                    f"Registro meteorológico inválido em {objeto['Key']}"
                )
            identificador = registro.get("id_agendamento")
            if identificador is not None:
                por_agendamento[str(identificador)] = registro
    if not por_agendamento:
        raise RuntimeError(
            f"Nenhum registro meteorológico encontrado em s3://{bucket}/{prefixo}"
        )
    return por_agendamento


def unir_dados_sql_e_meteorologia(tabelas, meteorologia):
    status_agendamentos = _status_por_id(
        tabelas["status_agendamentos"], "estado"
    )
    status_pagamentos = _status_por_id(
        tabelas["status_pagamentos"], "estado"
    )
    clientes = {str(item["id"]): item for item in tabelas["clientes"]}
    profissionais = {str(item["id"]): item for item in tabelas["profissionais"]}
    servicos = {str(item["id"]): item for item in tabelas["servicos"]}

    itens_por_agendamento = _por_chave(
        tabelas["agendamento_itens"], "agendamento_id"
    )
    pagamentos_por_agendamento = _por_chave(
        tabelas["pagamentos"], "agendamento_id"
    )
    saida = []

    for agendamento in tabelas["agendamentos"]:
        agendamento_id = _id(agendamento.get("id"), "agendamentos.id")
        cliente_id = agendamento.get("cliente_id")
        cliente = clientes.get(str(cliente_id), {})
        itens = itens_por_agendamento.get(str(agendamento_id), [])
        if not itens:
            continue

        registros_itens = []
        probabilidade_chuva = None
        weather = meteorologia.get(str(agendamento_id))
        if weather is not None:
            probabilidade_chuva = weather.get("probabilidade_chuva")

        for item in itens:
            servico = servicos.get(str(item.get("servico_id")), {})
            profissional = profissionais.get(str(item.get("profissional_id")), {})
            registros_itens.append(
                {
                    "itemId": item.get("id"),
                    "serviceId": item.get("servico_id"),
                    "service": servico.get("nome") or "Serviço",
                    "servicePrice": servico.get("preco"),
                    "durationMinutes": servico.get("duracao_minutos"),
                    "professionalId": item.get("profissional_id"),
                    "professionalName": profissional.get("nome") or "Profissional",
                    "startAt": _data_hora(
                        item.get("inicio_atendimento"),
                        "agendamento_itens.inicio_atendimento",
                    ),
                    "endAt": (
                        _data_hora(
                            item["fim_atendimento"],
                            "agendamento_itens.fim_atendimento",
                        )
                        if item.get("fim_atendimento")
                        else None
                    ),
                }
            )

        pagamentos = []
        for pagamento in pagamentos_por_agendamento.get(str(agendamento_id), []):
            pagamentos.append(
                {
                    "value": pagamento.get("valor"),
                    "paidAt": (
                        _data_hora(pagamento["pago_em"], "pagamentos.pago_em")
                        if pagamento.get("pago_em")
                        else None
                    ),
                    "status": status_pagamentos.get(
                        int(pagamento["status_pagamento_id"]), ""
                    )
                    if pagamento.get("status_pagamento_id") is not None
                    else "",
                }
            )

        saida.append(
            {
                "id": agendamento_id,
                "clientId": cliente_id,
                "clientName": cliente.get("nome") or "",
                "createdAt": (
                    _data_hora(agendamento["criado_em"], "agendamentos.criado_em")
                    if agendamento.get("criado_em")
                    else None
                ),
                "status": status_agendamentos.get(
                    int(agendamento["status_agendamento_id"]), ""
                )
                if agendamento.get("status_agendamento_id") is not None
                else "",
                "finalPrice": agendamento.get("preco_final"),
                "weatherProbability": probabilidade_chuva,
                "historyNoShows": (
                    weather.get("qtd_no_shows") if weather is not None else None
                ),
                "historyUnfinished": (
                    weather.get("qtd_agendamentos_nao_finalizados")
                    if weather is not None
                    else None
                ),
                "historyCompleted": (
                    weather.get("qtd_agendamentos_concluidos")
                    if weather is not None
                    else None
                ),
                "items": registros_itens,
                "payments": pagamentos,
            }
        )

    return {
        "professionals": [
            {"id": item.get("id"), "name": item.get("nome") or ""}
            for item in tabelas["profissionais"]
        ],
        "appointments": saida,
        "workingDays": tabelas["dias_de_trabalho"],
        "blocks": tabelas["bloqueios"],
    }


def processar(
    bucket_bronze,
    bucket_silver,
    prefixo_sql,
    prefixo_meteorologia,
    data=None,
):
    cliente_s3 = criar_cliente_s3()
    tabelas, snapshot = carregar_snapshot_sql(
        cliente_s3, bucket_bronze, prefixo_sql, data
    )
    meteorologia = carregar_dados_meteorologicos(
        cliente_s3, bucket_silver, prefixo_meteorologia
    )
    dados = unir_dados_sql_e_meteorologia(tabelas, meteorologia)
    gerado_em = datetime.now(ZoneInfo(TIMEZONE_NAME))
    data_particao = snapshot
    dados["snapshotSql"] = snapshot
    dados["generatedAt"] = gerado_em.isoformat(timespec="seconds")
    dados["referenceDate"] = data_particao
    chave = (
        f"dashboard/data={data_particao}/"
        "dashboard.json"
    )
    cliente_s3.put_object(
        Bucket=bucket_silver,
        Key=chave,
        Body=json.dumps(dados, ensure_ascii=False, default=str).encode("utf-8"),
        ContentType="application/json; charset=utf-8",
    )
    return chave


def main():
    parser = argparse.ArgumentParser(
        description="Combina snapshots SQL e meteorologia na Silver/dashboard."
    )
    parser.add_argument("--bronze-bucket", default=os.getenv("BRONZE_BUCKET"))
    parser.add_argument("--silver-bucket", default=os.getenv("SILVER_BUCKET"))
    parser.add_argument(
        "--sql-prefix", default=os.getenv("SQL_RAW_PREFIX", "sql-data")
    )
    parser.add_argument(
        "--weather-prefix",
        default=os.getenv("WEATHER_PREFIX", "dados-no-show/"),
    )
    parser.add_argument("--date", default=data_local())
    parser.add_argument("--JOB_NAME")
    parser.add_argument("--JOB_ID")
    parser.add_argument("--JOB_RUN_ID")
    parser.add_argument("--TempDir")
    parser.add_argument("--job-language")
    parser.add_argument("--job-bookmark-option")
    parser.add_argument("--enable-metrics")
    parser.add_argument("--enable-continuous-cloudwatch-log")
    parser.add_argument("--enable-glue-datacatalog")
    parser.add_argument("--enable-job-insights")
    parser.add_argument("--extra-py-files")
    args = parser.parse_args()
    if not args.bronze_bucket or not args.silver_bucket:
        parser.error("--bronze-bucket e --silver-bucket são obrigatórios")

    try:
        chave = processar(
            args.bronze_bucket,
            args.silver_bucket,
            args.sql_prefix,
            args.weather_prefix,
            args.date,
        )
    except (BotoCoreError, ClientError, UnicodeDecodeError):
        raise
    print(f"Dashboard Silver salva em s3://{args.silver_bucket}/{chave}")


if __name__ == "__main__":
    main()
