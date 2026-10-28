import io
import json
import pathlib
import sys
import unittest
from unittest.mock import patch


JOBS_DIRECTORY = pathlib.Path(__file__).resolve().parents[1]
LAMBDA_DIRECTORY = (
    JOBS_DIRECTORY.parents[1]
    / "aws-lambda-dados-no-show"
    / "lambda-py"
    / "lambda_function"
)
sys.path.insert(0, str(JOBS_DIRECTORY))
sys.path.insert(0, str(LAMBDA_DIRECTORY))

import etl_calculo_no_show as etl
import etl_unir_fontes
import lambda_function


DATA = "2026-10-25"


def agendamento_bronze():
    return {
        "idAgendamento": 10,
        "idCliente": 20,
        "nomeCliente": "Cliente",
        "dataHoraAgendamento": f"{DATA}T09:30:00",
        "qtdNoShows": 1,
        "qtdAgendamentosNaoFinalizados": 2,
        "qtdAgendamentosConcluidos": 4,
        "tempoDiasAteConsulta": 15,
    }


def registro_silver():
    return {
        "id_agendamento": 10,
        "id_cliente": 20,
        "nome_cliente": "Cliente",
        "data_hora_agendamento": f"{DATA}T09:30:00",
        "probabilidade_chuva": 40,
        "qtd_no_shows": 1,
        "qtd_agendamentos_nao_finalizados": 2,
        "qtd_agendamentos_concluidos": 4,
        "tempo_dias_ate_consulta": 15,
    }


class FakeS3:
    def __init__(self, objects=None):
        self.objects = objects or {}
        self.writes = []

    def get_object(self, Bucket, Key):
        return {"Body": io.BytesIO(self.objects[(Bucket, Key)])}

    def put_object(self, **kwargs):
        self.writes.append(kwargs)

    def get_paginator(self, operation):
        if operation != "list_objects_v2":
            raise AssertionError(f"Operação S3 inesperada: {operation}")
        return self

    def paginate(self, Bucket, Prefix):
        chaves = [
            chave
            for bucket, chave in self.objects
            if bucket == Bucket and chave.startswith(Prefix)
        ]
        yield {"Contents": [{"Key": chave} for chave in chaves]}


class LambdaTests(unittest.TestCase):
    def test_handler_ingests_for_requested_date(self):
        previsao = {"daily": {"time": [DATA]}}
        arquivos = {
            "studio-many": f"studio-many-api/data={DATA}/agendamentos.json",
            "open-meteo": f"clima/data={DATA}/previsao.json",
        }

        with (
            patch.object(lambda_function, "buscar_agendamentos",
                         return_value=[agendamento_bronze()]) as buscar,
            patch.object(lambda_function, "buscar_dados_meteorologicos",
                         return_value=previsao) as clima,
            patch.object(lambda_function, "salvar_no_s3",
                         return_value=arquivos) as salvar,
            patch.object(lambda_function, "BRONZE_BUCKET", "bronze"),
        ):
            response = lambda_function.lambda_handler({"data": DATA}, None)

        self.assertEqual(response["statusCode"], 200)
        body = json.loads(response["body"])
        self.assertEqual(body["quantidadeAgendamentos"], 1)
        self.assertEqual(body["bucket"], "bronze")
        buscar.assert_called_once_with(DATA)
        clima.assert_called_once_with(DATA)
        salvar.assert_called_once_with(
            DATA,
            [agendamento_bronze()],
            previsao,
        )

    def test_handler_rejects_invalid_date(self):
        with patch.object(
            lambda_function,
            "buscar_agendamentos",
        ) as buscar:
            response = lambda_function.lambda_handler(
                {"data": "25-10-2026"},
                None,
            )

        self.assertEqual(response["statusCode"], 400)
        buscar.assert_not_called()

    def test_saves_two_raw_json_objects_to_bronze(self):
        fake_s3 = FakeS3()
        agendamentos = [agendamento_bronze()]
        previsao = {"daily": {"time": [DATA]}}

        with (
            patch.object(lambda_function, "BRONZE_BUCKET", "bronze"),
            patch.object(lambda_function, "S3_ENDPOINT_URL", None),
            patch.object(lambda_function.boto3, "client",
                         return_value=fake_s3),
        ):
            arquivos = lambda_function.salvar_no_s3(
                DATA,
                agendamentos,
                previsao,
            )

        self.assertEqual(len(fake_s3.writes), 3)
        self.assertEqual(
            arquivos["studio-many"],
            f"studio-many-api/data={DATA}/agendamentos.json",
        )
        self.assertEqual(
            arquivos["open-meteo"],
            f"clima/data={DATA}/previsao.json",
        )
        self.assertEqual(
            json.loads(fake_s3.writes[0]["Body"]),
            agendamentos,
        )
        self.assertTrue(
            all(write["Bucket"] == "bronze" for write in fake_s3.writes)
        )
        self.assertEqual(
            fake_s3.writes[-1]["Key"],
            f"studio-many-api/data={DATA}/_SUCCESS.json",
        )


