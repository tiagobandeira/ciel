"""Lê o conteúdo de um arquivo de texto local."""

from pathlib import Path

MAX_CHARS = 8_000  # limite pra não explodir o contexto do modelo


def run(path: str, encoding: str = "utf-8") -> str:
    """
    path:     caminho do arquivo a ler
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

    if len(content) > MAX_CHARS:
        content = content[:MAX_CHARS] + f"\n\n[... truncado após {MAX_CHARS} caracteres ...]"

    return content
