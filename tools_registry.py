"""
Autodiscover de tools: varre /tools e /tools/temp, importa cada módulo,
lê o docstring como descrição e run() como função.
Tools em /tools/temp são marcadas com categoria 'temp'.
"""

import importlib.util
from pathlib import Path

TOOLS_DIR      = Path(__file__).parent / "tools"
TOOLS_TEMP_DIR = TOOLS_DIR / "temp"


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
            tools[path.stem] = {
                "fn":          mod.run,
                "description": (mod.__doc__ or "sem descrição").strip(),
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
    return [
        {
            "name":      name,
            "description": meta["description"],
            "categoria": meta.get("categoria", "permanente"),
        }
        for name, meta in tools.items()
    ]