import argparse
import json
import os
import re
import unicodedata
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from etl_calculo_no_show import calcular_chance_falta, validar_e_transformar


TIMEZONE_NAME = "America/Sao_Paulo"
WEEKDAY_LABELS = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]
HEATMAP_SLOTS = [
    ("08h–10h", 8, 10),
    ("10h–12h", 10, 12),
    ("12h–14h", 12, 14),
    ("14h–16h", 14, 16),
    ("16h–19h", 16, 19),
]
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


def _normalizar_texto(valor):
    texto = unicodedata.normalize("NFKD", str(valor or ""))
    texto = "".join(
        caractere
        for caractere in texto
        if not unicodedata.combining(caractere)
    ).lower()
    return texto.replace("-", " ").replace("_", " ")


def classificar_status_agendamento(status):
    texto = _normalizar_texto(status)
    if any(
        termo in texto
        for termo in (
            "no show",
            "noshow",
            "faltou",
            "falta",
            "nao compareceu",
            "nao veio",
            "ausente",
        )
    ):
        return "no_show"
    if "cancel" in texto:
        return "cancelled"
    if any(
        termo in texto
        for termo in (
            "pendente",
            "aguard",
            "aberto",
            "nao confirmado",
            "nao finalizado",
            "nao finalizada",
        )
    ):
        return "pending"
    if any(
        termo in texto
        for termo in (
            "conclu",
            "realiz",
            "atendid",
            "finaliz",
            "compareceu",
            "presente",
        )
    ):
        return "completed"
    if any(termo in texto for termo in ("confirm", "agendado")):
        return "confirmed"
    raise ValueError(f"Status de agendamento não reconhecido: {status!r}")


def _datetime_local(valor):
    if not valor:
        raise ValueError("Data/hora de agendamento ausente.")
    resultado = datetime.fromisoformat(str(valor).replace("Z", "+00:00"))
    if resultado.tzinfo is None:
        resultado = resultado.replace(tzinfo=ZoneInfo(TIMEZONE_NAME))
    return resultado.astimezone(ZoneInfo(TIMEZONE_NAME))


def _valor_decimal(valor):
    if valor is None or str(valor).strip() == "":
        return Decimal("0")
    try:
        return Decimal(str(valor))
    except (InvalidOperation, TypeError, ValueError) as erro:
        raise ValueError(f"Valor monetário inválido: {valor!r}") from erro


def _identificador(valor, campo):
    try:
        identificador = int(valor)
    except (TypeError, ValueError) as erro:
        raise ValueError(f"Identificador inválido em {campo}: {valor!r}") from erro
    if identificador <= 0:
        raise ValueError(f"Identificador deve ser positivo em {campo}")
    return identificador


def _status_pagamento_pago(status):
    texto = _normalizar_texto(status)
    if any(termo in texto for termo in ("nao", "cancel", "estorn", "pendente")):
        return False
    return any(termo in texto for termo in ("pago", "aprovado", "recebido", "paid"))


def _mes_seguinte(ano, mes):
    return (ano + 1, 1) if mes == 12 else (ano, mes + 1)


def _hora(valor):
    if isinstance(valor, time):
        return valor.replace(tzinfo=None)
    if isinstance(valor, datetime):
        return valor.time().replace(tzinfo=None)
    if not valor:
        return None
    texto = str(valor)
    try:
        return time.fromisoformat(texto[11:19] if len(texto) >= 19 else texto)
    except ValueError as erro:
        raise ValueError(f"Horário inválido: {valor!r}") from erro


def _weekday_numero(valor):
    texto = _normalizar_texto(valor).strip()
    dias = {
        "segunda": 0, "segunda feira": 0, "seg": 0, "monday": 0,
        "terca": 1, "terca feira": 1, "ter": 1, "tuesday": 1,
        "quarta": 2, "quarta feira": 2, "qua": 2, "wednesday": 2,
        "quinta": 3, "quinta feira": 3, "qui": 3, "thursday": 3,
        "sexta": 4, "sexta feira": 4, "sex": 4, "friday": 4,
        "sabado": 5, "sab": 5, "saturday": 5,
        "domingo": 6, "dom": 6, "sunday": 6,
    }
    if texto not in dias:
        raise ValueError(f"Dia da semana inválido em dias_de_trabalho: {valor!r}")
    return dias[texto]





