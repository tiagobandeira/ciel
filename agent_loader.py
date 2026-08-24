"""
Carrega personas de agentes a partir de arquivos .md em /agents/.

Formato do .md:
  # Nome do Agente          ← título (obrigatório)
  ## Persona                ← bloco de personalidade/contexto
  ## Tools permitidas       ← 'todas' ou lista de nomes separados por vírgula/newline
  ## Comportamento          ← regras adicionais pro prompt
  ## Formato de resposta    ← override do formato JSON (opcional)
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

    name = sections.get("__title__", agent_name)
    persona = sections.get("persona", "")
    tools_raw = sections.get("tools permitidas", "todas")
    behavior = sections.get("comportamento", "")
    fmt = sections.get("formato de resposta", "")
    description = persona.splitlines()[0] if persona else "(sem descrição)"

    allowed_tools = _parse_allowed_tools(tools_raw)

    # Monta o system prompt
    parts = [f"# {name}\n"]
    if persona:
        parts.append(persona)
    if behavior:
        parts.append(f"\n## Regras de comportamento\n{behavior}")
    if fmt:
        parts.append(f"\n## Formato de resposta\n{fmt}")
    else:
        parts.append(DEFAULT_JSON_FORMAT)

    system_prompt = "\n".join(parts)

    return {
        "name": name,
        "id": agent_name,
        "system_prompt": system_prompt,
        "allowed_tools": allowed_tools,
        "description": description,
    }





# Tools sempre disponíveis em qualquer agente — não precisam ser listadas no .md
CORE_TOOLS = {
    "read_file", "write_file", "list_directory", "search_files",
    "list_sources", "search_knowledge", "read_source",
    "calculator", "get_local_datetime",
    "create_tool", "run_script", "install_tool", "http_request",
    "web_search_extended", "temp_log",
    "secondary_model"
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
