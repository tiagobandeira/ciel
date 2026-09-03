"""
Carrega personas de agentes a partir de arquivos .md em /agents/.

Formato do .md:
  # Nome do Agente          ← título (obrigatório)
  ## Persona                ← bloco de personalidade/contexto
  ## Tools permitidas       ← 'todas' ou lista de nomes separados por vírgula/newline
  ## Servidores MCP         ← 'todos', 'nenhum' ou lista de nomes de servidores
  ## Comportamento          ← regras adicionais pro prompt
  ## Formato de resposta    ← override do formato JSON (opcional)
  ## Skills                 ← skills atreladas à persona (opcional)
                              formato: <nome-da-skill>: <nível>
                              níveis: obrigatoria | sugerida | opcional
"""

import re
from pathlib import Path

AGENTS_DIR = Path(__file__).parent / "agents"

# Formato padrão injetado se o .md não tiver "## Formato de resposta"
DEFAULT_JSON_FORMAT = """
## Formato de resposta (obrigatório)
Responda SEMPRE em JSON puro, sem texto adicional, sem markdown:

Se precisar usar uma tool:
{"tool": "nome_da_tool", "args": {...}}

Se a tarefa estiver concluída:
{"done": true, "message": "mensagem curta pro usuário"}
"""

# Níveis de prioridade de skill e a instrução correspondente injetada no prompt.
# Adicione ou ajuste níveis aqui — o texto vai direto pro orquestrador.
SKILL_LEVELS: dict[str, str] = {
    "obrigatoria": (
        "use sempre que a tarefa se encaixar nessa skill — "
        "não espere o usuário pedir, chame secondary_model com essa skill automaticamente"
    ),
    "sugerida": (
        "considere usar quando a tarefa se encaixar — "
        "você decide se é necessário antes de responder"
    ),
    "opcional": (
        "disponível para uso via comando do usuário ou decisão própria — "
        "comportamento padrão de skill"
    ),
}

# Nível aplicado quando a skill é listada no agente sem nível explícito
_DEFAULT_SKILL_LEVEL = "opcional"


def list_agents() -> list[str]:
    """Retorna nomes dos agentes disponíveis (sem extensão)."""
    return sorted(p.stem for p in AGENTS_DIR.glob("*.md"))


def _parse_sections(text: str) -> dict[str, str]:
    """
    Divide o .md em seções pelo padrão '## Título'.
    Retorna dict {título_lowercase: conteúdo}.
    """
    sections: dict[str, str] = {}
    # título principal (# Título)
    title_match = re.match(r"^#\s+(.+)", text.strip())
    if title_match:
        sections["__title__"] = title_match.group(1).strip()

    # seções secundárias (## Título)
    parts = re.split(r"^##\s+", text, flags=re.MULTILINE)
    for part in parts[1:]:
        lines = part.strip().splitlines()
        key = lines[0].strip().lower()
        value = "\n".join(lines[1:]).strip()
        sections[key] = value

    return sections


def _parse_allowed_tools(raw: str) -> list[str] | None:
    """
    Retorna None se 'todas', ou lista de nomes de tools.
    Aceita vírgulas ou newlines como separadores.
    """
    raw = raw.strip().lower()
    if raw in ("todas", "all", "*"):
        return None  # None = sem restrição
    names = re.split(r"[,\n]+", raw)
    return [n.strip().strip("-").strip() for n in names if n.strip()]


def _parse_skills(raw: str) -> list[dict]:
    """
    Parseia a seção '## Skills' do agente.

    Formato aceito (uma skill por linha):
      frontend-visual: obrigatoria
      code-review: sugerida
      data-analysis            ← sem nível → cai em _DEFAULT_SKILL_LEVEL

    Retorna lista de dicts:
      [{"name": "frontend-visual", "level": "obrigatoria"}, ...]

    Linhas em branco e comentários (#) são ignorados.
    Níveis desconhecidos caem em _DEFAULT_SKILL_LEVEL com aviso no stderr.
    """
    import sys

    skills: list[dict] = []
    for raw_line in raw.splitlines():
        line = raw_line.strip().strip("-").strip()
        if not line or line.startswith("#"):
            continue

        if ":" in line:
            name, _, level_raw = line.partition(":")
            name = name.strip()
            level = level_raw.strip().lower()
        else:
            name = line
            level = _DEFAULT_SKILL_LEVEL

        if not name:
            continue

        if level not in SKILL_LEVELS:
            print(
                f"[agent_loader] nível de skill desconhecido '{level}' "
                f"em '{name}' — usando '{_DEFAULT_SKILL_LEVEL}'",
                file=sys.stderr,
            )
            level = _DEFAULT_SKILL_LEVEL

        skills.append({"name": name, "level": level})

    return skills


def _build_skills_block(skills: list[dict]) -> str:
    """
    Monta o bloco de texto injetado no system prompt do orquestrador.
    Retorna string vazia se não houver skills.
    """
    if not skills:
        return ""

    lines = ["## Skills desta persona"]
    lines.append(
        "Você tem as seguintes skills disponíveis. "
        "Respeite o nível de cada uma ao decidir quando usá-las:\n"
    )
    for skill in skills:
        instruction = SKILL_LEVELS[skill["level"]]
        lines.append(f"- **{skill['name']}** [{skill['level']}]: {instruction}")

    lines.append(
        "\nPara usar uma skill, passe `skill=\"<nome>\"` na chamada a `secondary_model`."
    )
    return "\n".join(lines)