def _appointment_records(dados, referencia):
    profissionais = {}
    ids_usados = set()
    for item in dados.get("professionals", []):
        sql_id = _identificador(item.get("id"), "professionals.id")
        nome = str(item.get("name") or "").strip()
        if not nome:
            raise ValueError(f"Nome ausente para profissional {sql_id}")
        base_id = f"prof-{sql_id}"
        professional_id = base_id if base_id not in ids_usados else f"{base_id}-{sql_id}"
        ids_usados.add(professional_id)
        profissionais[str(sql_id)] = {"id": professional_id, "name": nome}

    appointments = []
    by_id = {}
    for raw in dados.get("appointments", []):
        appointment_id = _identificador(raw.get("id"), "appointments.id")
        if appointment_id in by_id:
            raise ValueError(f"Agendamento duplicado no Silver: {appointment_id}")
        client_id = (
            _identificador(raw.get("clientId"), "appointments.clientId")
            if raw.get("clientId") is not None
            else None
        )
        status = classificar_status_agendamento(raw.get("status"))
        start_rows = []
        for item in raw.get("items", []):
            professional = profissionais.get(str(item.get("professionalId")))
            if professional is None:
                raise ValueError(
                    f"Profissional {item.get('professionalId')} não encontrado "
                    f"no agendamento {appointment_id}"
                )
            horario = _datetime_local(item.get("startAt"))
            fim = _datetime_local(item["endAt"]) if item.get("endAt") else None
            minutos = item.get("durationMinutes")
            if minutos is None and fim is not None:
                minutos = max(0, int((fim - horario).total_seconds() // 60))
            if minutos is None:
                raise ValueError(
                    f"Duração ausente para o item {item.get('itemId')} "
                    f"do agendamento {appointment_id}"
                )
            start_rows.append(
                {
                    **item,
                    "professional": professional,
                    "start": horario,
                    "durationMinutes": int(minutos),
                }
            )
        if not start_rows:
            continue
        start_rows.sort(key=lambda item: item["start"])
        appointment = {
            **raw,
            "id": appointment_id,
            "clientId": client_id,
            "statusKey": status,
            "historyNoShows": raw.get("historyNoShows"),
            "historyUnfinished": raw.get("historyUnfinished"),
            "historyCompleted": raw.get("historyCompleted"),
            "items": start_rows,
        }
        appointments.append(appointment)
        by_id[appointment_id] = appointment

    return profissionais, appointments, by_id


def _weather_by_appointment(appointment):
    valor = appointment.get("weatherProbability")
    if valor is None:
        raise ValueError(
            f"Previsão meteorológica ausente para o agendamento {appointment['id']}"
        )
    try:
        probabilidade = int(round(float(valor)))
    except (TypeError, ValueError) as erro:
        raise ValueError(
            f"Previsão meteorológica inválida para o agendamento {appointment['id']}"
        ) from erro
    if not 0 <= probabilidade <= 100:
        raise ValueError(
            f"Probabilidade de chuva fora do intervalo para o agendamento "
            f"{appointment['id']}"
        )
    return probabilidade


def _historico_por_cliente(appointments, reference_date):
    inicio = reference_date - timedelta(days=180)
    historico = defaultdict(dict)
    for appointment in appointments:
        if appointment["statusKey"] not in ("no_show", "completed"):
            continue
        if appointment["clientId"] is None:
            continue
        if appointment["items"][0]["start"].date() >= reference_date:
            continue
        if appointment["items"][0]["start"].date() < inicio:
            continue
        historico[appointment["clientId"]][appointment["id"]] = appointment["statusKey"]
    contagem = {}
    for client_id, registros in historico.items():
        contagem[client_id] = {
            "no_shows": sum(status == "no_show" for status in registros.values()),
            "completed": sum(status == "completed" for status in registros.values()),
        }
    return contagem


def _chance_por_agendamento(appointment, historico, reference_date):
    first_item = appointment["items"][0]
    dias_ate = max(0, (first_item["start"].date() - reference_date).days)
    contagens = historico.get(appointment["clientId"], {})
    registro = validar_e_transformar(
        {
            "id_agendamento": appointment["id"],
            "id_cliente": appointment["clientId"] or appointment["id"],
            "nome_cliente": appointment.get("clientName") or "Cliente",
            "data_hora_agendamento": first_item["start"].isoformat(timespec="seconds"),
            "probabilidade_chuva": _weather_by_appointment(appointment),
            "qtd_no_shows": (
                appointment["historyNoShows"]
                if appointment["historyNoShows"] is not None
                else contagens.get("no_shows", 0)
            ),
            "qtd_agendamentos_nao_finalizados": (
                appointment["historyUnfinished"]
                if appointment["historyUnfinished"] is not None
                else 0
            ),
            "qtd_agendamentos_concluidos": (
                appointment["historyCompleted"]
                if appointment["historyCompleted"] is not None
                else contagens.get("completed", 0)
            ),
            "tempo_dias_ate_consulta": dias_ate,
        }
    )
    return calcular_chance_falta(registro)


def _payment_totals(dados, reference_date):
    totais = defaultdict(Decimal)
    for appointment in dados.get("appointments", []):
        for payment in appointment.get("payments", []):
            if not _status_pagamento_pago(payment.get("status")):
                continue
            if not payment.get("paidAt"):
                continue
            paid_date = _datetime_local(payment["paidAt"]).date()
            if paid_date.year != reference_date.year or paid_date.month != reference_date.month:
                continue
            totais[int(appointment["id"])] += _valor_decimal(payment.get("value"))
    return totais


def _payment_totals_month(dados, year, month):
    totais = defaultdict(Decimal)
    for appointment in dados.get("appointments", []):
        for payment in appointment.get("payments", []):
            if not _status_pagamento_pago(payment.get("status")):
                continue
            if not payment.get("paidAt"):
                continue
            paid_date = _datetime_local(payment["paidAt"]).date()
            if paid_date.year == year and paid_date.month == month:
                totais[int(appointment["id"])] += _valor_decimal(
                    payment.get("value")
                )
    return totais


def _revenue_for_month(
    appointments, payment_totals, year, month, professional_id
):
    total = Decimal("0")
    for appointment in appointments:
        itens_mes = [
            item
            for item in appointment["items"]
            if item["start"].year == year
            and item["start"].month == month
            and appointment["statusKey"] != "cancelled"
        ]
        if not itens_mes:
            continue
        distribuicao = _distribuir_valor(
            payment_totals.get(appointment["id"], Decimal("0")), itens_mes
        )
        for item in itens_mes:
            if (
                not professional_id
                or item["professional"]["id"] == professional_id
            ):
                total += distribuicao.get(item["itemId"], Decimal("0"))
    return total


def _distribuir_valor(valor, itens):
    if not itens:
        return {}
    pesos = [max(Decimal("0"), _valor_decimal(item.get("servicePrice"))) for item in itens]
    total_pesos = sum(pesos)
    if total_pesos == 0:
        pesos = [Decimal("1") for _ in itens]
        total_pesos = Decimal(len(itens))
    distribuido = {}
    restante = valor
    for indice, item in enumerate(itens):
        if indice == len(itens) - 1:
            parcela = restante
        else:
            parcela = (valor * pesos[indice] / total_pesos).quantize(Decimal("0.01"))
            restante -= parcela
        distribuido[item["itemId"]] = parcela
    return distribuido


def _current_month_items(appointments, reference_date):
    return [
        (appointment, item)
        for appointment in appointments
        for item in appointment["items"]
        if item["start"].year == reference_date.year
        and item["start"].month == reference_date.month
        and appointment["statusKey"] != "cancelled"
    ]


def _weekly_volume(appointments, professional_id, reference_date):
    week_start = reference_date - timedelta(days=reference_date.weekday())
    confirmed = [0] * 7
    pending = [0] * 7
    for appointment in appointments:
        if appointment["statusKey"] not in ("confirmed", "pending"):
            continue
        seen = set()
        for item in appointment["items"]:
            if professional_id and item["professional"]["id"] != professional_id:
                continue
            schedule_date = item["start"].date()
            if week_start <= schedule_date < week_start + timedelta(days=7):
                key = (schedule_date, item["professional"]["id"])
                if key in seen:
                    continue
                seen.add(key)
                target = confirmed if appointment["statusKey"] == "confirmed" else pending
                target[schedule_date.weekday()] += 1
    return {
        "weekStart": week_start.isoformat(),
        "labels": WEEKDAY_LABELS,
        "confirmed": confirmed,
        "pending": pending,
    }


def _cliente_abreviado(nome):
    partes = str(nome or "Cliente").split()
    return f"{partes[0]} {partes[-1][0]}." if len(partes) > 1 else partes[0]


def _unconfirmed(appointments, professional_id, reference_date):
    itens = []
    hoje_pendentes = set()
    semana_anterior_pendentes = set()
    limite = reference_date + timedelta(days=7)
    semana_anterior = reference_date - timedelta(days=7)
    for appointment in appointments:
        if appointment["statusKey"] != "pending":
            continue
        for item in appointment["items"]:
            if professional_id and item["professional"]["id"] != professional_id:
                continue
            data_agendada = item["start"].date()
            chave = (appointment["id"], item["professional"]["id"])
            if data_agendada == reference_date:
                hoje_pendentes.add(chave)
            if data_agendada == semana_anterior:
                semana_anterior_pendentes.add(chave)
            if reference_date <= data_agendada <= limite:
                itens.append(
                    {
                        "appointmentId": str(appointment["id"]),
                        "client": _cliente_abreviado(appointment.get("clientName")),
                        "service": item["service"],
                        "professionalId": item["professional"]["id"],
                        "date": data_agendada.isoformat(),
                        "time": item["start"].strftime("%H:%M"),
                    }
                )
    itens.sort(key=lambda item: (item["date"], item["time"], item["appointmentId"]))
    delta = len(hoje_pendentes) - len(semana_anterior_pendentes)
    return {"deltaVsLastWeek": delta, "items": itens}


def _receita_e_servicos(dados, appointments, professional_id, reference_date):
    receitas_por_agendamento = _payment_totals(dados, reference_date)
    itens_mes = _current_month_items(appointments, reference_date)
    servicos = {}
    valores_profissional = defaultdict(Decimal)
    quantidade_agendamentos = 0

    por_agendamento = defaultdict(list)
    for appointment, item in itens_mes:
        por_agendamento[appointment["id"]].append((appointment, item))

    for appointment_id, pares in por_agendamento.items():
        pares_filtrados = [
            (appointment, item)
            for appointment, item in pares
            if not professional_id
            or item["professional"]["id"] == professional_id
        ]
        if not pares_filtrados:
            continue
        quantidade_agendamentos += len(pares_filtrados)
        valor_total = receitas_por_agendamento.get(appointment_id, Decimal("0"))
        valor_itens = _distribuir_valor(
            valor_total, [item for _, item in pares]
        )
        for _, item in pares_filtrados:
            nome = item["service"]
            entrada = servicos.setdefault(
                nome, {"appointments": 0, "revenue": Decimal("0")}
            )
            entrada["appointments"] += 1
            receita = valor_itens.get(item["itemId"], Decimal("0"))
            entrada["revenue"] += receita
            valores_profissional[item["professional"]["id"]] += receita

    lista_servicos = [
        {
            "name": nome,
            "appointments": valores["appointments"],
            "revenue": round(float(valores["revenue"]), 2),
        }
        for nome, valores in sorted(servicos.items())
    ]
    total = round(sum(servico["revenue"] for servico in lista_servicos), 2)
    ticket = round(total / quantidade_agendamentos, 2) if quantidade_agendamentos else 0
    por_profissional = [
        {
            "professionalId": item["id"],
            "value": round(float(valores_profissional.get(item["id"], Decimal("0"))), 2),
        }
        for item in dados["professionals"]
        if not professional_id or item["id"] == professional_id
    ]
    ano_anterior, mes_anterior = (
        (reference_date.year - 1, 12)
        if reference_date.month == 1
        else (reference_date.year, reference_date.month - 1)
    )
    pagamentos_mes_anterior = _payment_totals_month(
        dados, ano_anterior, mes_anterior
    )
    mes_anterior_total = _revenue_for_month(
        appointments,
        pagamentos_mes_anterior,
        ano_anterior,
        mes_anterior,
        professional_id,
    )
    return (
        lista_servicos,
        {
            "month": reference_date.strftime("%Y-%m"),
            "daysElapsed": reference_date.day,
            "total": total,
            "averageTicket": ticket,
            "changePercent": _rate_change(
                total, float(mes_anterior_total)
            ),
            "byProfessional": por_profissional,
        },
    )


def _rate_change(atual, anterior):
    if anterior == 0:
        return 0.0 if atual == 0 else 100.0
    return round(((atual - anterior) / anterior) * 100, 2)


def _no_show(appointments, professional_id, reference_date, chances):
    atual_inicio = reference_date - timedelta(days=90)
    anterior_inicio = reference_date - timedelta(days=180)
    contagem_atual = 0
    total_atual = 0
    contagem_anterior = 0
    total_anterior = 0
    heatmap = [[0 for _ in HEATMAP_SLOTS] for _ in range(7)]
    seen_periods = set()

    at_risk = []
    for appointment in appointments:
        first_item = appointment["items"][0]
        data_agendada = first_item["start"].date()
        if anterior_inicio <= data_agendada < atual_inicio and appointment["statusKey"] in ("no_show", "completed"):
            key = appointment["id"]
            if key not in seen_periods:
                seen_periods.add(key)
                total_anterior += 1
                contagem_anterior += appointment["statusKey"] == "no_show"
        elif atual_inicio <= data_agendada < reference_date and appointment["statusKey"] in ("no_show", "completed"):
            key = appointment["id"]
            if key not in seen_periods:
                seen_periods.add(key)
                total_atual += 1
                if appointment["statusKey"] == "no_show":
                    contagem_atual += 1
                    hora = first_item["start"].hour
                    for indice, (_, inicio, fim) in enumerate(HEATMAP_SLOTS):
                        if inicio <= hora < fim:
                            heatmap[first_item["start"].weekday()][indice] += 1

        if (
            appointment["statusKey"] not in ("confirmed", "pending")
            or not reference_date <= data_agendada <= reference_date + timedelta(days=30)
        ):
            continue
        chance = chances[appointment["id"]]
        if chance < 40:
            continue
        for item in appointment["items"]:
            if professional_id and item["professional"]["id"] != professional_id:
                continue
            at_risk.append(
                {
                    "appointmentId": str(appointment["id"]),
                    "client": _cliente_abreviado(appointment.get("clientName")),
                    "service": item["service"],
                    "professionalId": item["professional"]["id"],
                    "date": item["start"].date().isoformat(),
                    "time": item["start"].strftime("%H:%M"),
                    "leadTimeDays": _lead_time_days(appointment, item),
                    "confirmation": (
                        "Confirmado"
                        if appointment["statusKey"] == "confirmed"
                        else "Pendente"
                    ),
                    "risk": "Alto" if chance >= 70 else "Médio",
                    "probability": int(round(chance)),
                }
            )
    at_risk.sort(
        key=lambda item: (
            -item["probability"],
            item["date"],
            item["time"],
            item["appointmentId"],
        )
    )
    taxa_atual = contagem_atual / total_atual if total_atual else 0
    taxa_anterior = contagem_anterior / total_anterior if total_anterior else 0
    return {
        "windowDays": 90,
        "changePercent": _rate_change(taxa_atual, taxa_anterior),
        "heatmap": {
            "days": WEEKDAY_LABELS,
            "slots": [item[0] for item in HEATMAP_SLOTS],
            "values": heatmap,
        },
        "atRisk": at_risk,
    }


def _lead_time_days(appointment, item):
    created_at = appointment.get("createdAt")
    if not created_at:
        raise ValueError(
            f"Data de criação ausente para o agendamento {appointment['id']}"
        )
    return max(
        0,
        (item["start"].date() - _datetime_local(created_at).date()).days,
    )


def _sobreposicao_horas(inicio_a, fim_a, inicio_b, fim_b):
    inicio = max(inicio_a, inicio_b)
    fim = min(fim_a, fim_b)
    return max(0.0, (fim - inicio).total_seconds() / 3600)


def _capacidade(
    dados, appointments, professional_id, inicio, fim, granularidade, reference_date
):
    weekday_labels = {}
    for item in dados.get("workingDays", []):
        chave = str(item.get("profissional_id"))
        if professional_id and chave not in dados["professionalIdsBySlug"][professional_id]:
            continue
        dia = _weekday_numero(item.get("dia_da_semana"))
        hora_inicio = _hora(item.get("hora_inicio"))
        hora_fim = _hora(item.get("hora_fim"))
        if hora_inicio is None or hora_fim is None or hora_fim <= hora_inicio:
            raise ValueError(f"Horário de trabalho inválido: {item}")
        weekday_labels.setdefault(chave, []).append((dia, hora_inicio, hora_fim))

    if granularidade == "weekday":
        labels = WEEKDAY_LABELS
        bucket_for = lambda current: current.weekday()
    elif granularidade == "week":
        semanas = max(1, (fim - inicio).days // 7 + 1)
        labels = [f"Sem {indice + 1}" for indice in range(semanas)]
        bucket_for = lambda current: min((current - inicio).days // 7, len(labels) - 1)
    else:
        meses = []
        atual = date(inicio.year, inicio.month, 1)
        while atual <= fim:
            meses.append(atual.strftime("%b"))
            ano, mes = _mes_seguinte(atual.year, atual.month)
            atual = date(ano, mes, 1)
        labels = meses

        def bucket_for(current):
            return (current.year - inicio.year) * 12 + current.month - inicio.month

    total = [0.0] * len(labels)
    utilizado = [0.0] * len(labels)
    for offset in range((fim - inicio).days + 1):
        dia = inicio + timedelta(days=offset)
        indice = bucket_for(dia)
        for sql_professional_id, horarios in weekday_labels.items():
            for weekday, comeco, final in horarios:
                if weekday != dia.weekday():
                    continue
                inicio_dt = datetime.combine(dia, comeco)
                fim_dt = datetime.combine(dia, final)
                disponibilidade = (fim_dt - inicio_dt).total_seconds() / 3600
                for bloqueio in dados.get("blocks", []):
                    if str(bloqueio.get("profissional_id")) != sql_professional_id:
                        continue
                    if not bloqueio.get("inicio") or not bloqueio.get("fim"):
                        continue
                    inicio_bloqueio = _datetime_local(bloqueio["inicio"]).replace(tzinfo=None)
                    fim_bloqueio = _datetime_local(bloqueio["fim"]).replace(tzinfo=None)
                    disponibilidade -= _sobreposicao_horas(
                        inicio_dt, fim_dt, inicio_bloqueio, fim_bloqueio
                    )
                total[indice] += max(0.0, disponibilidade)

    for appointment in appointments:
        if appointment["statusKey"] not in ("confirmed", "pending", "completed"):
            continue
        for item in appointment["items"]:
            if professional_id and item["professional"]["id"] != professional_id:
                continue
            dia = item["start"].date()
            if not inicio <= dia <= fim:
                continue
            if dia < reference_date and appointment["statusKey"] != "completed":
                continue
            indice = bucket_for(dia)
            utilizado[indice] += item["durationMinutes"] / 60

    ocioso = [round(max(0.0, total[i] - utilizado[i]), 2) for i in range(len(total))]
    total_horas = sum(total)
    percentual = round(sum(ocioso) / total_horas * 100, 2) if total_horas else 0.0
    return {
        "idleCapacity": percentual,
        "changePercent": 0.0,
        "capacity": {
            "labels": labels,
            "totalHours": [round(value, 2) for value in total],
            "utilizedHours": [round(value, 2) for value in utilizado],
            "idleHours": ocioso,
        },
    }


def _periodo_idle(dados, appointments, professional_id, referencia):
    fim_seis_meses = referencia + timedelta(days=182)
    definicoes = {
        "30d": (referencia, referencia + timedelta(days=29), "weekday"),
        "90d": (referencia, referencia + timedelta(days=89), "week"),
        "6m": (referencia, fim_seis_meses, "month"),
    }
    resultado = {}
    for nome, (inicio, fim, granularidade) in definicoes.items():
        atual = _capacidade(
            dados,
            appointments,
            professional_id,
            inicio,
            fim,
            granularidade,
            referencia,
        )
        duracao = (fim - inicio).days + 1
        anterior = _capacidade(
            dados,
            appointments,
            professional_id,
            inicio - timedelta(days=duracao),
            inicio - timedelta(days=1),
            granularidade,
            referencia,
        )
        atual["changePercent"] = _rate_change(
            atual["idleCapacity"], anterior["idleCapacity"]
        )
        resultado[nome] = atual
    return resultado


def _montar_fatia(
    dados, appointments, professional_id, reference_date, chances
):
    servicos, receita = _receita_e_servicos(
        dados, appointments, professional_id, reference_date
    )
    return {
        "weeklyVolume": _weekly_volume(
            appointments, professional_id, reference_date
        ),
        "unconfirmed": _unconfirmed(
            appointments, professional_id, reference_date
        ),
        "services": servicos,
        "revenue": receita,
        "idle": _periodo_idle(
            dados, appointments, professional_id, reference_date
        ),
        "noShow": _no_show(
            appointments, professional_id, reference_date, chances
        ),
    }


def gerar_dashboard(dados, schema, agora=None):
    if schema.get("$id") != "studio-many/dashboard-data/1.0.0":
        raise ValueError("O JSON Schema informado não corresponde à versão 1.0.0.")
    fuso = ZoneInfo(TIMEZONE_NAME)
    agora = agora or datetime.now(fuso)
    if agora.tzinfo is None:
        agora = agora.replace(tzinfo=fuso)
    reference_date = agora.astimezone(fuso).date()
    profissionais, appointments, _ = _appointment_records(dados, reference_date)
    history = _historico_por_cliente(appointments, reference_date)

    active_future = [
        appointment
        for appointment in appointments
        if appointment["statusKey"] in ("confirmed", "pending")
        and reference_date
        <= appointment["items"][0]["start"].date()
        <= reference_date + timedelta(days=30)
    ]
    chances = {
        appointment["id"]: _chance_por_agendamento(
            appointment, history, reference_date
        )
        for appointment in active_future
    }

    professional_ids_by_slug = defaultdict(set)
    for sql_id, professional in profissionais.items():
        professional_ids_by_slug[professional["id"]].add(sql_id)
    dados = {
        **dados,
        "professionals": list(profissionais.values()),
        "professionalIdsBySlug": professional_ids_by_slug,
    }

    gerado_em = agora.astimezone(fuso).isoformat(timespec="seconds")
    dashboard = {
        "schemaVersion": "1.0.0",
        "generatedAt": gerado_em,
        "timezone": TIMEZONE_NAME,
        "referenceDate": reference_date.isoformat(),
        "professionals": list(profissionais.values()),
        "byProfessional": {},
    }
    dashboard["byProfessional"]["all"] = _montar_fatia(
        dados, appointments, None, reference_date, chances
    )
    for professional in profissionais.values():
        dashboard["byProfessional"][professional["id"]] = _montar_fatia(
            dados,
            appointments,
            professional["id"],
            reference_date,
            chances,
        )
    return dashboard


def _ler_uri_s3(uri):
    correspondencia = re.fullmatch(r"s3://([^/]+)/(.+)", uri)
    if not correspondencia:
        raise ValueError(f"URI S3 inválida: {uri}")
    return correspondencia.group(1), correspondencia.group(2)


def processar(bucket_silver, bucket_gold, schema_uri):
    cliente_s3 = criar_cliente_s3()
    objetos = []
    paginator = cliente_s3.get_paginator("list_objects_v2")
    for pagina in paginator.paginate(Bucket=bucket_silver, Prefix="dashboard/"):
        objetos.extend(
            objeto
            for objeto in pagina.get("Contents", [])
            if re.fullmatch(
                r"dashboard/data=\d{4}-\d{2}-\d{2}/dashboard\.json",
                objeto["Key"],
            )
        )
    if not objetos:
        raise RuntimeError(
            f"Nenhum snapshot Silver encontrado em s3://{bucket_silver}/dashboard/"
        )
    mais_recente = max(
        objetos,
        key=lambda item: item.get("LastModified", datetime.min.replace(tzinfo=timezone.utc)),
    )
    resposta = cliente_s3.get_object(Bucket=bucket_silver, Key=mais_recente["Key"])
    with resposta["Body"] as corpo:
        dados = json.loads(corpo.read().decode("utf-8"))

    bucket_schema, chave_schema = _ler_uri_s3(schema_uri)
    resposta_schema = cliente_s3.get_object(Bucket=bucket_schema, Key=chave_schema)
    with resposta_schema["Body"] as corpo:
        schema_bytes = corpo.read()
        schema = json.loads(schema_bytes.decode("utf-8"))

    dashboard = gerar_dashboard(dados, schema)
    correspondencia = re.fullmatch(
        r"dashboard/data=(\d{4}-\d{2}-\d{2})/dashboard\.json",
        mais_recente["Key"],
    )
    if correspondencia is None:
        raise ValueError(f"Partição Silver inválida: {mais_recente['Key']}")
    data_particao = dashboard.get("referenceDate") or correspondencia.group(1)
    cliente_s3.put_object(
        Bucket=bucket_gold,
        Key=f"dashboard/data={data_particao}/dashboard-data.json",
        Body=json.dumps(dashboard, ensure_ascii=False).encode("utf-8"),
        ContentType="application/json; charset=utf-8",
    )
    cliente_s3.put_object(
        Bucket=bucket_gold,
        Key="dashboard/dashboard-data.schema.json",
        Body=schema_bytes,
        ContentType="application/schema+json; charset=utf-8",
    )
    return len(dashboard["professionals"])


def main():
    parser = argparse.ArgumentParser(
        description="Gera os JSONs da dashboard e publica na Gold."
    )
    parser.add_argument("--silver-bucket", default=os.getenv("SILVER_BUCKET"))
    parser.add_argument("--gold-bucket", default=os.getenv("GOLD_BUCKET"))
    parser.add_argument(
        "--schema-s3-uri", default=os.getenv("DASHBOARD_SCHEMA_S3_URI")
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
    parser.add_argument("--extra-py-files")
    args = parser.parse_args()
    if not args.silver_bucket or not args.gold_bucket or not args.schema_s3_uri:
        parser.error(
            "--silver-bucket, --gold-bucket e --schema-s3-uri são obrigatórios"
        )
    try:
        quantidade = processar(
            args.silver_bucket, args.gold_bucket, args.schema_s3_uri
        )
    except (BotoCoreError, ClientError, UnicodeDecodeError):
        raise
    print(f"Dashboard Gold atualizada com {quantidade} profissionais.")


if __name__ == "__main__":
    main()
