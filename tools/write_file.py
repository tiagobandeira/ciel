"""Escreve conteúdo em um arquivo de texto local (cria ou sobrescreve)."""

PERMISSIONS = {"path": "write"}

import json
from pathlib import Path


def run(path: str, content, mode: str = "overwrite") -> str:
    """
    path:    caminho do arquivo a escrever
    content: texto ou objeto JSON (dict/list) a serializar
    mode:    'overwrite' (padrão) | 'append'
    """
    if mode not in ("overwrite", "append"):
        return f"Erro: mode '{mode}' inválido. Use 'overwrite' ou 'append'."

    if not isinstance(content, str):
        try:
            content = json.dumps(content, ensure_ascii=False, indent=2)
        except (TypeError, ValueError) as exc:
            return f"Erro: conteúdo não é texto nem JSON serializável: {exc}"

    p = Path(path)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        open_mode = "w" if mode == "overwrite" else "a"
        with open(p, open_mode, encoding="utf-8") as f:
            f.write(content)
        action = "sobrescrito" if mode == "overwrite" else "atualizado (append)"
        return f"Arquivo {action} com sucesso: {path} ({len(content)} caracteres)"
    except Exception as e:
        return f"Erro ao escrever arquivo: {e}"
