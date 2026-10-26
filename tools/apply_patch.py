"""Aplica um patch atômico de trechos exatos em um arquivo de texto."""

PERMISSIONS = {"path": "write"}

from pathlib import Path

MAX_HUNKS = 30


def run(path: str, hunks: list[dict], encoding: str = "utf-8") -> str:
    """
    path:    caminho do arquivo a editar
    hunks:   lista de {"old": "trecho exato", "new": "novo trecho"}
    encoding: encoding do arquivo (padrão utf-8)

    Aplica todos os hunks ou nenhum. Cada `old` precisa aparecer exatamente
    uma vez no arquivo; se algum falhar, nada é escrito.
    """
    p = Path(path)
    if not p.exists():
        return f"Erro: arquivo '{path}' não encontrado."
    if not p.is_file():
        return f"Erro: '{path}' não é um arquivo."
    if not isinstance(hunks, list) or not hunks:
        return "Erro: 'hunks' deve ser uma lista não vazia de {old, new}."
    if len(hunks) > MAX_HUNKS:
        return f"Erro: no máximo {MAX_HUNKS} hunks por chamada."

    try:
        original = p.read_text(encoding=encoding)
    except UnicodeDecodeError:
        return f"Erro: não foi possível decodificar '{path}' como {encoding}."
    except Exception as exc:
        return f"Erro ao ler arquivo: {exc}"

    content = original
    for index, hunk in enumerate(hunks, start=1):
        if not isinstance(hunk, dict):
            return f"Erro: hunk {index} não é um objeto {{old, new}}."
        old = hunk.get("old")
        new = hunk.get("new")
        if not isinstance(old, str) or not isinstance(new, str):
            return f"Erro: hunk {index} precisa de 'old' e 'new' como strings."
        if not old:
            return f"Erro: hunk {index} tem 'old' vazio."

        occurrences = content.count(old)
        if occurrences != 1:
            return (
                f"Erro: hunk {index} encontrou {occurrences} ocorrência(s) "
                f"do trecho 'old'. Nada foi escrito; use um trecho mais "
                f"específico (ou edit_file com count)."
            )
        content = content.replace(old, new, 1)

    try:
        p.write_text(content, encoding=encoding)
    except Exception as exc:
        return f"Erro ao escrever arquivo: {exc}"

    return (
        f"Arquivo atualizado: {path} "
        f"({len(hunks)} hunk(s); {len(original)} → {len(content)} caracteres)"
    )
