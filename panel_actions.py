"""Ações de painel que o front pode disparar, por allowlist.

O manifesto do painel declara ações com `tipo` (`front` ou `tool`) e `acao`.
Ações `front` rodam no navegador; ações `tool` chegam em /api/painel_acao e
só são executadas se estiverem registradas aqui.
"""


def _atualizar_noticias(dados: dict):
    tema = " ".join(str(dados.get("tema") or "").split())[:80]
    if not tema:
        return False, "Tema da notícia ausente."
    try:
        limite = max(3, min(int(dados.get("limite") or 5), 8))
    except (TypeError, ValueError):
        limite = 5
    from ui_tools.ui_painel_noticias import run
    mensagem = run(tema, limite)
    if mensagem.startswith(("Erro", "Não encontrei")):
        return False, mensagem
    return True, mensagem


ACOES = {
    "atualizar_noticias": _atualizar_noticias,
}


def executar(acao: str, dados: dict):
    """Retorna (ok, mensagem). Ação desconhecida nunca é executada."""
    fn = ACOES.get(str(acao or ""))
    if fn is None:
        return False, "Ação de painel não permitida."
    try:
        return fn(dados if isinstance(dados, dict) else {})
    except Exception as e:
        return False, f"Erro ao executar a ação: {str(e)[:140]}"
