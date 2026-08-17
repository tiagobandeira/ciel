"""Executa um script Python local e retorna stdout/stderr. ATENÇÃO: tool de execução arbitrária — desabilitada com --safe."""

import subprocess
import sys
from pathlib import Path


def run(script_path: str, args: list[str] = None, timeout: int = 120) -> str:
    """
    script_path: caminho para o .py a executar
    args:        lista de argumentos passados ao script (opcional)
    timeout:     segundos antes de encerrar o processo (padrão: 120)
    """
    path = Path(script_path)
    if not path.exists():
        return f"Erro: arquivo '{script_path}' não encontrado."
    if path.suffix != ".py":
        return f"Erro: '{script_path}' não é um arquivo Python."

    cmd = [sys.executable, str(path)] + (args or [])
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = result.stdout.strip()
        error  = result.stderr.strip()

        if result.returncode != 0:
            return f"Script falhou (exit {result.returncode}):\n{error or output}"
        return output or "(sem saída)"

    except subprocess.TimeoutExpired:
        return f"Erro: script excedeu o tempo limite de {timeout} segundos."
    except Exception as e:
        return f"Erro ao executar script: {e}"