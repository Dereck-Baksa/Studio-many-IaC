import io
import json
import pathlib
import sys
import unittest
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo


JOBS_DIRECTORY = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(JOBS_DIRECTORY))

import etl_dashboard_gold
import etl_dashboard_silver


REFERENCE = datetime(
    2026, 10, 26, 12, 0, tzinfo=ZoneInfo("America/Sao_Paulo")
)


def appointment(
    appointment_id,
    status,
    scheduled_at,
    weather=100,
    payments=None,
):
    return {
        "id": appointment_id,
        "clientId": 10,
        "clientName": "Beatriz Nunes",
        "createdAt": "2026-10-01T10:00:00",
        "status": status,
        "finalPrice": "100.00",
        "weatherProbability": weather,
        "payments": payments or [],
        "items": [
            {
                "itemId": appointment_id + 1000,
                "serviceId": 3,
                "service": "Limpeza de pele",
                "servicePrice": "100.00",
                "durationMinutes": 60,
                "professionalId": 7,
                "professionalName": "Dra. Ana",
                "startAt": scheduled_at,
                "endAt": None,
            }
        ],
    }


def dashboard_source():
    return {
        "professionals": [{"id": 7, "name": "Dra. Ana"}],
        "workingDays": [
            {
                "profissional_id": 7,
                "dia_da_semana": "Segunda-feira",
                "hora_inicio": "2026-10-26 09:00:00",
                "hora_fim": "2026-10-26 17:00:00",
            }
        ],
        "blocks": [],
        "appointments": [
            appointment(
                200,
                "Confirmado",
                "2026-10-27T10:00:00",
                payments=[
                    {
                        "value": "100.00",
                        "paidAt": "2026-10-26T11:00:00",
                        "status": "Pago",
                    }
                ],
            ),
            appointment(198, "Faltou", "2026-09-01T10:00:00", weather=None),
        ],
    }