class BronzeToSilverTests(unittest.TestCase):
    def test_unifies_agendamentos_with_weather_for_matching_date(self):
        registros = etl_unir_fontes.unir_dados(
            [agendamento_bronze()],
            {
                "daily": {
                    "time": ["2026-10-24", DATA],
                    "precipitation_probability_max": [10, 45],
                }
            },
            DATA,
        )

        self.assertEqual(len(registros), 1)
        self.assertEqual(registros[0]["id_agendamento"], 10)
        self.assertEqual(registros[0]["probabilidade_chuva"], 45)
        self.assertEqual(registros[0]["qtd_no_shows"], 1)

    def test_unify_fails_when_weather_date_is_missing(self):
        with self.assertRaisesRegex(ValueError, "indisponível"):
            etl_unir_fontes.unir_dados(
                [agendamento_bronze()],
                {
                    "daily": {
                        "time": ["2026-10-24"],
                        "precipitation_probability_max": [10],
                    }
                },
                DATA,
            )

    def test_process_date_reads_bronze_and_writes_silver_json(self):
        bronze_objects = {
            (
                "bronze",
                f"studio-many-api/data={DATA}/_SUCCESS.json",
            ): json.dumps({"data": DATA}).encode("utf-8"),
            (
                "bronze",
                f"studio-many-api/data={DATA}/agendamentos.json",
            ): json.dumps([agendamento_bronze()]).encode("utf-8"),
            (
                "bronze",
                f"clima/data={DATA}/previsao.json",
            ): json.dumps({
                "daily": {
                    "time": [DATA],
                    "precipitation_probability_max": [45],
                }
            }).encode("utf-8"),
        }
        fake_s3 = FakeS3(bronze_objects)

        with patch.object(
            etl_unir_fontes,
            "criar_cliente_s3",
            return_value=fake_s3,
        ):
            key = etl_unir_fontes.processar_data(
                DATA,
                "bronze",
                "silver",
            )

        self.assertEqual(
            key,
            f"dados-no-show/data={DATA}/agendamentos.json",
        )
        self.assertEqual(fake_s3.writes[0]["Bucket"], "silver")
        self.assertEqual(
            json.loads(fake_s3.writes[0]["Body"])[0][
                "probabilidade_chuva"
            ],
            45,
        )


class SilverToGoldTests(unittest.TestCase):
    def test_calculates_chance_using_existing_formula(self):
        self.assertEqual(
            etl.calcular_chance_falta(registro_silver()),
            30.5,
        )

    def test_uses_neutral_attendance_without_history(self):
        registro = registro_silver()
        registro["qtd_no_shows"] = 0
        registro["qtd_agendamentos_concluidos"] = 0
        registro["tempo_dias_ate_consulta"] = 0
        registro["probabilidade_chuva"] = 0

        self.assertEqual(etl.calcular_chance_falta(registro), 30.0)

    def test_gold_writes_chance_in_partitioned_json(self):
        fake_s3 = FakeS3()

        total = etl.gravar_gold(
            fake_s3,
            "gold",
            [registro_silver()],
            DATA,
        )

        self.assertEqual(total, 1)
        write = fake_s3.writes[0]
        self.assertEqual(write["Bucket"], "gold")
        self.assertEqual(
            write["Key"],
            f"dados-no-show/data={DATA}/agendamentos.json",
        )
        saved = json.loads(write["Body"])[0]
        self.assertEqual(saved["chance"], 30.5)
        self.assertNotIn("chance", registro_silver())

    def test_validation_rejects_rain_probability_out_of_range(self):
        registro = registro_silver()
        registro["probabilidade_chuva"] = 101
        with self.assertRaisesRegex(ValueError, "entre 0 e 100"):
            etl.validar_e_transformar(registro)


if __name__ == "__main__":
    unittest.main()
