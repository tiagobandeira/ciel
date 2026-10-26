"""Escreve vários arquivos novos em uma única chamada, de forma atômica."""

PERMISSIONS = {"base": "write"}

from pathlib import Path

from tools.file_locks import lock_paths

MAX_FILES = 20


def run(
    base: str,
    files: list[dict],
    overwrite: bool = True,
    encoding: str = "utf-8",
) -> str:
    """
    base:     pasta raiz onde os arquivos serão criados
    files:    lista de {"path": "relativo/arquivo", "content": "texto"}
    overwrite: sobrescreve arquivos existentes (padrão: sim)
    encoding: encoding dos arquivos (padrão utf-8)

    Todos os arquivos são validados antes; se um falhar na escrita, os
    anteriores são restaurados (rollback).
    """
    if not isinstance(files, list) or not files:
        return "Erro: 'files' deve ser uma lista não vazia de {path, content}."
    if len(files) > MAX_FILES:
        return f"Erro: no máximo {MAX_FILES} arquivos por chamada."

    base_path = Path(base or ".").expanduser()
    try:
        base_path.mkdir(parents=True, exist_ok=True)
        base_resolved = base_path.resolve()
    except Exception as exc:
        return f"Erro ao preparar a pasta base '{base}': {exc}"
    if not base_resolved.is_dir():
        return f"Erro: '{base}' não é uma pasta."

    prepared: list[tuple[Path, str]] = []
    seen: set[Path] = set()
    skipped = 0
    for index, item in enumerate(files, start=1):
        if not isinstance(item, dict):
            return f"Erro: arquivo {index} não é um objeto {{path, content}}."
        raw_path = item.get("path")
        content = item.get("content")
        if not isinstance(raw_path, str) or not raw_path.strip():
            return f"Erro: arquivo {index} precisa de 'path' como string."
        if not isinstance(content, str):
            return f"Erro: arquivo {index} precisa de 'content' como string."

        relative = Path(raw_path.strip())
        if relative.is_absolute() or ".." in relative.parts:
            return f"Erro: caminho inválido no arquivo {index}: {raw_path!r}."
        target = (base_resolved / relative).resolve()
        if not target.is_relative_to(base_resolved):
            return f"Erro: caminho fora da pasta base no arquivo {index}: {raw_path!r}."
        if target in seen:
            return f"Erro: caminho duplicado: {raw_path}."
        seen.add(target)

        if target.exists() and not overwrite:
            skipped += 1
            continue
        prepared.append((target, content))

    backups: dict[Path, bytes] = {}
    created: list[Path] = []
    with lock_paths([target for target, _ in prepared]):
        try:
            for target, content in prepared:
                if target.exists():
                    backups[target] = target.read_bytes()
                else:
                    created.append(target)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding=encoding)
        except Exception as exc:
            for target, data in backups.items():
                try:
                    target.write_bytes(data)
                except Exception:
                    pass
            for target in created:
                try:
                    if target.exists():
                        target.unlink()
                except Exception:
                    pass
            return f"Erro ao escrever arquivos; alterações revertidas: {exc}"

    return (
        f"{len(prepared)} arquivo(s) escrito(s) em {base}; "
        f"{skipped} preservado(s)."
    )
