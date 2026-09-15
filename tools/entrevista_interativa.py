"""
Tool para conduzir entrevistas estruturadas com o usuário.

Cada item da lista aceita:
  - contexto  (opcional): texto exibido antes da pergunta — narração, situação, resumo
  - pergunta  (obrigatório): a pergunta em si, curta e direta
  - opcoes    (opcional): lista de opções — vira botões na TUI, lista numerada na CLI

Exemplo com contexto:
  '[{"contexto": "O ar é pesado...", "pergunta": "O que você faz?", "opcoes": ["Avançar", "Recuar"]}]'

Exemplo simples (sem contexto):
  '[{"pergunta": "Qual seu SO?", "opcoes": ["Windows", "Linux", "Mac"]}]'
"""

INTERACTIVE = True

import json
import re


def _parse_perguntas(raw: str) -> list:
    """
    Parse tolerante do JSON de perguntas.
    Tenta json.loads direto; se falhar, tenta recuperar os objetos individualmente
    via regex — útil quando texto narrativo longo contém aspas ou caracteres especiais
    que quebram o JSON gerado pelo modelo.
    """
    # tentativa normal
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # fallback: extrai objetos {...} individualmente
    resultado = []
    for match in re.finditer(r'\{.*?\}', raw, re.DOTALL):
        bloco = match.group(0)
        try:
            resultado.append(json.loads(bloco))
            continue
        except json.JSONDecodeError:
            pass
        # recupera campos individualmente se o bloco ainda estiver quebrado
        item = {}
        for campo in ("contexto", "pergunta"):
            m = re.search(rf'"{campo}"\s*:\s*"(.*?)"(?=\s*[,}}])', bloco, re.DOTALL)
            if m:
                item[campo] = m.group(1)
        opcoes_m = re.search(r'"opcoes"\s*:\s*\[(.*?)\]', bloco, re.DOTALL)
        if opcoes_m:
            item["opcoes"] = re.findall(r'"([^"]+)"', opcoes_m.group(1))
        if "pergunta" in item:
            resultado.append(item)

    return resultado


def run(perguntas: str, perguntar=None) -> str:
    """
    perguntas: string JSON contendo a lista de perguntas.
    Cada item pode ter: contexto (opcional), pergunta (obrigatório), opcoes (opcional).
    """
    if perguntar is None:
        return (
            "Erro: esta tool precisa rodar num harness que suporte INTERACTIVE "
            "(o argumento 'perguntar' não foi injetado)."
        )
    try:
        lista_perguntas = _parse_perguntas(perguntas)
        if not lista_perguntas:
            return "Erro: não foi possível interpretar o parâmetro 'perguntas' como lista JSON."

        respostas = []
        for item in lista_perguntas:
            contexto = item.get("contexto", "").strip()
            pergunta = item.get("pergunta", "").strip()
            opcoes   = item.get("opcoes") or None

            # exibe contexto antes da pergunta, se houver
            if contexto:
                pergunta_completa = f"{contexto}\n\n{pergunta}" if pergunta else contexto
            else:
                pergunta_completa = pergunta

            respostas.append(perguntar(pergunta_completa, opcoes))

        return json.dumps({"status": "concluído", "respostas": respostas}, ensure_ascii=False)
    except Exception as e:
        return f"Erro durante a entrevista: {str(e)}"