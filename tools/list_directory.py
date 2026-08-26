"""Lista arquivos de um diretório com tipo (arquivo/pasta) e filtro por extensão."""

import os
from pathlib import Path


def run(directory: str = ".", ext: str = "", recursive: bool = False, **kwargs) -> str:
    """
    directory: caminho do diretório a listar (padrão: diretório atual)
    ext: filtra por extensão, ex: '.py', '.txt', '.md' (vazio = todos)
    recursive: se True, lista subdiretórios também (padrão: False)
    """
    # aceita 'path' como alias de 'directory' via **kwargs — fica fora do schema
    # para não criar ambiguidade com 'directory', mas mantém compatibilidade com
    # modelos que historicamente chutavam 'path'
    path = kwargs.get("path", "")
    if path and directory == ".":
        directory = path
    try:
        base = Path(directory)

        if not base.exists():
            return f"Erro: diretório '{directory}' não encontrado."
        if not base.is_dir():
            return f"Erro: '{directory}' não é um diretório."

        if recursive:
            entries = sorted(base.rglob("*"))
        else:
            entries = sorted(base.iterdir())

        if ext:
            ext = ext if ext.startswith(".") else f".{ext}"
            entries = [e for e in entries if e.is_file() and e.suffix.lower() == ext.lower()]
        
        if not entries:
            msg = f"Nenhum arquivo encontrado em '{directory}'"
            if ext:
                msg += f" com extensão '{ext}'"
            return msg + "."

        lines = []
        for entry in entries:
            rel = entry.relative_to(base)
            kind = "[dir] " if entry.is_dir() else "[arq] "
            lines.append(f"{kind}{rel}")

        total = len(lines)
        header = f"{total} item(s) em '{directory}'"
        if ext:
            header += f" (ext: {ext})"
        if recursive:
            header += " [recursivo]"

        return header + "\n\n" + "\n".join(lines)

    except Exception as e:
        return f"Erro: {e}"