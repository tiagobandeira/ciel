"""Executa as células de código de um notebook em um script Python linear."""

PERMISSIONS = {"path": "read"}

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

MAX_OUTPUT = 16000


def _source(value) -> str:
    if isinstance(value, list):
        return "\n".join(str(part) for part in value)
    return str(value or "")


def _clean_cell(source: str) -> str:
    """Remove magics de IPython que não rodam em Python puro."""
    lines = []
    for line in source.splitlines():
        stripped = line.lstrip()
        if stripped.startswith(("%", "!")) or stripped.startswith("get_ipython("):
            lines.append("# [ciel] linha IPython ignorada: " + stripped)
            continue
        lines.append(line)
    return "\n".join(lines)


def run(
    path: str,
    cwd: str = "",
    timeout: int = 120,
    log_path: str = "",
) -> str:
    """
    path: .ipynb
    cwd: pasta de execução (padrão: pasta do notebook)
    timeout: segundos
    log_path: se informado, grava stdout+stderr nesse arquivo
    """
    notebook_path = Path(path)
    if not notebook_path.is_file():
        return f"Erro: notebook '{path}' não encontrado."
    try:
        data = json.loads(notebook_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return f"Erro ao ler notebook: {exc}"

    cells = data.get("cells") or []
    code = [
        _clean_cell(_source(cell.get("source", "")))
        for cell in cells
        if cell.get("cell_type") == "code"
    ]
    if not code:
        return "Erro: notebook não tem células de código."
    script = "\n\n".join(code)

    workdir = Path(cwd) if cwd else notebook_path.parent
    if not workdir.is_dir():
        return f"Erro: cwd '{workdir}' não é uma pasta."
    try:
        timeout = max(1, min(int(timeout), 300))
    except (TypeError, ValueError):
        timeout = 120

    handle = tempfile.NamedTemporaryFile(
        "w", suffix=".py", prefix=".ciel_notebook_",
        dir=workdir, encoding="utf-8", delete=False,
    )
    try:
        handle.write(script)
        handle.close()
        env = dict(os.environ)
        env.setdefault("MPLBACKEND", "Agg")
        proc = subprocess.run(
            [sys.executable, handle.name],
            cwd=str(workdir), capture_output=True, text=True,
            timeout=timeout, env=env,
        )
        output = (
            f"Notebook executado: {path} (exit={proc.returncode})\n"
            f"cwd: {workdir}\n"
            f"--- stdout ---\n{proc.stdout}\n"
            f"--- stderr ---\n{proc.stderr}"
        )
        if log_path:
            try:
                log = Path(log_path)
                log.parent.mkdir(parents=True, exist_ok=True)
                log.write_text(output, encoding="utf-8")
            except Exception as exc:
                output += f"\n[aviso] não gravei o log: {exc}"
        return output[:MAX_OUTPUT]
    except subprocess.TimeoutExpired:
        return f"Erro: notebook excedeu {timeout}s."
    except Exception as exc:
        return f"Erro ao executar notebook: {exc}"
    finally:
        try:
            os.unlink(handle.name)
        except OSError:
            pass
