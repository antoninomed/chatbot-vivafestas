from __future__ import annotations

def main_menu_list(company_name: str) -> tuple[str, str, list[dict]]:
    body = (
        f"Olá! 👋\n"
        f"Sou o atendimento automático da *Viva Festas*.\n\n"
        f"Selecione uma opção:"
    )

    button_text = "Abrir menu"

    sections = [
        {
            "title": "Locação",
            "rows": [
                {"id": "CATALOG", "title": "🎉 Ver kits", "description": "Catálogo e temas disponíveis"},
            ],
        },
        {
            "title": "Informações",
            "rows": [
                {"id": "LOCATION", "title": "📍 Localização", "description": "Endereço e localização da loja"},
            ],
        },
        {
            "title": "Operação",
            "rows": [
                {"id": "PAYMENT", "title": "💳 Pagamento", "description": "Sinal, formas de pagamento e prazos"},
                {"id": "ATTENDANT", "title": "👩‍💼 Falar com atendimento", "description": "Encaminhar para atendimento humano"},
            ],
        },
    ]

    return body, button_text, sections