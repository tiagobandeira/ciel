"""Copia um template de projeto para o workspace (scaffold determinístico)."""

PERMISSIONS = {"dest": "write"}

import re
import shutil
from pathlib import Path

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
_TEMPLATE_RE = re.compile(r"^[a-z0-9_-]+$")


def run(template: str, dest: str, overwrite: bool = False) -> str:
    """
    template: nome da pasta em templates/ (ex.: app_web, landing, game)
    dest:     pasta de destino no workspace
    overwrite: sobrescreve arquivos existentes (padrão: preserva)
    """
    name = (template or "").strip()
    if not _TEMPLATE_RE.match(name):
        return f"Erro: template inválido: {template!r}."
    source = TEMPLATES_DIR / name
    if not source.is_dir():
        disponiveis = sorted(p.name for p in TEMPLATES_DIR.iterdir() if p.is_dir()) if TEMPLATES_DIR.exists() else []
        return (
            f"Erro: template '{name}' não existe. "
            f"Disponíveis: {', '.join(disponiveis) or '(nenhum)'}."
        )

    target = Path(dest)
    try:
        target.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        return f"Erro ao criar destino '{dest}': {exc}"

    copied = 0
    skipped = 0
    errors: list[str] = []
    for item in source.rglob("*"):
        if not item.is_file():
            continue
        relative = item.relative_to(source)
        output = target / relative
        if output.exists() and not overwrite:
            skipped += 1
            continue
        try:
            output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, output)
            copied += 1
        except Exception as exc:
            errors.append(f"{relative}: {exc}")

    if errors:
        return (
            f"Template '{name}' aplicado parcialmente em {dest}: "
            f"{copied} copiado(s), {skipped} preservado(s), "
            f"erros: {'; '.join(errors)}"
        )
    return (
        f"Template '{name}' aplicado em {dest}: "
        f"{copied} arquivo(s) copiado(s), {skipped} preservado(s)."
    )