class DashboardSilverTests(unittest.TestCase):
    def test_loads_latest_completed_daily_sql_snapshot(self):
        first = "2026-10-26"
        latest = "2026-10-27"
        objects = {}
        for table in etl_dashboard_silver.TABLES:
            objects[f"sql-data/{table}/data={first}/{table}.json"] = b"[]"
            objects[f"sql-data/{table}/data={latest}/{table}.json"] = b"[]"
        objects[f"sql-data/data={first}/_SUCCESS.json"] = json.dumps(
            {"data": first, "tabelas": sorted(etl_dashboard_silver.TABLES)}
        ).encode("utf-8")
        objects[f"sql-data/data={latest}/_SUCCESS.json"] = json.dumps(
            {"data": latest, "tabelas": sorted(etl_dashboard_silver.TABLES)}
        ).encode("utf-8")
        class FakeS3:
            def get_paginator(self, operation):
                self.operation = operation
                return self

            def paginate(self, Bucket, Prefix):
                yield {
                    "Contents": [
                        {"Key": key}
                        for key in objects
                        if key.startswith(Prefix)
                    ]
                }

            def get_object(self, Bucket, Key):
                return {"Body": io.BytesIO(objects[Key])}

        tables, snapshot = etl_dashboard_silver.carregar_snapshot_sql(
            FakeS3(), "bronze", "sql-data"
        )

        self.assertEqual(snapshot, latest)
        self.assertEqual(set(tables), etl_dashboard_silver.TABLES)

    def test_process_writes_one_stable_daily_dashboard_key(self):
        class FakeS3:
            def __init__(self):
                self.writes = []

            def put_object(self, **kwargs):
                self.writes.append(kwargs)

        fake_s3 = FakeS3()
        with (
            patch.object(
                etl_dashboard_silver,
                "criar_cliente_s3",
                return_value=fake_s3,
            ),
            patch.object(
                etl_dashboard_silver,
                "carregar_snapshot_sql",
                return_value=({}, "2026-10-26"),
            ),
            patch.object(
                etl_dashboard_silver,
                "carregar_dados_meteorologicos",
                return_value={},
            ),
            patch.object(
                etl_dashboard_silver,
                "unir_dados_sql_e_meteorologia",
                return_value=dashboard_source(),
            ),
        ):
            first_key = etl_dashboard_silver.processar(
                "bronze",
                "silver",
                "sql-data",
                "dados-no-show/",
                "2026-10-26",
            )
            second_key = etl_dashboard_silver.processar(
                "bronze",
                "silver",
                "sql-data",
                "dados-no-show/",
                "2026-10-26",
            )

        self.assertEqual(
            first_key,
            "dashboard/data=2026-10-26/dashboard.json",
        )
        self.assertEqual(second_key, first_key)
        self.assertEqual(
            [write["Key"] for write in fake_s3.writes],
            [first_key, first_key],
        )

    def test_joins_sql_rows_with_weather_by_appointment_id(self):
        tables = {
            "status_agendamentos": [{"id": 2, "estado": "Confirmado"}],
            "status_pagamentos": [{"id": 1, "estado": "Pago"}],
            "clientes": [{"id": 10, "nome": "Beatriz Nunes"}],
            "profissionais": [{"id": 7, "nome": "Dra. Ana"}],
            "servicos": [
                {
                    "id": 3,
                    "nome": "Limpeza de pele",
                    "preco": "100.00",
                    "duracao_minutos": 60,
                }
            ],
            "agendamento_itens": [
                {
                    "id": 21,
                    "agendamento_id": 200,
                    "inicio_atendimento": "2026-10-27 10:00:00",
                    "fim_atendimento": None,
                    "servico_id": 3,
                    "profissional_id": 7,
                }
            ],
            "pagamentos": [
                {
                    "valor": "100.00",
                    "pago_em": "2026-10-26 11:00:00",
                    "agendamento_id": 200,
                    "status_pagamento_id": 1,
                }
            ],
            "agendamentos": [
                {
                    "id": 200,
                    "cliente_id": 10,
                    "criado_em": "2026-10-01 10:00:00",
                    "preco_final": "100.00",
                    "status_agendamento_id": 2,
                }
            ],
            "dias_de_trabalho": [],
            "bloqueios": [],
        }

        result = etl_dashboard_silver.unir_dados_sql_e_meteorologia(
            tables,
            {
                "200": {
                    "id_agendamento": 200,
                    "probabilidade_chuva": 45,
                    "qtd_no_shows": 2,
                    "qtd_agendamentos_nao_finalizados": 1,
                    "qtd_agendamentos_concluidos": 5,
                }
            },
        )

        self.assertEqual(len(result["appointments"]), 1)
        item = result["appointments"][0]
        self.assertEqual(item["weatherProbability"], 45)
        self.assertEqual(item["historyNoShows"], 2)
        self.assertEqual(item["historyUnfinished"], 1)
        self.assertEqual(item["historyCompleted"], 5)
        self.assertEqual(item["items"][0]["service"], "Limpeza de pele")
        self.assertEqual(item["payments"][0]["status"], "Pago")


