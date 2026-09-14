"""
Tool para conduzir entrevistas estruturadas com o usuário.
"""

INTERACTIVE = True

import json


def run(perguntas: str, perguntar=None) -> str:
    """
    perguntas: string JSON contendo a lista de perguntas e alternativas.
    Exemplo: '[{"pergunta": "Qual seu SO?", "opcoes": ["Windows", "Linux", "Mac"]}]'
    """
    if perguntar is None:
        return (
            "Erro: esta tool precisa rodar num harness que suporte INTERACTIVE "
            "(o argumento 'perguntar' não foi injetado)."
        )
    try:
        lista_perguntas = json.loads(perguntas)
        if not isinstance(lista_perguntas, list):
            return "Erro: O parâmetro 'perguntas' deve ser uma lista JSON."

        respostas = []
        for item in lista_perguntas:
            pergunta = item.get("pergunta", "")
            opcoes = item.get("opcoes") or None
            respostas.append(perguntar(pergunta, opcoes))

        return json.dumps({"status": "concluído", "respostas": respostas}, ensure_ascii=False)
    except Exception as e:
        return f"Erro durante a entrevista: {str(e)}"
