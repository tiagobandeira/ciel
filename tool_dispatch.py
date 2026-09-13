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

# Tools cujo argumento aponta pra um caminho no disco são identificadas
# dinamicamente via PERMISSIONS, self-declarado no topo do arquivo de cada
# tool (mesmo padrão de REQUIREMENTS/EXTRA, lido por tools_registry.py) —
# não há mais uma lista central pra manter na mão. Isso cobre igual tools
# do core, tools extras (read_pdf, docx_*, etc.) e tools criadas via
# create_tool/create_temp_tool, desde que a tool declare:
#
#   PERMISSIONS = {"path": "read"}                    # um argumento
#   PERMISSIONS = {"caminho": "write", "saida": "write"}  # mais de um
#
# Critério de quando declarar: é o MODELO quem escolhe o path sozinho,
# numa tool cujo código ninguém revisou individualmente call a call. NÃO
# precisam declarar (ficam de fora por design, não por esquecimento):
#   - tools acionadas por comando explícito do usuário (/img, /source) —
#     o path já veio de intenção humana direta, não de exploração do modelo.
#   - create_tool/create_temp_tool — o path de escrita é interno e fixo
#     (tools/ ou tools/temp/), e o código em si já passa pela confirmação
#     de criação, um controle mais forte que checagem de path.
_VALID_PERMISSION_VALUES = {"read", "write"}


def get_path_checks(tool_name: str, tools: dict) -> list[tuple[str, bool]]:
    """
    Lê PERMISSIONS da tool (via metadata já carregado por tools_registry.py)
    e devolve [(nome_do_argumento, precisa_de_permissão_de_escrita), ...].
    Tool sem PERMISSIONS declarado devolve lista vazia — não é checada.
    """
    meta = tools.get(tool_name)
    if not meta:
        return []
    permissions = meta.get("permissions", {})
    checks = []
    for arg_name, level in permissions.items():
        if level not in _VALID_PERMISSION_VALUES:
            continue  # valor inválido — ignora em vez de quebrar o loop
        checks.append((arg_name, level == "write"))
    return checks


def filter_unsafe(tools: dict, safe: bool) -> dict:
    """Remove tools inseguras do dict quando --safe está ativo. No-op se safe=False."""
    if not safe:
        return tools
    return {k: v for k, v in tools.items() if k not in UNSAFE_TOOLS}


def needs_confirmation(tool_name: str, trusted: bool) -> bool:
    """True se essa tool call deve ser confirmada com o usuário antes de rodar."""
    return tool_name in CONFIRM_BEFORE_RUN and not trusted