class DashboardGoldTests(unittest.TestCase):
    def test_generates_contract_and_uses_existing_no_show_probability(self):
        schema_path = JOBS_DIRECTORY.parent / "dashboard-data.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))

        result = etl_dashboard_gold.gerar_dashboard(
            dashboard_source(),
            schema,
            agora=REFERENCE,
        )

        self.assertEqual(result["referenceDate"], "2026-10-26")
        self.assertEqual(result["timezone"], "America/Sao_Paulo")
        self.assertEqual(len(result["professionals"]), 1)
        slice_data = result["byProfessional"]["all"]
        self.assertEqual(slice_data["revenue"]["total"], 100.0)
        self.assertEqual(slice_data["services"][0]["revenue"], 100.0)
        self.assertEqual(slice_data["noShow"]["windowDays"], 90)
        self.assertEqual(
            slice_data["noShow"]["heatmap"]["values"][1][1],
            1,
        )
        self.assertEqual(len(slice_data["noShow"]["atRisk"]), 1)
        risk = slice_data["noShow"]["atRisk"][0]
        self.assertEqual(risk["risk"], "Alto")
        self.assertGreaterEqual(risk["probability"], 70)
        self.assertEqual(risk["leadTimeDays"], 26)
        self.assertEqual(
            slice_data["noShow"]["atRisk"][0]["appointmentId"],
            "200",
        )

    def test_status_classifier_rejects_unknown_status(self):
        with self.assertRaisesRegex(ValueError, "não reconhecido"):
            etl_dashboard_gold.classificar_status_agendamento("Em análise")

    def test_non_finalized_status_is_not_misclassified_as_completed(self):
        self.assertEqual(
            etl_dashboard_gold.classificar_status_agendamento("Não finalizado"),
            "pending",
        )

    def test_publishes_dashboard_json_and_original_schema_to_gold(self):
        schema_path = JOBS_DIRECTORY.parent / "dashboard-data.schema.json"
        schema_bytes = schema_path.read_bytes()
        source_bytes = json.dumps(dashboard_source()).encode("utf-8")

        class FakeS3:
            def __init__(self):
                self.writes = []

            def get_paginator(self, operation):
                return self

            def paginate(self, Bucket, Prefix):
                yield {
                    "Contents": [
                        {
                            "Key": (
                                "dashboard/data=2026-10-26/"
                                "dashboard.json"
                            ),
                            "LastModified": REFERENCE,
                        }
                    ]
                }

            def get_object(self, Bucket, Key):
                content = (
                    source_bytes
                    if Bucket == "silver"
                    else schema_bytes
                )
                return {"Body": io.BytesIO(content)}

            def put_object(self, **kwargs):
                self.writes.append(kwargs)

        fake_s3 = FakeS3()
        with (
            patch.object(
                etl_dashboard_gold,
                "criar_cliente_s3",
                return_value=fake_s3,
            ),
            patch.object(
                etl_dashboard_gold,
                "gerar_dashboard",
                return_value={
                    "schemaVersion": "1.0.0",
                    "professionals": [{"id": "prof-7", "name": "Dra. Ana"}],
                },
            ),
        ):
            etl_dashboard_gold.processar(
                "silver",
                "gold",
                "s3://artifacts/glue-jobs/dashboard-data.schema.json",
            )

        self.assertEqual(len(fake_s3.writes), 2)
        writes_by_key = {write["Key"]: write for write in fake_s3.writes}
        daily_key = (
            "dashboard/data=2026-10-26/dashboard-data.json"
        )
        self.assertIn(daily_key, writes_by_key)
        self.assertEqual(
            writes_by_key["dashboard/dashboard-data.schema.json"]["Body"],
            schema_bytes,
        )
        self.assertEqual(
            json.loads(
                writes_by_key[daily_key]["Body"]
            ),
            {
                "schemaVersion": "1.0.0",
                "professionals": [{"id": "prof-7", "name": "Dra. Ana"}],
            },
        )

    def test_silver_join_preserves_missing_weather_for_gold_validation(self):
        tables = {
            "status_agendamentos": [{"id": 2, "estado": "Confirmado"}],
            "status_pagamentos": [],
            "clientes": [{"id": 10, "nome": "Beatriz Nunes"}],
            "profissionais": [{"id": 7, "nome": "Dra. Ana"}],
            "servicos": [
                {
                    "id": 3,
                    "nome": "Limpeza de pele",
                    "preco": "100.00",
                    "duracao_minutos": 60,
                }
            ],
            "agendamento_itens": [
                {
                    "id": 21,
                    "agendamento_id": 200,
                    "inicio_atendimento": "2026-10-27 10:00:00",
                    "servico_id": 3,
                    "profissional_id": 7,
                }
            ],
            "pagamentos": [],
            "agendamentos": [
                {
                    "id": 200,
                    "cliente_id": 10,
                    "status_agendamento_id": 2,
                }
            ],
            "dias_de_trabalho": [],
            "bloqueios": [],
        }

        result = etl_dashboard_silver.unir_dados_sql_e_meteorologia(
            tables, {}
        )
        self.assertIsNone(result["appointments"][0]["weatherProbability"])
        schema_path = JOBS_DIRECTORY.parent / "dashboard-data.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        with self.assertRaisesRegex(ValueError, "Previsão meteorológica ausente"):
            etl_dashboard_gold.gerar_dashboard(
                result,
                schema,
                agora=REFERENCE,
            )


if __name__ == "__main__":
    unittest.main()
