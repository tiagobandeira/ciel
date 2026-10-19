"""Lista as skills disponíveis em skills/ com nome e descrição curta."""

from pathlib import Path

from skill_loader import extract_metadata as _extract_metadata

_SKILLS_DIR = Path(__file__).parent.parent / "skills"


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