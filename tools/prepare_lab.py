"""Prepara um diretório de laboratório limpo, arquivando o anterior."""

PERMISSIONS = {"path": "write"}

import shutil
from datetime import datetime
from pathlib import Path


def run(path: str = "data/labs/estudo", arquivar: bool = True) -> str:
    """
    path: diretório do lab
    arquivar: se já existir conteúdo, move para <pai>/_arquivo/<nome>_<ts>
    """
    target = Path(path)
    archived = ""
    try:
        if target.exists() and any(target.iterdir()):
            if arquivar:
                stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                backup = target.parent / "_arquivo" / f"{target.name}_{stamp}"
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(target), str(backup))
                archived = str(backup)
        target.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        return f"Erro ao preparar lab '{path}': {exc}"
    msg = f"Lab pronto: {path}"
    if archived:
        msg += f" (anterior arquivado em {archived})"
    return msg
