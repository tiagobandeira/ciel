"""Copia um laboratório completo para um histórico nomeado."""

PERMISSIONS = {"source": "read", "dest": "write"}

import re
import shutil
from datetime import datetime
from pathlib import Path


def _slug(value: str) -> str:
    raw = re.sub(r"[^\w\-]+", "-", (value or "").strip().lower())
    return raw.strip("-") or "estudo"


def run(
    name: str = "",
    source: str = "data/labs/estudo",
    dest_dir: str = "data/labs/estudos",
    overwrite: bool = False,
) -> str:
    """
    name: nome do estudo; vazio = timestamp
    source: lab atual
    dest_dir: pasta dos estudos salvos
    overwrite: sobrescreve o destino exato
    """
    src = Path(source)
    if not src.is_dir():
        return f"Erro: lab '{source}' não encontrado."
    if not any(src.iterdir()):
        return f"Erro: lab '{source}' está vazio."

    base = Path(dest_dir)
    base.mkdir(parents=True, exist_ok=True)
    slug = _slug(name) if name else datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = base / slug
    if dest.exists() and not overwrite:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = base / f"{slug}_{stamp}"
    try:
        if dest.exists() and overwrite:
            shutil.rmtree(dest)
        shutil.copytree(src, dest)
    except Exception as exc:
        return f"Erro ao salvar estudo: {exc}"
    return f"Estudo salvo em: {dest}"
