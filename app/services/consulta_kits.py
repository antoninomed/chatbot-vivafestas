import re
import unicodedata
from typing import Optional

from sqlalchemy.orm import Session

from app.db.models import KitFesta


PALAVRAS_IRRELEVANTES = {
    "kit", "kits", "tema", "temas", "decoracao", "decoração",
    "festa", "do", "da", "de", "o", "a", "os", "as", "um", "uma",
    "quero", "gostaria", "saber", "sobre", "valor", "preco", "preço",
    "custa", "quanto", "aluguel", "locacao", "locação", "tem",
    "disponivel", "disponível", "disponibilidade", "me", "fala",
    "informacao", "informação", "detalhes"
}


def normalizar_texto(txt: str) -> str:
    if not txt:
        return ""
    txt = unicodedata.normalize("NFKD", txt).encode("ascii", "ignore").decode("utf-8")
    txt = txt.lower().strip()
    txt = re.sub(r"[^\w\s]", " ", txt)
    txt = re.sub(r"\s+", " ", txt)
    return txt


def tokenizar(txt: str) -> list[str]:
    txt = normalizar_texto(txt)
    return [p for p in txt.split() if p and p not in PALAVRAS_IRRELEVANTES]


def formatar_valor_brl(valor) -> Optional[str]:
    if valor is None or valor == "":
        return None
    try:
        return f"R$ {float(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return str(valor)


def detectar_intencao_kit(mensagem: str) -> bool:
    msg = normalizar_texto(mensagem)

    gatilhos = [
        "kit", "tema", "decoracao", "decoração",
        "valor", "preco", "preço", "quanto custa", "quanto e", "quanto é",
        "aluguel", "locacao", "locação",
        "disponivel", "disponível", "disponibilidade",
        "tem o", "tem do", "vocês têm", "voces tem", "trabalham com"
    ]

    return any(g in msg for g in gatilhos)


def extrair_tipo_pergunta(mensagem: str) -> dict:
    msg = normalizar_texto(mensagem)

    quer_preco = any(p in msg for p in [
        "valor", "preco", "preço", "quanto custa", "quanto e", "quanto é", "custa", "aluguel", "locacao", "locação"
    ])

    quer_disponibilidade = any(p in msg for p in [
        "disponivel", "disponível", "disponibilidade", "tem disponivel", "tem disponível", "esta disponivel", "está disponível"
    ])

    quer_detalhes = any(p in msg for p in [
        "detalhes", "itens", "inclui", "acompanha", "descricao", "descrição", "observacoes", "observações"
    ])

    return {
        "quer_preco": quer_preco,
        "quer_disponibilidade": quer_disponibilidade,
        "quer_detalhes": quer_detalhes,
    }


def _nome_kit(kit: KitFesta) -> str:
    return getattr(kit, "nome_kit", None) or getattr(kit, "tema", None) or getattr(kit, "categoria", None) or "esse kit"


def pontuar_kit(kit: KitFesta, mensagem: str) -> float:
    mensagem_norm = normalizar_texto(mensagem)
    tokens_msg = set(tokenizar(mensagem))

    nome_kit = normalizar_texto(getattr(kit, "nome_kit", "") or "")
    tema = normalizar_texto(getattr(kit, "tema", "") or "")
    categoria = normalizar_texto(getattr(kit, "categoria", "") or "")
    descricao = normalizar_texto(getattr(kit, "descricao", "") or "")
    observacoes = normalizar_texto(getattr(kit, "observacoes", "") or "")

    tokens_nome = set(tokenizar(nome_kit))
    tokens_tema = set(tokenizar(tema))
    tokens_categoria = set(tokenizar(categoria))
    tokens_descricao = set(tokenizar(descricao))
    tokens_observacoes = set(tokenizar(observacoes))

    score = 0.0

    if nome_kit and nome_kit == mensagem_norm:
        score += 120
    if tema and tema == mensagem_norm:
        score += 100

    if nome_kit and nome_kit in mensagem_norm:
        score += 60
    if tema and tema in mensagem_norm:
        score += 50
    if categoria and categoria in mensagem_norm:
        score += 20

    score += len(tokens_msg & tokens_nome) * 15
    score += len(tokens_msg & tokens_tema) * 12
    score += len(tokens_msg & tokens_categoria) * 5
    score += len(tokens_msg & tokens_descricao) * 2
    score += len(tokens_msg & tokens_observacoes) * 1

    for palavra in tokens_msg:
        if palavra and palavra in nome_kit:
            score += 6
        if palavra and palavra in tema:
            score += 4

    return score


def buscar_kit_por_mensagem(db: Session, tenant_id: str, mensagem: str) -> Optional[KitFesta]:
    kits = (
        db.query(KitFesta)
        .filter(KitFesta.tenant_id == tenant_id)
        .all()
    )

    if not kits:
        return None

    melhor_kit = None
    melhor_score = 0.0

    for kit in kits:
        score = pontuar_kit(kit, mensagem)
        if score > melhor_score:
            melhor_score = score
            melhor_kit = kit

    if melhor_kit and melhor_score >= 8:
        return melhor_kit

    return None


def montar_resposta_kit(kit: KitFesta, mensagem: str) -> str:
    tipo = extrair_tipo_pergunta(mensagem)

    nome_kit = _nome_kit(kit)
    valor = formatar_valor_brl(getattr(kit, "valor_locacao", None))
    status = (getattr(kit, "status_disponibilidade", None) or "").strip()
    descricao = (getattr(kit, "descricao", None) or "").strip()
    observacoes = (getattr(kit, "observacoes", None) or "").strip()
    quantidade_itens = getattr(kit, "quantidade_itens", None)

    partes = []

    if tipo["quer_preco"]:
        if valor:
            partes.append(f"O kit *{nome_kit}* custa *{valor}* para locação.")
        else:
            partes.append(f"Encontrei o kit *{nome_kit}* em nosso catálogo, mas o valor ainda não está cadastrado.")

    if tipo["quer_disponibilidade"]:
        if status:
            partes.append(f"No momento, ele está com status: *{status}*.")
        else:
            partes.append("Posso verificar a disponibilidade dele para a data do seu evento.")

    if tipo["quer_detalhes"]:
        if quantidade_itens:
            partes.append(f"Esse kit possui *{quantidade_itens}* item(ns) cadastrados.")
        if descricao:
            partes.append(f"Descrição: {descricao}.")
        if observacoes:
            partes.append(f"Observações: {observacoes}.")

    if not partes:
        if valor and status:
            partes.append(f"Encontrei o kit *{nome_kit}* em nosso catálogo. O valor de locação é *{valor}* e o status atual é *{status}*.")
        elif valor:
            partes.append(f"Encontrei o kit *{nome_kit}* em nosso catálogo. O valor de locação é *{valor}*.")
        elif status:
            partes.append(f"Encontrei o kit *{nome_kit}* em nosso catálogo. No momento, ele está com status: *{status}*.")
        else:
            partes.append(f"Encontrei o kit *{nome_kit}* em nosso catálogo.")

    partes.append("Se quiser, também posso verificar a disponibilidade para a data do seu evento.")

    return " ".join(partes)


def responder_consulta_kit(db: Session, tenant_id: str, mensagem: str) -> Optional[str]:
    if not detectar_intencao_kit(mensagem):
        return None

    kit = buscar_kit_por_mensagem(db, tenant_id, mensagem)
    if not kit:
        return None

    return montar_resposta_kit(kit, mensagem)