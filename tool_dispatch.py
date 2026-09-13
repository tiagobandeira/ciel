"""
tool_dispatch.py — fonte única de verdade sobre quais tools são "inseguras"
(bloqueadas no modo --safe) e quais exigem confirmação antes de executar,
mesmo fora do modo --safe.

Antes desse módulo, UNSAFE_TOOLS existia em três lugares diferentes
(cli.py, ciel_tui.py e implicitamente em agent_loop.py) e podia divergir
entre os harnesses. Agora cli.py, ciel_tui.py e agent_loop.py importam
tudo daqui.
"""

# Tools que executam ou geram/rodam código arbitrário.
# No modo --safe são removidas do registry ANTES do schema ser montado
# pro modelo — ou seja, o modelo nunca fica sabendo que elas existem,
# então não insiste tentando chamá-las. Esse já era o comportamento de
# run_script; create_tool e create_temp_tool entram aqui pelo mesmo motivo:
# ambas escrevem E importam (logo, executam) código Python novo via
# importlib, independente de run_script estar disponível ou não.
UNSAFE_TOOLS = {"run_script", "create_tool", "create_temp_tool"}

# Tools que, mesmo fora do modo --safe, escrevem e IMPORTAM código Python
# novo como parte da própria execução (_try_import_and_fix). Pedem
# confirmação explícita antes de rodar, a não ser que o usuário já tenha
# ativado o modo de confiança pra sessão atual (--trust-tools ou a opção
# "auto" no prompt de confirmação).
CONFIRM_BEFORE_RUN = {"create_tool", "create_temp_tool"}


def filter_unsafe(tools: dict, safe: bool) -> dict:
    """Remove tools inseguras do dict quando --safe está ativo. No-op se safe=False."""
    if not safe:
        return tools
    return {k: v for k, v in tools.items() if k not in UNSAFE_TOOLS}


def needs_confirmation(tool_name: str, trusted: bool) -> bool:
    """True se essa tool call deve ser confirmada com o usuário antes de rodar."""
    return tool_name in CONFIRM_BEFORE_RUN and not trusted
