import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import boto3
import pymysql
import pymysql.cursors


DASHBOARD_TABLES = {
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
OPTIONAL_TABLES = {"faturamentos", "disponibilidades"}


def list_tables(connection):
    with connection.cursor() as cursor:
        cursor.execute("SHOW TABLES")
        rows = cursor.fetchall()

    available_tables = {
        next(iter(row.values())) if isinstance(row, dict) else row[0]
        for row in rows
    }
    missing_tables = DASHBOARD_TABLES - available_tables
    if missing_tables:
        raise RuntimeError(
            "Tabelas obrigatórias ausentes no banco: "
            + ", ".join(sorted(missing_tables))
        )

    return sorted(DASHBOARD_TABLES | (OPTIONAL_TABLES & available_tables))


def extract_table(connection, table_name):
    quoted_table = f"`{table_name}`"
    with connection.cursor() as cursor:
        cursor.execute(f"SHOW COLUMNS FROM {quoted_table}")
        columns = [row["Field"] for row in cursor.fetchall()]

        if table_name == "clientes":
            columns = [column for column in columns if column != "total_no_shows"]

        selected_columns = ", ".join(f"`{column}`" for column in columns)
        query = f"SELECT {selected_columns} FROM {quoted_table}"

        if table_name == "agendamento_itens":
            query += (
                " WHERE `inicio_atendimento` >= "
                "DATE_SUB(CURRENT_TIMESTAMP, INTERVAL 365 DAY)"
                " AND `inicio_atendimento` < "
                "DATE_ADD(CURRENT_TIMESTAMP, INTERVAL 30 DAY)"
            )
        elif table_name == "agendamentos":
            query += (
                " WHERE EXISTS (SELECT 1 FROM `agendamento_itens` AS item"
                " WHERE item.`agendamento_id` = `agendamentos`.`id`"
                " AND item.`inicio_atendimento` >= "
                "DATE_SUB(CURRENT_TIMESTAMP, INTERVAL 365 DAY)"
                " AND item.`inicio_atendimento` < "
                "DATE_ADD(CURRENT_TIMESTAMP, INTERVAL 30 DAY))"
            )

        cursor.execute(query)
        return cursor.fetchall()


def _json_default(value):
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def main():
    db_host = os.environ["DB_HOST"]
    db_port = int(os.environ.get("DB_PORT", "3307"))
    db_name = os.environ["DB_NAME"]
    db_user = os.environ["DB_USER"]
    db_password = os.environ["DB_PASSWORD"]
    bucket = os.environ["S3_BUCKET"]
    prefix = os.environ.get("S3_PREFIX", "sql-data").strip("/")
    region = os.environ.get("AWS_REGION", "us-east-1")

    collected_at = datetime.now(ZoneInfo("America/Sao_Paulo"))
    date_partition = collected_at.strftime("%Y-%m-%d")

    connection = pymysql.connect(
        host=db_host,
        port=db_port,
        database=db_name,
        user=db_user,
        password=db_password,
        cursorclass=pymysql.cursors.DictCursor,
        charset="utf8mb4",
        connect_timeout=10,
        read_timeout=30,
        write_timeout=30,
    )
    s3 = boto3.client("s3", region_name=region)

    try:
        table_names = list_tables(connection)
        for table_name in table_names:
            rows = extract_table(connection, table_name)
            key = "/".join(
                part
                for part in (
                    prefix,
                    table_name,
                    f"data={date_partition}",
                    f"{table_name}.json",
                )
                if part
            )
            body = json.dumps(
                rows,
                ensure_ascii=False,
                default=_json_default,
            ).encode("utf-8")
            s3.put_object(
                Bucket=bucket,
                Key=key,
                Body=body,
                ContentType="application/json; charset=utf-8",
            )

        manifest_key = "/".join(
            part
            for part in (prefix, f"data={date_partition}", "_SUCCESS.json")
            if part
        )
        manifest = {
            "data": date_partition,
            "coletadoEm": collected_at.isoformat(timespec="seconds"),
            "tabelas": table_names,
        }
        s3.put_object(
            Bucket=bucket,
            Key=manifest_key,
            Body=json.dumps(manifest, ensure_ascii=False).encode("utf-8"),
            ContentType="application/json; charset=utf-8",
        )
    finally:
        connection.close()


def lambda_handler(event, context):
    main()
    return {"statusCode": 200, "body": "Ingestão SQL concluída."}


if __name__ == "__main__":
    main()
