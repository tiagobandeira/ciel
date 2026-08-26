"""
Autodiscover de tools: varre /tools e /tools/temp, importa cada módulo,
lê o docstring como descrição e run() como função.
Tools em /tools/temp são marcadas com categoria 'temp'.
"""

import re
import inspect
import importlib.util
from pathlib import Path

TOOLS_DIR      = Path(__file__).parent / "tools"
TOOLS_TEMP_DIR = TOOLS_DIR / "temp"


def _extract_params(fn) -> list[dict]:
    """
    Extrai parâmetros de uma função via inspect.signature.

    Para cada parâmetro retorna um dict com:
      - name  (sempre presente)
      - type  (quando há anotação de tipo)
      - default (quando há valor padrão)
      - description (quando há docstring no padrão 'param: descrição')

    Parâmetros *args e **kwargs são ignorados — o modelo não sabe usá-los.
    """
    try:
        sig = inspect.signature(fn)
    except (ValueError, TypeError):
        return []

    # tenta extrair descrições de parâmetros do docstring da função
    # suporta o padrão comum: "param_name: descrição" ou "param_name (tipo): descrição"
    param_docs: dict[str, str] = {}
    doc = inspect.getdoc(fn) or ""
    for line in doc.splitlines():
        line = line.strip().lstrip("-").strip()
        # padrão: "nome:" ou "nome (tipo):"
        m = re.match(r"^(\w+)(?:\s*\([^)]*\))?\s*:\s*(.+)$", line)
        if m:
            param_docs[m.group(1)] = m.group(2).strip()

    params = []
    for name, param in sig.parameters.items():
        # ignora *args e **kwargs
        if param.kind in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ):
            continue

        entry: dict = {"name": name}

        # tipo
        if param.annotation is not inspect.Parameter.empty:
            ann = param.annotation
            entry["type"] = ann.__name__ if hasattr(ann, "__name__") else str(ann)

        # valor padrão
        if param.default is not inspect.Parameter.empty:
            entry["default"] = repr(param.default)

        # descrição extraída do docstring da run()
        if name in param_docs:
            entry["description"] = param_docs[name]

        params.append(entry)

    return params


def _load_from_dir(directory: Path, categoria: str) -> dict:
    """Carrega todas as tools de um diretório."""
    tools = {}
    if not directory.exists():
        return tools

    for path in sorted(directory.glob("*.py")):
        if path.name.startswith("_"):
            continue
        spec = importlib.util.spec_from_file_location(path.stem, path)
        mod  = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
        except Exception as e:
            # tool com erro de importação não quebra o registry
            print(f"[registry] erro ao carregar {path.name}: {e}")
            continue

        if hasattr(mod, "run"):
            params = _extract_params(mod.run)
            tools[path.stem] = {
                "fn":          mod.run,
                "description": (mod.__doc__ or "sem descrição").strip(),
                "parameters":  params,
                "categoria":   categoria,
                "path":        path,
            }

    return tools


def load_tools() -> dict:
    """Carrega tools permanentes e temporárias."""
    tools = {}
    tools.update(_load_from_dir(TOOLS_DIR,      categoria="permanente"))
    tools.update(_load_from_dir(TOOLS_TEMP_DIR, categoria="temp"))
    return tools


def tools_schema(tools: dict) -> list[dict]:
    """Gera o schema de tools pro prompt do modelo."""
    schema = []
    for name, meta in tools.items():
        entry: dict = {
            "name":        name,
            "description": meta["description"],
            "categoria":   meta.get("categoria", "permanente"),
        }
        # inclui parâmetros apenas quando existem — evita ruído pra tools sem args
        params = meta.get("parameters", [])
        if params:
            entry["parameters"] = params
        schema.append(entry)
    return schema