import argparse
import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import boto3


TIMEZONE_NAME = "America/Sao_Paulo"


def data_local():
    return datetime.now(ZoneInfo(TIMEZONE_NAME)).strftime("%Y-%m-%d")


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


def ler_json_s3(cliente_s3, bucket, chave):
    resposta = cliente_s3.get_object(Bucket=bucket, Key=chave)

    with resposta["Body"] as corpo:
        return json.loads(corpo.read().decode("utf-8"))


def unir_dados(agendamentos, dados_meteorologicos, data):
    if not isinstance(agendamentos, list):
        raise ValueError("A resposta de agendamentos deve ser uma lista.")

    dados_diarios = dados_meteorologicos.get("daily", {})
    datas = dados_diarios.get("time", [])
    probabilidades = dados_diarios.get(
        "precipitation_probability_max",
        [],
    )

    try:
        indice_data = datas.index(data)
        probabilidade_chuva = probabilidades[indice_data]
    except (ValueError, IndexError) as erro:
        raise ValueError(
            f"Previsão de chuva indisponível para {data}."
        ) from erro

    if probabilidade_chuva is None:
        raise ValueError(
            f"Previsão de chuva indisponível para {data}."
        )

    registros = []
    for agendamento in agendamentos:
        if not isinstance(agendamento, dict):
            raise ValueError("Cada agendamento deve ser um objeto JSON.")

        registros.append({
            "id_agendamento": agendamento.get("idAgendamento"),
            "id_cliente": agendamento.get("idCliente"),
            "nome_cliente": agendamento.get("nomeCliente"),
            "data_hora_agendamento": agendamento.get(
                "dataHoraAgendamento"
            ),
            "probabilidade_chuva": probabilidade_chuva,
            "qtd_no_shows": agendamento.get("qtdNoShows"),
            "qtd_agendamentos_nao_finalizados": agendamento.get(
                "qtdAgendamentosNaoFinalizados"
            ),
            "qtd_agendamentos_concluidos": agendamento.get(
                "qtdAgendamentosConcluidos"
            ),
            "tempo_dias_ate_consulta": agendamento.get(
                "tempoDiasAteConsulta"
            ),
        })

    return registros


def processar_data(data, bucket_bronze, bucket_silver):
    datetime.strptime(data, "%Y-%m-%d")
    cliente_s3 = criar_cliente_s3()
    prefixo_data = f"data={data}/"
    manifesto = ler_json_s3(
        cliente_s3,
        bucket_bronze,
        f"studio-many-api/{prefixo_data}_SUCCESS.json",
    )
    if not isinstance(manifesto, dict) or manifesto.get("data") != data:
        raise RuntimeError(
            f"Coleta Bronze incompleta para {data}: manifesto inválido."
        )

    agendamentos = ler_json_s3(
        cliente_s3,
        bucket_bronze,
        f"studio-many-api/{prefixo_data}agendamentos.json",
    )
    dados_meteorologicos = ler_json_s3(
        cliente_s3,
        bucket_bronze,
        f"clima/{prefixo_data}previsao.json",
    )
    registros = unir_dados(agendamentos, dados_meteorologicos, data)

    chave_saida = f"dados-no-show/{prefixo_data}agendamentos.json"
    cliente_s3.put_object(
        Bucket=bucket_silver,
        Key=chave_saida,
        Body=json.dumps(
            registros,
            ensure_ascii=False,
        ).encode("utf-8"),
        ContentType="application/json; charset=utf-8",
    )

    return chave_saida


def main():
    parser = argparse.ArgumentParser(
        description="Une dados Bronze e grava o JSON consolidado na Silver."
    )
    parser.add_argument(
        "--date",
        default=data_local(),
        help="Data no formato YYYY-MM-DD.",
    )
    parser.add_argument(
        "--bronze-bucket",
        default=os.getenv("BRONZE_BUCKET"),
        required=os.getenv("BRONZE_BUCKET") is None,
    )
    parser.add_argument(
        "--silver-bucket",
        default=os.getenv("SILVER_BUCKET"),
        required=os.getenv("SILVER_BUCKET") is None,
    )
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

    chave_saida = processar_data(
        argumentos.date,
        argumentos.bronze_bucket,
        argumentos.silver_bucket,
    )
    print(
        f"JSON consolidado salvo em "
        f"s3://{argumentos.silver_bucket}/{chave_saida}"
    )


if __name__ == "__main__":
    main()