def load_agent(agent_name: str) -> dict:
    """
    Carrega e parseia o .md do agente.

    Retorna:
      {
        "name": str,
        "id": str,
        "system_prompt": str,        ← prompt montado pronto pra usar
        "allowed_tools": list | None, ← None = todas
        "description": str,          ← linha de descrição curta
        "skills": list[dict],        ← [{"name": str, "level": str}, ...]
      }
    """
    path = AGENTS_DIR / f"{agent_name}.md"
    if not path.exists():
        available = list_agents()
        raise FileNotFoundError(
            f"Agente '{agent_name}' não encontrado. "
            f"Disponíveis: {available}"
        )

    text = path.read_text(encoding="utf-8")
    sections = _parse_sections(text)

    name        = sections.get("__title__", agent_name)
    persona     = sections.get("persona", "")
    tools_raw   = sections.get("tools permitidas", "todas")
    mcp_raw     = sections.get("servidores mcp", "todos")
    behavior    = sections.get("comportamento", "")
    fmt         = sections.get("formato de resposta", "")
    skills_raw  = sections.get("skills", "")
    description = persona.splitlines()[0] if persona else "(sem descrição)"

    allowed_tools       = _parse_allowed_tools(tools_raw)
    allowed_mcp_servers = _parse_allowed_mcp_servers(mcp_raw)
    skills              = _parse_skills(skills_raw)
    skills_block        = _build_skills_block(skills)

    # Monta o system prompt
    parts = [f"# {name}\n"]
    if persona:
        parts.append(persona)
    if behavior:
        parts.append(f"\n## Regras de comportamento\n{behavior}")
    if skills_block:
        parts.append(f"\n{skills_block}")
    if fmt:
        parts.append(f"\n## Formato de resposta\n{fmt}")
    else:
        parts.append(DEFAULT_JSON_FORMAT)

    system_prompt = "\n".join(parts)

    return {
        "name":                name,
        "id":                  agent_name,
        "system_prompt":       system_prompt,
        "allowed_tools":       allowed_tools,
        "allowed_mcp_servers": allowed_mcp_servers,
        "description":         description,
        "skills":              skills,
    }


# Tools sempre disponíveis em qualquer agente — não precisam ser listadas no .md
CORE_TOOLS = {
    "read_file", "write_file", "list_directory", "search_files",
    "list_sources", "search_knowledge", "read_source",
    "calculator", "get_local_datetime",
    "create_tool", "run_script", "install_tool", "http_request",
    "web_search_extended", "temp_log",
    "secondary_model","list_skills"
}


def filter_tools(tools: dict, allowed: list | None) -> dict:
    """
    Filtra o dict de tools pelo allowed_tools do agente.
    CORE_TOOLS são sempre incluídas, independente do que o agente define.
    """
    if allowed is None:
        return tools
    combined = CORE_TOOLS | set(allowed)
    return {k: v for k, v in tools.items() if k in combined}


def _parse_allowed_mcp_servers(raw: str) -> list[str] | None:
    """
    Parseia a seção '## Servidores MCP' do agente.

    Retorna:
      None          → sem restrição (todos os servidores conectados visíveis)
      []            → nenhum servidor MCP visível
      ["a", "b"]   → somente esses servidores visíveis

    Valores aceitos para "todos": todos, all, *
    Valores aceitos para "nenhum": nenhum, none, -
    Aceita vírgulas ou newlines como separadores.
    """
    raw = raw.strip().lower()
    if raw in ("todos", "all", "*"):
        return None
    if raw in ("nenhum", "none", "-"):
        return []
    names = re.split(r"[,\n]+", raw)
    return [n.strip().strip("-").strip() for n in names if n.strip()]


def filter_mcp_tools(mcp_tools: dict, allowed_servers: list[str] | None) -> dict:
    """
    Filtra tools MCP pelo allowed_mcp_servers do agente.

    Tools MCP têm namespace 'mcp_{servidor}__{tool}'.

      allowed_servers=None  → todas as tools passam (sem restrição)
      allowed_servers=[]    → nenhuma tool MCP visível
      allowed_servers=[...] → só tools dos servidores listados

    Não afeta tools locais — só entradas cujo nome começa com 'mcp_' e
    contém '__' (namespace gerado pelo adapter MCP).
    """
    if allowed_servers is None:
        return mcp_tools
    allowed_set = set(allowed_servers)
    filtered = {}
    for tool_name, meta in mcp_tools.items():
        if tool_name.startswith("mcp_") and "__" in tool_name:
            # extrai nome do servidor: mcp_{servidor}__{tool}
            server_name = tool_name[len("mcp_"):tool_name.index("__")]
            if server_name in allowed_set:
                filtered[tool_name] = meta
        else:
            # tool local que por acaso começa com mcp_ (raro) — passa normalmente
            filtered[tool_name] = meta
    return filtered