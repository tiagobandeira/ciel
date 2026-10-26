"""Lê o conteúdo de um arquivo de texto local, com suporte a trechos."""

PERMISSIONS = {"path": "read"}

from pathlib import Path

MAX_CHARS = 8_000  # limite padrão pra não explodir o contexto do modelo
MAX_LIMIT = 20_000  # teto por chamada quando o modelo pede um trecho grande


def _numbered(text: str, first_line: int) -> str:
    lines = text.splitlines(keepends=True)
    if not lines:
        return text
    out = []
    for index, line in enumerate(lines, start=first_line):
        if line.endswith("\n"):
            out.append(f"{index:>5} | {line}")
        else:
            out.append(f"{index:>5} | {line}")
    return "".join(out)


def run(
    path: str,
    offset: int = 0,
    limit: int = MAX_CHARS,
    start_line: int = 0,
    end_line: int = 0,
    numbered: bool = False,
    encoding: str = "utf-8",
) -> str:
    """
    path:       caminho do arquivo a ler
    offset:     caractere inicial (0 = começo do arquivo)
    limit:      máximo de caracteres a retornar (padrão 8000, teto 20000)
    start_line: linha inicial 1-based; se > 0, ignora offset/limit
    end_line:   linha final inclusiva (0 = até o fim)
    numbered:   prefixa cada linha com o número (para patches/edições)
    encoding:   encoding do arquivo (padrão utf-8)
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

    # ── modo por linhas ──────────────────────────────────────────────────────
    if start_line or end_line:
        try:
            first = max(1, int(start_line or 1))
            last = int(end_line or 0)
        except (TypeError, ValueError):
            return "Erro: start_line/end_line devem ser inteiros."

        lines = content.splitlines(keepends=True)
        total_lines = len(lines)
        if last <= 0:
            last = total_lines
        last = min(last, total_lines)
        first = min(first, max(1, total_lines))
        chunk = "".join(lines[first - 1:last])
        if len(chunk) > MAX_LIMIT:
            chunk = chunk[:MAX_LIMIT] + "\n[... truncado ...]"
        if numbered:
            chunk = _numbered(chunk, first)
        header = (
            f"\n\n[linhas {first}–{last} de {total_lines}; "
            f"use start_line={last + 1} para continuar]"
        )
        return chunk + header

    # ── modo por caracteres ──────────────────────────────────────────────────
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
    if numbered:
        first_line = content.count("\n", 0, start) + 1
        chunk = _numbered(chunk, first_line)
    if start > 0 or end < total:
        chunk += (
            f"\n\n[trecho {start}–{end} de {total} caracteres; "
            f"use offset={end} para continuar]"
        )
    return chunk
