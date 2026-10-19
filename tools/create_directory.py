"""Cria uma pasta (e os diretórios pais) no workspace."""

PERMISSIONS = {"path": "write"}

from pathlib import Path


def run(path: str) -> str:
    """
    path: caminho da pasta a criar, relativo ao workspace
    """
    if not str(path or "").strip():
        return "Erro: path vazio."

    target = Path(path).expanduser()
    try:
        if target.exists():
            if target.is_dir():
                return f"Pasta já existe: {path}"
            return f"Erro: '{path}' já existe e não é uma pasta."

        target.mkdir(parents=True, exist_ok=True)
        return f"Pasta criada: {path}"
    except Exception as exc:
        return f"Erro ao criar pasta '{path}': {exc}"
