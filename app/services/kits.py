from datetime import datetime, timezone, timedelta

from sqlalchemy.orm import Session

from app.db.models import KitFesta, RegistroAluguel

try:
    from zoneinfo import ZoneInfo
    LOCAL_TZ = ZoneInfo("America/Sao_Paulo")
except Exception:
    LOCAL_TZ = timezone(timedelta(hours=-3))


def _agora():
    return datetime.now(LOCAL_TZ)


def buscar_kit_por_nome(db: Session, tenant_id, nome: str):
    termo = (nome or "").strip()
    if not termo:
        return None

    termo_like = f"%{termo}%"

    return (
        db.query(KitFesta)
        .filter(
            KitFesta.tenant_id == tenant_id,
            KitFesta.ativo == True,
            (
                KitFesta.nome_kit.ilike(termo_like)
                | KitFesta.tema.ilike(termo_like)
                | KitFesta.categoria.ilike(termo_like)
                | KitFesta.codigo_kit.ilike(termo_like)
            )
        )
        .order_by(KitFesta.nome_kit.asc())
        .first()
    )


def obter_status_disponibilidade(db: Session, tenant_id, nome_kit: str):
    kit = buscar_kit_por_nome(db, tenant_id, nome_kit)
    if not kit:
        return None
    return kit.status_disponibilidade, kit


def obter_valor_locacao(db: Session, tenant_id, nome_kit: str):
    kit = buscar_kit_por_nome(db, tenant_id, nome_kit)
    if not kit:
        return None
    return kit.valor_locacao, kit


def obter_detalhes_kit(db: Session, tenant_id, nome_kit: str):
    kit = buscar_kit_por_nome(db, tenant_id, nome_kit)
    if not kit:
        return None, None

    detalhes = {
        "nome_kit": kit.nome_kit,
        "categoria": kit.categoria,
        "tema": kit.tema,
        "codigo_kit": kit.codigo_kit,
        "valor_locacao": kit.valor_locacao,
        "status_disponibilidade": kit.status_disponibilidade,
        "quantidade_itens": kit.quantidade_itens,
        "descricao": kit.descricao,
        "observacoes": kit.observacoes,
    }
    return detalhes, kit


def existe_conflito_reserva(
    db: Session,
    tenant_id,
    kit_id,
    data_reserva,
    data_entrega,
    ignorar_registro_id=None,
):
    query = (
        db.query(RegistroAluguel)
        .filter(
            RegistroAluguel.tenant_id == tenant_id,
            RegistroAluguel.kit_id == kit_id,
            RegistroAluguel.status != "cancelado",
            RegistroAluguel.data_reserva < data_entrega,
            RegistroAluguel.data_entrega > data_reserva,
        )
    )

    if ignorar_registro_id is not None:
        query = query.filter(RegistroAluguel.id != ignorar_registro_id)

    return query.first() is not None


def verificar_disponibilidade_por_data(db: Session, tenant_id, nome_kit: str, data_evento):
    kit = buscar_kit_por_nome(db, tenant_id, nome_kit)
    if not kit:
        return None

    conflito = (
        db.query(RegistroAluguel)
        .filter(
            RegistroAluguel.tenant_id == tenant_id,
            RegistroAluguel.kit_id == kit.id,
            RegistroAluguel.status != "cancelado",
            RegistroAluguel.data_reserva <= datetime.combine(data_evento, datetime.max.time()).replace(tzinfo=LOCAL_TZ),
            RegistroAluguel.data_entrega >= datetime.combine(data_evento, datetime.min.time()).replace(tzinfo=LOCAL_TZ),
        )
        .first()
    )

    return (conflito is None), kit


def atualizar_status_devolucao_atrasada(db: Session, registro: RegistroAluguel):
    if not registro:
        return False

    if (registro.status or "") not in ["reservado", "entregue"]:
        return False

    data_entrega = registro.data_entrega
    if not data_entrega:
        return False

    if data_entrega.tzinfo is None:
        data_entrega = data_entrega.replace(tzinfo=LOCAL_TZ)

    if _agora() > data_entrega:
        registro.status = "devolucao_atrasada"
        db.flush()
        return True

    return False


def sincronizar_disponibilidade_kit(db: Session, kit_id, tenant_id):
    kit = (
        db.query(KitFesta)
        .filter(
            KitFesta.id == kit_id,
            KitFesta.tenant_id == tenant_id,
        )
        .first()
    )
    if not kit:
        return None

    registros_ativos = (
        db.query(RegistroAluguel)
        .filter(
            RegistroAluguel.tenant_id == tenant_id,
            RegistroAluguel.kit_id == kit_id,
            RegistroAluguel.status.in_(["reservado", "entregue", "devolucao_atrasada"]),
        )
        .order_by(RegistroAluguel.data_reserva.asc())
        .all()
    )

    houve_alteracao = False
    for registro in registros_ativos:
        if atualizar_status_devolucao_atrasada(db, registro):
            houve_alteracao = True

    if houve_alteracao:
        registros_ativos = (
            db.query(RegistroAluguel)
            .filter(
                RegistroAluguel.tenant_id == tenant_id,
                RegistroAluguel.kit_id == kit_id,
                RegistroAluguel.status.in_(["reservado", "entregue", "devolucao_atrasada"]),
            )
            .order_by(RegistroAluguel.data_reserva.asc())
            .all()
        )

    if registros_ativos:
        kit.status_disponibilidade = "Indisponível"
    else:
        kit.status_disponibilidade = "Disponível"

    db.commit()
    return kit.status_disponibilidade