"""Lista as skills disponíveis em skills/ com nome e descrição curta."""

from pathlib import Path
import re

_SKILLS_DIR = Path(__file__).parent.parent / "skills"


def _extract_metadata(text: str) -> dict:
    """
    Extrai description e mode do frontmatter YAML ou do corpo do arquivo.
    Retorna dict com chaves 'description' e 'mode'.
    """
    description = ""
    mode = ""

    # 1. frontmatter YAML (entre --- e ---)
    fm_match = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    if fm_match:
        fm = fm_match.group(1)
        d = re.search(r"^description:\s*(.+)$", fm, re.MULTILINE | re.IGNORECASE)
        m = re.search(r"^mode:\s*(\w+)$",        fm, re.MULTILINE | re.IGNORECASE)
        if d:
            description = d.group(1).strip()
        if m:
            mode = m.group(1).strip()

    # 2. fallback description — primeiro parágrafo após título
    if not description:
        d = re.search(r"^description:\s*(.+)$", text, re.MULTILINE | re.IGNORECASE)
        if d:
            description = d.group(1).strip()
        else:
            lines = text.splitlines()
            past_title = False
            for line in lines:
                stripped = line.strip()
                if not past_title:
                    if stripped.startswith("#"):
                        past_title = True
                    continue
                if stripped and not stripped.startswith("---"):
                    description = stripped[:120]
                    break

    return {"description": description, "mode": mode}


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
            text  = path.read_text(encoding="utf-8")
            meta  = _extract_metadata(text)
            desc  = meta["description"] or "sem descrição"
            mode  = f"  [mode: {meta['mode']}]" if meta["mode"] else ""
        except Exception:
            desc, mode = "erro ao ler arquivo", ""
        linhas.append(f"  - {path.stem}{mode}: {desc}")

    return "\n".join(linhas)