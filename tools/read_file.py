"""Lê o conteúdo de um arquivo de texto local, com suporte a trechos."""

PERMISSIONS = {"path": "read"}

from pathlib import Path

MAX_CHARS = 8_000  # limite padrão pra não explodir o contexto do modelo
MAX_LIMIT = 20_000  # teto por chamada quando o modelo pede um trecho grande


def run(
    path: str,
    offset: int = 0,
    limit: int = MAX_CHARS,
    encoding: str = "utf-8",
) -> str:
    """
    path:     caminho do arquivo a ler
    offset:   caractere inicial (0 = começo do arquivo)
    limit:    máximo de caracteres a retornar (padrão 8000, teto 20000)
    encoding: encoding do arquivo (padrão utf-8)
    """
    p = Path(path)
    if not p.exists():
        return f"Erro: arquivo '{path}' não encontrado."
    if not p.is_file():
        return f"Erro: '{path}' não é um arquivo."

    try:
        content = p.read_text(encoding=encoding)
    except UnicodeDecodeError:
        return f"Erro: não foi possível decodificar '{path}' como {encoding}. Tente outro encoding."
    except Exception as e:
        return f"Erro ao ler arquivo: {e}"

    total = len(content)
    try:
        start = int(offset)
    except (TypeError, ValueError):
        start = 0
    try:
        size = int(limit)
    except (TypeError, ValueError):
        size = MAX_CHARS

    start = max(0, min(start, total))
    size = max(1, min(size, MAX_LIMIT))
    end = min(start + size, total)

    chunk = content[start:end]
    if start > 0 or end < total:
        chunk += (
            f"\n\n[trecho {start}–{end} de {total} caracteres; "
            f"use offset={end} para continuar]"
        )
    return chunk
