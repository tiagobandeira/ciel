"""Cria uma tool temporária em /tools/temp e registra no temp-log.md."""

import ast
import importlib.util
import subprocess
import sys
from pathlib import Path
from datetime import datetime

TOOLS_TEMP_DIR = Path(__file__).parent / "tools" / "temp"
TEMP_LOG       = TOOLS_TEMP_DIR / "temp-log.md"


def _ensure_log():
    TOOLS_TEMP_DIR.mkdir(parents=True, exist_ok=True)
    if not TEMP_LOG.exists():
        TEMP_LOG.write_text(
            "# Temp Tools Log\n\n"
            "| tool | criada | usos | último uso |\n"
            "|------|--------|------|------------|\n",
            encoding="utf-8",
        )


def _log_creation(tool_name: str):
    _ensure_log()
    today = datetime.now().strftime("%Y-%m-%d")
    with open(TEMP_LOG, "a", encoding="utf-8") as f:
        f.write(f"| {tool_name} | {today} | 0 | - |\n")


def _try_import_and_fix(path: Path) -> str | None:
    """
    Tenta importar o módulo. Se falhar com ModuleNotFoundError,
    instala o pacote e tenta de novo (até 5 dependências).
    Retorna mensagem de erro ou None se OK.
    """
    for _ in range(5):
        spec = importlib.util.spec_from_file_location("_check", path)
        mod  = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
            return None  # OK
        except ModuleNotFoundError as e:
            pkg = (e.name or str(e)).split(".")[0]
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install", pkg],
                capture_output=True, text=True,
            )
            if result.returncode != 0:
                return f"Não foi possível instalar '{pkg}': {result.stderr[:150]}"
        except SyntaxError as e:
            return f"Erro de sintaxe: {e}"
        except Exception as e:
            return f"Erro ao importar: {e}"
    return "Muitas dependências faltando — verifique o código gerado."


def run(tool_name: str, tool_code: str) -> str:
    """
    tool_name: nome da tool em snake_case (sem .py)
    tool_code: código Python completo seguindo o contrato run() → str
    """
    if not tool_name.replace("_", "").isalnum():
        return f"Erro: nome inválido '{tool_name}'. Use apenas letras, números e underscore."

    TOOLS_TEMP_DIR.mkdir(parents=True, exist_ok=True)
    tool_path = TOOLS_TEMP_DIR / f"{tool_name}.py"

    try:
        tool_path.write_text(tool_code, encoding="utf-8")
    except Exception as e:
        return f"Erro ao salvar tool temporária: {e}"

    # valida import e instala dependências faltantes automaticamente
    err = _try_import_and_fix(tool_path)
    if err:
        tool_path.unlink(missing_ok=True)  # remove arquivo inválido
        return f"Erro ao validar tool '{tool_name}': {err}"

    _log_creation(tool_name)
    return f"Tool temporária '{tool_name}' criada em tools/temp/{tool_name}.py"