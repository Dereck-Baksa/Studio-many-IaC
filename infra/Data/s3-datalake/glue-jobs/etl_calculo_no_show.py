import argparse
import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import boto3
from botocore.exceptions import BotoCoreError, ClientError


PREFIXO_SILVER = "dados-no-show/"
PREFIXO_GOLD = "dados-no-show/"
TIMEZONE_NAME = "America/Sao_Paulo"


def data_local():
    return datetime.now(ZoneInfo(TIMEZONE_NAME)).strftime("%Y-%m-%d")

CAMPOS = [
    "id_agendamento",
    "id_cliente",
    "nome_cliente",
    "data_hora_agendamento",
    "probabilidade_chuva",
    "qtd_no_shows",
    "qtd_agendamentos_nao_finalizados",
    "qtd_agendamentos_concluidos",
    "tempo_dias_ate_consulta",
]

CAMPOS_GOLD = CAMPOS + ["chance"]

CAMPOS_INTEIROS = [
    "id_agendamento",
    "id_cliente",
    "probabilidade_chuva",
    "qtd_no_shows",
    "qtd_agendamentos_nao_finalizados",
    "qtd_agendamentos_concluidos",
    "tempo_dias_ate_consulta",
]

CAMPOS_NAO_NEGATIVOS = [
    "qtd_no_shows",
    "qtd_agendamentos_nao_finalizados",
    "qtd_agendamentos_concluidos",
    "tempo_dias_ate_consulta",
]


def criar_cliente_s3():
    configuracao = {
        "region_name": os.getenv("AWS_REGION", "us-east-1"),
    }
    endpoint_url = os.getenv("S3_ENDPOINT_URL")

    if endpoint_url:
        configuracao.update({
            "endpoint_url": endpoint_url,
            "aws_access_key_id": os.getenv(
                "AWS_ACCESS_KEY_ID",
                "test",
            ),
            "aws_secret_access_key": os.getenv(
                "AWS_SECRET_ACCESS_KEY",
                "test",
            ),
        })

    return boto3.client("s3", **configuracao)


def validar_e_transformar(linha):
    """Valida um registro da Silver e normaliza seus tipos."""

    if not isinstance(linha, dict):
        raise ValueError("Cada registro deve ser um objeto JSON.")

    registro = {}

    for campo in CAMPOS:
        valor = linha.get(campo)

        if valor is None or not str(valor).strip():
            raise ValueError(f"Campo obrigatório vazio: {campo}")

        registro[campo] = str(valor).strip()

    for campo in CAMPOS_INTEIROS:
        try:
            registro[campo] = int(registro[campo])
        except ValueError as erro:
            raise ValueError(
                f"Valor inteiro inválido em {campo}"
            ) from erro

    if registro["id_agendamento"] <= 0:
        raise ValueError("ID do agendamento deve ser positivo")

    if registro["id_cliente"] <= 0:
        raise ValueError("ID do cliente deve ser positivo")

    probabilidade = registro["probabilidade_chuva"]
    if not 0 <= probabilidade <= 100:
        raise ValueError(
            "Probabilidade de chuva deve estar entre 0 e 100"
        )

    for campo in CAMPOS_NAO_NEGATIVOS:
        if registro[campo] < 0:
            raise ValueError(f"Valor negativo em {campo}")

    try:
        data_hora = datetime.fromisoformat(
            registro["data_hora_agendamento"]
        )
    except ValueError as erro:
        raise ValueError(
            "Data/hora do agendamento inválida"
        ) from erro

    registro["data_hora_agendamento"] = data_hora.isoformat(
        timespec="seconds"
    )
    return registro


def calcular_chance_falta(registro):
    """Calcula a chance estimada de falta, em porcentagem."""

    concluidos = registro["qtd_agendamentos_concluidos"]
    faltas = registro["qtd_no_shows"]
    dias = registro["tempo_dias_ate_consulta"]
    chuva = registro["probabilidade_chuva"]

    total_historico = concluidos + faltas
    if total_historico == 0:
        taxa_comparecimento = 0.5
    else:
        taxa_comparecimento = concluidos / total_historico

    taxa_faltas = 1 - taxa_comparecimento
    fator_tempo = min(max(dias, 0) / 30, 1)
    fator_chuva = chuva / 100

    chance = (
        0.60 * taxa_faltas
        + 0.25 * fator_tempo
        + 0.15 * fator_chuva
    ) * 100

    return round(chance, 2)


