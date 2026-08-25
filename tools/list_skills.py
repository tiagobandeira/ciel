"""Lista as skills disponíveis em skills/ com nome e descrição curta."""

from pathlib import Path
import re

_SKILLS_DIR = Path(__file__).parent.parent / "skills"


def _extract_description(text: str) -> str:
    """
    Extrai a descrição da skill a partir do frontmatter YAML ou do
    primeiro parágrafo após o título.

    Aceita dois formatos:
      1) Frontmatter: description: <texto>
      2) Linha após o título (# Título\\n\\n<descrição>)
    """
    # 1. frontmatter YAML
    fm = re.search(r"^description:\s*(.+)$", text, re.MULTILINE | re.IGNORECASE)
    if fm:
        return fm.group(1).strip()

    # 2. primeiro parágrafo após título
    lines = text.splitlines()
    past_title = False
    for line in lines:
        stripped = line.strip()
        if not past_title:
            if stripped.startswith("#"):
                past_title = True
            continue
        if stripped:
            return stripped[:120]

    return "sem descrição"


def run() -> str:
    """
    Retorna lista formatada de skills disponíveis em skills/.
    Cada skill é um arquivo .md com nome e descrição extraída.
    """
    if not _SKILLS_DIR.exists():
        return "Pasta skills/ não encontrada. Crie skills/ na raiz do projeto."

    skills = sorted(_SKILLS_DIR.glob("*.md"))
    if not skills:
        return "Nenhuma skill disponível em skills/."

    linhas = ["Skills disponíveis:\n"]
    for path in skills:
        try:
            text = path.read_text(encoding="utf-8")
            desc = _extract_description(text)
        except Exception:
            desc = "erro ao ler arquivo"
        linhas.append(f"  - {path.stem}: {desc}")

    return "\n".join(linhas)
