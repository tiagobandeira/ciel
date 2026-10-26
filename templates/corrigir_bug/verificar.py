"""Executa o teste do projeto-alvo descrito em ALVO.json.

Uso:
    python verificar.py

O ALVO.json fica nesta pasta e tem o formato:
    {"projeto": "data/user/bugfix_demo",
     "comando": ["python", "-m", "pytest", "-q"],
     "cwd": "data/user/bugfix_demo"}
"""

from __future__ import annotations

import json
import shlex
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[2]
ALVO = BASE / "ALVO.json"


def _resolve(raw: str) -> Path:
    path = Path(raw).expanduser()
    return path if path.is_absolute() else (ROOT / path)


def _python_executable() -> str:
    """Prefere o venv do próprio projeto ao Python do processo atual."""
    candidatos = [
        ROOT / "venv" / "Scripts" / "python.exe",
        ROOT / "venv" / "bin" / "python",
        ROOT / ".venv" / "Scripts" / "python.exe",
        ROOT / ".venv" / "bin" / "python",
    ]
    for candidato in candidatos:
        if candidato.is_file():
            return str(candidato)
    return sys.executable


def main() -> int:
    if not ALVO.exists():
        print(f"Erro: ALVO.json não encontrado em {ALVO}")
        return 2
    try:
        data = json.loads(ALVO.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"Erro ao ler ALVO.json: {exc}")
        return 2

    projeto = _resolve(str(data.get("projeto") or "data/user/bugfix_demo"))
    if not projeto.is_dir():
        print(f"Erro: projeto não encontrado: {projeto}")
        return 2

    comando = data.get("comando") or [sys.executable, "-m", "pytest", "-q"]
    if isinstance(comando, str):
        comando = shlex.split(comando)
    if not isinstance(comando, list) or not comando:
        print("Erro: 'comando' inválido no ALVO.json")
        return 2
    # "python" no ALVO pode resolver para outro interpretador (PATH/Store);
    # usa o venv do projeto quando existir.
    if str(comando[0]).lower() in ("python", "python.exe", "py"):
        comando = [_python_executable(), *comando[1:]]

    cwd_raw = data.get("cwd") or str(projeto)
    cwd = _resolve(str(cwd_raw))
    if not cwd.is_dir():
        cwd = projeto

    print(f"projeto: {projeto}")
    print(f"comando: {' '.join(str(c) for c in comando)}")
    print(f"cwd:     {cwd}")
    print("-" * 60)
    try:
        result = subprocess.run(
            [str(c) for c in comando],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=int(data.get("timeout") or 120),
        )
    except Exception as exc:
        print(f"Erro ao executar: {exc}")
        return 2

    saida = (result.stdout or "") + (result.stderr or "")
    print(saida.strip())
    print("-" * 60)
    print(f"RESULTADO: exit {result.returncode}")
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
