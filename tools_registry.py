"""
Autodiscover de tools: varre /tools e /tools/temp, importa cada módulo,
lê o docstring como descrição e run() como função.
Tools em /tools/temp são marcadas com categoria 'temp'.

Variáveis de módulo reconhecidas em cada tool:
  REQUIREMENTS = ["pkg"]   deps pip necessárias (usadas pelo orquestrador)
  EXTRA = True             tool opcional — ImportError é esperado e vira
                           sugestão de instalação, não erro
  PERMISSIONS = {"path": "read"}
                           declara quais argumentos são paths no disco e se
                           precisam de leitura ou escrita. Usada pelo guard
                           de workspace (workspace.py / tool_dispatch.py)
                           pra saber o que checar antes de rodar a tool —
                           sem isso, o argumento não é validado contra o
                           workspace atual.
"""

import re
import inspect
import importlib.util
from pathlib import Path

TOOLS_DIR      = Path(__file__).parent / "tools"
TOOLS_TEMP_DIR = TOOLS_DIR / "temp"

# tools que falharam por ImportError — populado por load_tools()
# cada entrada: (nome_da_tool, módulo_ausente, is_extra)
# is_extra=True  → EXTRA = True no módulo — ausência esperada, vira sugestão
# is_extra=False → tool core sem a flag — erro real, exibido separado
_missing_optional: list[tuple[str, str, bool]] = []


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


def _read_extra_from_source(path: Path) -> bool:
    """
    Lê EXTRA = True do source sem importar o módulo.
    Usado quando o import falha antes de EXTRA ser definida.
    Heurística simples: procura 'EXTRA = True' nas primeiras 30 linhas.
    """
    try:
        for line in path.read_text(encoding="utf-8").splitlines()[:30]:
            stripped = line.strip()
            if stripped.startswith("EXTRA") and "True" in stripped:
                return True
    except OSError:
        pass
    return False


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
        # lê variáveis de módulo antes de executar — precisamos de EXTRA
        # mesmo quando o import falha, então usamos uma leitura parcial via ast
        # para não duplicar lógica, lemos EXTRA do módulo já carregado abaixo
        try:
            spec.loader.exec_module(mod)
        except ImportError as e:
            missing_mod = str(e).removeprefix("No module named '").rstrip("'")
            # EXTRA pode não estar acessível se o import falhou antes de defini-la;
            # tentamos ler do source com uma heurística simples antes de desistir
            is_extra = _read_extra_from_source(path)
            _missing_optional.append((path.stem, missing_mod, is_extra))
            if not is_extra:
                # tool core com ImportError inesperado — avisa imediatamente
                print(f"[registry] erro de dependência em {path.name}: {missing_mod}")
            continue
        except Exception as e:
            # erro real (sintaxe, atributo, etc.) — sempre visível
            print(f"[registry] erro ao carregar {path.name}: {e}")
            continue

        if hasattr(mod, "run"):
            params = _extract_params(mod.run)
            tools[path.stem] = {
                "fn":           mod.run,
                "description":  (mod.__doc__ or "sem descrição").strip(),
                "parameters":   params,
                "categoria":    categoria,
                "path":         path,
                "extra":        bool(getattr(mod, "EXTRA", False)),
                "requirements": list(getattr(mod, "REQUIREMENTS", [])),
                "permissions":  dict(getattr(mod, "PERMISSIONS", {})),
            }

    return tools


def load_tools() -> dict:
    """Carrega tools permanentes e temporárias."""
    global _missing_optional
    _missing_optional = []  # reseta a cada carregamento

    tools = {}
    tools.update(_load_from_dir(TOOLS_DIR,      categoria="permanente"))
    tools.update(_load_from_dir(TOOLS_TEMP_DIR, categoria="temp"))
    return tools


def get_missing_optional_tools() -> list[tuple[str, str]]:
    """
    Retorna tools opcionais (EXTRA = True) que não carregaram por falta de
    dependência. Cada entrada é uma tupla (nome_da_tool, módulo_ausente).
    Usado pelo /tools-extras para exibir sugestões de instalação.
    """
    return [(name, mod) for name, mod, is_extra in _missing_optional if is_extra]


def get_broken_tools() -> list[tuple[str, str]]:
    """
    Retorna tools core (sem EXTRA = True) que falharam por ImportError.
    Cada entrada é uma tupla (nome_da_tool, módulo_ausente).
    Indica problema real — dep ausente que deveria estar no requirements.txt.
    """
    return [(name, mod) for name, mod, is_extra in _missing_optional if not is_extra]


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