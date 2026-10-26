"""Substitui um trecho exato de um arquivo de texto local."""

PERMISSIONS = {"path": "write"}

from pathlib import Path

from tools.file_locks import lock_path


def run(
    path: str,
    old: str,
    new: str,
    count: int = 1,
    encoding: str = "utf-8",
) -> str:
    """
    path:     caminho do arquivo a editar
    old:      trecho exato a substituir
    new:      texto novo
    count:    quantas ocorrências substituir (0 = todas; padrão 1)
    encoding: encoding do arquivo (padrão utf-8)
    """
    p = Path(path)
    if not p.exists():
        return f"Erro: arquivo '{path}' não encontrado."
    if not p.is_file():
        return f"Erro: '{path}' não é um arquivo."
    if not old:
        return "Erro: o trecho 'old' não pode ser vazio."

    with lock_path(path):
        try:
            content = p.read_text(encoding=encoding)
        except UnicodeDecodeError:
            return f"Erro: não foi possível decodificar '{path}' como {encoding}."
        except Exception as e:
            return f"Erro ao ler arquivo: {e}"

        occurrences = content.count(old)
        if occurrences == 0:
            return (
                "Erro: trecho não encontrado. Leia o arquivo com read_file "
                "e copie exatamente o texto que quer substituir."
            )

        try:
            times = int(count)
        except (TypeError, ValueError):
            times = 1
        if times <= 0:
            times = occurrences
        times = min(times, occurrences)

        try:
            updated = content.replace(old, new, times)
            p.write_text(updated, encoding=encoding)
        except Exception as e:
            return f"Erro ao editar arquivo: {e}"

        return (
            f"Arquivo atualizado: {path} "
            f"({occurrences} ocorrência(s), {times} substituída(s))"
        )
