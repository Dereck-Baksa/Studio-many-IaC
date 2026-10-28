
import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

import boto3


SPRING_API_BASE_URL = os.environ.get("SPRING_API_BASE_URL")
BRONZE_BUCKET = (
    os.environ.get("BRONZE_BUCKET")
    or os.environ.get("S3_BUCKET")
)
S3_ENDPOINT_URL = os.environ.get("S3_ENDPOINT_URL")

LATITUDE = float(os.environ.get("LATITUDE", "-23.55"))
LONGITUDE = float(os.environ.get("LONGITUDE", "-46.63"))


def get_json(url):
    with urlopen(url, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def buscar_agendamentos(data):
    if not SPRING_API_BASE_URL:
        raise RuntimeError(
            "A variável SPRING_API_BASE_URL não foi configurada."
        )

    params = urlencode({"data": data})
    url = (
        f"{SPRING_API_BASE_URL.rstrip('/')}"
        f"/analise/agendamentos?{params}"
    )

    agendamentos = get_json(url)
    if not isinstance(agendamentos, list):
        raise ValueError(
            "A API de agendamentos deve retornar uma lista JSON."
        )

    return agendamentos


def buscar_dados_meteorologicos(data):
    params = urlencode({
        "latitude": LATITUDE,
        "longitude": LONGITUDE,
        "daily": "precipitation_probability_max",
        "timezone": "America/Sao_Paulo",
        "start_date": data,
        "end_date": data,
    })

    url = f"https://api.open-meteo.com/v1/forecast?{params}"
    resposta = get_json(url)

    return resposta


def salvar_no_s3(data, agendamentos, dados_meteorologicos):
    if not BRONZE_BUCKET:
        raise RuntimeError(
            "A variável BRONZE_BUCKET não foi configurada."
        )

    configuracao = {
        "region_name": os.getenv("AWS_REGION", "us-east-1"),
    }
    if S3_ENDPOINT_URL:
        configuracao.update({
            "endpoint_url": S3_ENDPOINT_URL,
            "aws_access_key_id": os.getenv(
                "AWS_ACCESS_KEY_ID",
                "test",
            ),
            "aws_secret_access_key": os.getenv(
                "AWS_SECRET_ACCESS_KEY",
                "test",
            ),
        })
    cliente_s3 = boto3.client("s3", **configuracao)

    prefixo_data = f"data={data}/"
    arquivos = {
        "studio-many": f"studio-many-api/{prefixo_data}agendamentos.json",
        "open-meteo": f"clima/{prefixo_data}previsao.json",
    }
    objetos = [
        (
            arquivos["studio-many"],
            json.dumps(agendamentos, ensure_ascii=False).encode("utf-8"),
            "application/json; charset=utf-8",
        ),
        (
            arquivos["open-meteo"],
            json.dumps(
                dados_meteorologicos,
                ensure_ascii=False,
            ).encode("utf-8"),
            "application/json; charset=utf-8",
        ),
    ]

    for chave, conteudo, content_type in objetos:
        cliente_s3.put_object(
            Bucket=BRONZE_BUCKET,
            Key=chave,
            Body=conteudo,
            ContentType=content_type,
        )

    cliente_s3.put_object(
        Bucket=BRONZE_BUCKET,
        Key=f"studio-many-api/{prefixo_data}_SUCCESS.json",
        Body=json.dumps(
            {
                "data": data,
                "coletadoEm": datetime.now(
                    ZoneInfo("America/Sao_Paulo")
                ).isoformat(timespec="seconds"),
                "arquivos": list(arquivos.values()),
            },
            ensure_ascii=False,
        ).encode("utf-8"),
        ContentType="application/json; charset=utf-8",
    )

    return arquivos


def lambda_handler(event, context):
    try:
        parametros = event.get("queryStringParameters") or {}
        data = event.get("data") or parametros.get("data")

        if data is None:
            data = datetime.now(ZoneInfo("America/Sao_Paulo")).strftime(
                "%Y-%m-%d"
            )
        elif not isinstance(data, str) or not data:
            raise ValueError("Informe a data no formato YYYY-MM-DD.")

        # Valida o formato da data.
        datetime.strptime(data, "%Y-%m-%d")

        agendamentos = buscar_agendamentos(data)
        dados_meteorologicos = buscar_dados_meteorologicos(data)

        arquivos = salvar_no_s3(
            data,
            agendamentos,
            dados_meteorologicos,
        )

        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json"
            },
            "body": json.dumps({
                "mensagem": "Arquivos salvos com sucesso.",
                "data": data,
                "quantidadeAgendamentos": len(agendamentos),
                "bucket": BRONZE_BUCKET,
                "arquivos": arquivos,
            }, ensure_ascii=False),
        }

    except ValueError as erro:
        return {
            "statusCode": 400,
            "body": json.dumps({
                "erro": str(erro)
            }, ensure_ascii=False),
        }

    except (HTTPError, URLError) as erro:
        print(f"Erro na comunicação HTTP: {erro}")
        raise

    except Exception as erro:
        print(f"Erro ao processar agendamentos: {erro}")
        raise
