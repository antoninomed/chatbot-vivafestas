import re

def normalizar_telefone(numero: str) -> str:
    """
    Remove tudo que não for número.
    Ex:
    +55 (85) 99123-4567 -> 5585991234567
    """

    if not numero:
        return ""

    numero = re.sub(r"\D", "", numero)

    return numero