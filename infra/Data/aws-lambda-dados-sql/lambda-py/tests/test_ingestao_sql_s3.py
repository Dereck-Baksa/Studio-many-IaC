import importlib.util
import json
import sys
import types
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "lambda_function"
    / "ingestao_sql_s3.py"
)


def load_collector():
    fake_boto3 = types.ModuleType("boto3")
    fake_boto3.client = MagicMock()
    fake_pymysql = types.ModuleType("pymysql")
    fake_pymysql.connect = MagicMock()
    fake_cursors = types.ModuleType("pymysql.cursors")
    fake_cursors.DictCursor = object
    fake_pymysql.cursors = fake_cursors

    with patch.dict(
        sys.modules,
        {
            "boto3": fake_boto3,
            "pymysql": fake_pymysql,
            "pymysql.cursors": fake_cursors,
        },
    ):
        spec = importlib.util.spec_from_file_location("ingestao_sql_s3_tested", SCRIPT_PATH)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Não foi possível carregar o coletor em {SCRIPT_PATH}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


collector = load_collector()


class FakeCursor:
    def __init__(self, columns=None, rows=None, tables=None):
        self.columns = columns or []
        self.rows = rows or []
        self.tables = tables or []
        self.query = ""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def execute(self, query):
        self.query = query

    def fetchall(self):
        if self.query == "SHOW TABLES":
            return [{"table_name": table} for table in self.tables]
        if self.query.startswith("SHOW COLUMNS"):
            return [{"Field": column} for column in self.columns]
        if self.query.startswith("SELECT"):
            return self.rows
        raise AssertionError(f"Consulta inesperada: {self.query}")


class FakeConnection:
    def __init__(self, cursor):
        self.fake_cursor = cursor
        self.closed = False

    def cursor(self):
        return self.fake_cursor

    def close(self):
        self.closed = True


class IngestaoSqlS3Tests(unittest.TestCase):
    def test_list_tables_returns_only_dashboard_tables(self):
        cursor = FakeCursor(
            tables=list(collector.DASHBOARD_TABLES) + ["usuarios", "comprovantes"]
        )

        tables = collector.list_tables(FakeConnection(cursor))

        self.assertEqual(tables, sorted(collector.DASHBOARD_TABLES))

    def test_list_tables_reports_missing_required_tables(self):
        cursor = FakeCursor(tables=["usuarios"])

        with self.assertRaisesRegex(RuntimeError, "agendamentos"):
            collector.list_tables(FakeConnection(cursor))

    def test_agendamento_itens_query_keeps_history_and_next_30_days(self):
        cursor = FakeCursor(columns=["id", "inicio_atendimento"])

        collector.extract_table(FakeConnection(cursor), "agendamento_itens")

        self.assertIn(
            "`inicio_atendimento` >= DATE_SUB(CURRENT_TIMESTAMP, INTERVAL 365 DAY)",
            cursor.query,
        )
        self.assertIn(
            "`inicio_atendimento` < DATE_ADD(CURRENT_TIMESTAMP, INTERVAL 30 DAY)",
            cursor.query,
        )

    def test_agendamentos_query_includes_history_and_future_items(self):
        cursor = FakeCursor(columns=["id", "cliente_id"])

        collector.extract_table(FakeConnection(cursor), "agendamentos")

        self.assertIn("EXISTS", cursor.query)
        self.assertIn("item.`agendamento_id` = `agendamentos`.`id`", cursor.query)
        self.assertIn(
            "item.`inicio_atendimento` >= DATE_SUB(CURRENT_TIMESTAMP, INTERVAL 365 DAY)",
            cursor.query,
        )
        self.assertIn(
            "item.`inicio_atendimento` < DATE_ADD(CURRENT_TIMESTAMP, INTERVAL 30 DAY)",
            cursor.query,
        )

    def test_client_export_excludes_only_no_show_column(self):
        cursor = FakeCursor(
            columns=["id", "nome", "total_no_shows"],
            rows=[{"id": 1, "nome": "Cliente"}],
        )

        rows = collector.extract_table(FakeConnection(cursor), "clientes")

        self.assertEqual(rows, [{"id": 1, "nome": "Cliente"}])
        self.assertIn("`id`, `nome`", cursor.query)
        self.assertNotIn("total_no_shows", cursor.query)

    def test_main_connects_on_3307_and_uploads_daily_json(self):
        collected_at = datetime(
            2026,
            10,
            26,
            23,
            30,
            0,
            tzinfo=ZoneInfo("America/Sao_Paulo"),
        )
        connection = MagicMock()
        s3 = MagicMock()
        env = {
            "DB_HOST": "localhost",
            "DB_NAME": "studiomanydb",
            "DB_USER": "test-user",
            "DB_PASSWORD": "test-password",
            "S3_BUCKET": "test-bucket",
            "S3_PREFIX": "sql-data/",
        }

        with (
            patch.dict("os.environ", env, clear=True),
            patch.object(collector.pymysql, "connect", return_value=connection) as connect,
            patch.object(collector.boto3, "client", return_value=s3),
            patch.object(collector, "list_tables", return_value=["clientes"]),
            patch.object(
                collector,
                "extract_table",
                return_value=[{"id": 1, "nome": "Cliente"}],
            ),
            patch.object(collector, "datetime") as datetime_mock,
        ):
            datetime_mock.now.return_value = collected_at

            collector.main()

        self.assertEqual(connect.call_args.kwargs["port"], 3307)
        self.assertEqual(connect.call_args.kwargs["database"], "studiomanydb")
        connection.close.assert_called_once_with()
        self.assertEqual(s3.put_object.call_count, 2)

        upload = s3.put_object.call_args.kwargs
        self.assertEqual(upload["Bucket"], "test-bucket")
        self.assertEqual(
            upload["Key"],
            "sql-data/data=2026-10-26/_SUCCESS.json",
        )
        self.assertEqual(upload["ContentType"], "application/json; charset=utf-8")
        table_upload = s3.put_object.call_args_list[0].kwargs
        self.assertEqual(
            table_upload["Key"],
            "sql-data/clientes/data=2026-10-26/clientes.json",
        )
        self.assertEqual(
            json.loads(table_upload["Body"].decode("utf-8")),
            [{"id": 1, "nome": "Cliente"}],
        )
        self.assertEqual(
            json.loads(upload["Body"].decode("utf-8"))["data"],
            "2026-10-26",
        )


if __name__ == "__main__":
    unittest.main()