def listar_arquivos_silver(cliente_s3, bucket_silver, data=None):
    """Lista JSONs consolidados na Silver em ordem determinística."""

    paginator = cliente_s3.get_paginator("list_objects_v2")
    chaves = []
    prefixo = PREFIXO_SILVER
    if data:
        datetime.strptime(data, "%Y-%m-%d")
        prefixo = f"{PREFIXO_SILVER}data={data}/"

    for pagina in paginator.paginate(
        Bucket=bucket_silver,
        Prefix=prefixo,
    ):
        chaves.extend(
            objeto["Key"]
            for objeto in pagina.get("Contents", [])
            if objeto["Key"].lower().endswith(".json")
        )

    return sorted(chaves)


def ler_registros_silver(cliente_s3, bucket_silver, chaves):
    registros = []
    invalidos = 0

    for chave in chaves:
        resposta = cliente_s3.get_object(
            Bucket=bucket_silver,
            Key=chave,
        )

        with resposta["Body"] as corpo:
            conteudo = json.loads(corpo.read().decode("utf-8"))

        if not isinstance(conteudo, list):
            print(f"Arquivo ignorado: {chave} (raiz não é uma lista)")
            invalidos += 1
            continue

        for numero_linha, linha in enumerate(conteudo, start=1):
            try:
                registro = validar_e_transformar(linha)
                registros.append((chave, numero_linha, registro))
            except (ValueError, TypeError, AttributeError) as erro:
                invalidos += 1
                print(
                    f"Registro inválido: {chave}, "
                    f"item {numero_linha}: {erro}"
                )

    return registros, invalidos


def remover_duplicados(registros):
    """Mantém o primeiro registro válido de cada ID, deterministicamente."""

    unicos = {}
    duplicados = 0

    for chave, numero_linha, registro in registros:
        identificador = registro["id_agendamento"]
        if identificador in unicos:
            duplicados += 1
            print(
                f"Duplicado ignorado: ID {identificador}, "
                f"arquivo {chave}, item {numero_linha}"
            )
            continue

        unicos[identificador] = registro

    return list(unicos.values()), duplicados


def gravar_gold(cliente_s3, bucket_gold, registros, data_referencia=None):
    """Calcula a chance de falta e atualiza o arquivo diário da Gold."""

    data_referencia = data_referencia or data_local()
    datetime.strptime(data_referencia, "%Y-%m-%d")
    linhas = []
    for registro in registros:
        registro_com_chance = registro.copy()
        registro_com_chance["chance"] = calcular_chance_falta(registro)
        linhas.append(registro_com_chance)

    linhas.sort(key=lambda item: item["id_agendamento"])
    chave = f"{PREFIXO_GOLD}data={data_referencia}/agendamentos.json"
    cliente_s3.put_object(
        Bucket=bucket_gold,
        Key=chave,
        Body=json.dumps(
            linhas,
            ensure_ascii=False,
        ).encode("utf-8"),
        ContentType="application/json; charset=utf-8",
    )
    print(
        f"Gravados {len(linhas)} registros em "
        f"s3://{bucket_gold}/{chave}"
    )
    return len(linhas)


def main():
    parser = argparse.ArgumentParser(
        description="Valida dados da Silver e grava o resultado na Gold."
    )
    parser.add_argument(
        "--silver-bucket",
        default=os.getenv("SILVER_BUCKET"),
        required=os.getenv("SILVER_BUCKET") is None,
    )
    parser.add_argument(
        "--gold-bucket",
        default=os.getenv("GOLD_BUCKET"),
        required=os.getenv("GOLD_BUCKET") is None,
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
    argumentos = parser.parse_args()
    cliente_s3 = criar_cliente_s3()

    try:
        arquivos = listar_arquivos_silver(
            cliente_s3,
            argumentos.silver_bucket,
            argumentos.date,
        )
        registros, invalidos = ler_registros_silver(
            cliente_s3,
            argumentos.silver_bucket,
            arquivos,
        )
        registros_unicos, duplicados = remover_duplicados(registros)
        total_gravados = gravar_gold(
            cliente_s3,
            argumentos.gold_bucket,
            registros_unicos,
            argumentos.date,
        )

        print("\nETL Silver -> Gold concluído.")
        print(f"Arquivos Silver encontrados: {len(arquivos)}")
        print(f"Registros válidos lidos: {len(registros)}")
        print(f"Duplicados removidos: {duplicados}")
        print(f"Registros inválidos ignorados: {invalidos}")
        print(f"Registros gravados: {total_gravados}")
    except (BotoCoreError, ClientError, UnicodeDecodeError) as erro:
        print(f"Falha no processamento: {erro}")
        raise


if __name__ == "__main__":
    main()
