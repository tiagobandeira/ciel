"""Cria um notebook nbformat 4 válido a partir de células markdown/code."""

PERMISSIONS = {"path": "write"}

import json
import uuid
from pathlib import Path

MAX_CELLS = 200
CELL_TYPES = {"markdown", "code"}


def _source(value) -> str:
    if isinstance(value, list):
        return "\n".join(str(part) for part in value)
    return str(value or "")


def run(path: str, cells: list[dict], metadata: dict | None = None) -> str:
    """
    path: caminho do .ipynb
    cells: lista de {"type": "markdown"|"code", "source": "..."}
           (aceita "cell_type" no lugar de "type")
    metadata: metadados extras; Colab é adicionado por padrão
    """
    if not isinstance(cells, list) or not cells:
        return "Erro: 'cells' deve ser uma lista não vazia."
    if len(cells) > MAX_CELLS:
        return f"Erro: no máximo {MAX_CELLS} células."

    normalized = []
    for index, cell in enumerate(cells, start=1):
        if not isinstance(cell, dict):
            return f"Erro: célula {index} não é um objeto."
        kind = str(cell.get("type") or cell.get("cell_type") or "").strip().lower()
        if kind not in CELL_TYPES:
            return f"Erro: célula {index} tem tipo inválido ({kind!r})."
        source = _source(cell.get("source", cell.get("content", "")))
        base = {
            "cell_type": kind,
            "id": str(cell.get("id") or f"cell-{uuid.uuid4().hex[:10]}"),
            "metadata": dict(cell.get("metadata") or {}),
            "source": source,
        }
        if kind == "code":
            base["execution_count"] = None
            base["outputs"] = []
        normalized.append(base)

    nb_metadata = {
        "colab": {"provenance": [], "toc_visible": True},
        "kernelspec": {
            "display_name": "Python 3",
            "language": "python",
            "name": "python3",
        },
        "language_info": {"name": "python"},
    }
    if metadata:
        nb_metadata.update(metadata)

    notebook = {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": nb_metadata,
        "cells": normalized,
    }
    target = Path(path)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(notebook, ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
        loaded = json.loads(target.read_text(encoding="utf-8"))
        assert loaded["nbformat"] == 4 and loaded["cells"]
    except Exception as exc:
        return f"Erro ao criar notebook: {exc}"
    return (
        f"Notebook criado: {path} "
        f"({len(normalized)} células, {sum(1 for c in normalized if c['cell_type'] == 'code')} code)."
    )
