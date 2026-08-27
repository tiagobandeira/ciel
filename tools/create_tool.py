"""Cria uma nova tool Python no diretório /tools do agente.

tool_name: nome da tool (snake_case, ex: 'buscar_cep')
tool_code: código Python completo da tool — deve ter módulo-docstring e função run()
"""

import ast
import importlib.util
import subprocess
import sys
from pathlib import Path


# ── sanitização de escaping ───────────────────────────────────────────────────

def _sanitize_code(code: str) -> str:
    """
    Corrige problemas comuns de escaping quando o modelo gera tool_code
    como string JSON mal escapada.

    Casos cobertos:
      - módulo-docstring com 2 aspas no fechamento em vez de 3
        ex: '\"\"\"Descrição.\"\"\\n' → '\"\"\"Descrição.\"\"\"\\n'
        (ocorre quando o modelo gera \"\"\" no JSON e uma aspa é consumida no decode)
      - linha só com 2 aspas (fechamento inline de docstring)
        ex: '    \"\"' → '    \"\"\"'
      - quebras de linha mistas (\\r\\n ou \\r → \\n)
      - tabs misturados com espaços (tab → 4 espaços)
    """
    lines = code.split('\n')
    fixed = []
    for line in lines:
        stripped = line.rstrip()
        # linha que abre E fecha docstring de módulo mas termina com 2 aspas
        # ex: '\"\"\"Descrição.\"\"'  → '\"\"\"Descrição.\"\"\"'
        if (stripped.startswith('"""') and stripped.endswith('""')
                and not stripped.endswith('"""')):
            line = stripped + '"'
        # linha só com indentação + 2 aspas — fechamento de docstring multiline
        # ex: '    \"\"' → '    \"\"\"'
        elif stripped == '""':
            indent = len(line) - len(line.lstrip())
            line = ' ' * indent + '"""'
        fixed.append(line)

    code = '\n'.join(fixed)
    code = code.replace('\r\n', '\n').replace('\r', '\n')
    code = code.replace('\t', '    ')
    return code


# ── validação estática ────────────────────────────────────────────────────────

def _validate(code: str) -> tuple[bool, str]:
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return False, f"Erro de sintaxe na linha {e.lineno}: {e.msg}"

    if not tree.body:
        return False, "Arquivo vazio."

    first = tree.body[0]
    has_module_docstring = (
        isinstance(first, ast.Expr)
        and isinstance(first.value, ast.Constant)
        and isinstance(first.value.value, str)
    )
    if not has_module_docstring:
        return False, (
            "A tool deve começar com um módulo-docstring. "
            'Exemplo: """Busca o endereço de um CEP."""'
        )

    top_level_funcs = {
        node.name for node in tree.body if isinstance(node, ast.FunctionDef)
    }
    if "run" not in top_level_funcs:
        return False, "A tool deve definir uma função run() no nível do módulo."

    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "REQUIREMENTS"
        ):
            if not (
                isinstance(node.value, ast.List)
                and all(
                    isinstance(elt, ast.Constant) and isinstance(elt.value, str)
                    for elt in node.value.elts
                )
            ):
                return False, (
                    "REQUIREMENTS deve ser uma lista de strings. "
                    'Exemplo: REQUIREMENTS = ["requests", "beautifulsoup4>=4.12"]'
                )

    return True, ""


# ── extração de REQUIREMENTS via AST ─────────────────────────────────────────

def _extract_requirements(code: str) -> list[str]:
    tree = ast.parse(code)
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "REQUIREMENTS"
            and isinstance(node.value, ast.List)
        ):
            return [elt.value for elt in node.value.elts if isinstance(elt, ast.Constant)]
    return []


# ── instalação via pip ────────────────────────────────────────────────────────

def _install(packages: list[str]) -> tuple[bool, str]:
    if not packages:
        return True, ""
    cmd = [sys.executable, "-m", "pip", "install", "--quiet", *packages]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        return False, "Timeout ao instalar dependências (>120s)."
    except FileNotFoundError:
        return False, f"Interpretador não encontrado: {sys.executable}"

    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()[-500:]
        return False, f"pip falhou (exit {result.returncode}):\n{detail}"

    return True, f"Instalado: {', '.join(packages)}"


# ── fallback: auto-install por ModuleNotFoundError ───────────────────────────

def _try_import_and_fix(path: Path) -> str | None:
    """
    Tenta importar o módulo salvo. Se der ModuleNotFoundError,
    instala o pacote faltante e tenta de novo (até 5x).
    Retorna mensagem de erro ou None se OK.
    Cobre o caso em que o modelo esqueceu de declarar REQUIREMENTS.
    """
    for _ in range(5):
        spec = importlib.util.spec_from_file_location("_check", path)
        mod  = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
            return None  # OK
        except ModuleNotFoundError as e:
            pkg = (e.name or str(e)).split(".")[0]
            ok, log = _install([pkg])
            if not ok:
                return log
        except Exception:
            return None
    return "Muitas dependências faltando — adicione REQUIREMENTS ao código."


# ── ponto de entrada ──────────────────────────────────────────────────────────

def run(tool_name: str, tool_code: str) -> str:
    """
    tool_name : nome em snake_case (ex: 'buscar_cep').
    tool_code : código Python completo com docstring e run() → str.
    """
    # 1. sanitiza nome
    safe_name = "".join(c for c in tool_name if c.isalnum() or c == "_").lower().strip("_")
    if not safe_name:
        return "Erro: tool_name inválido. Use letras, números e underscore."

    # 2. sanitiza código — corrige escaping residual antes de validar
    tool_code = _sanitize_code(tool_code)

    # 3. valida estrutura sem executar
    ok, error_msg = _validate(tool_code)
    if not ok:
        return f"Erro de validação — tool não criada.\n{error_msg}"

    # 4. instala dependências declaradas em REQUIREMENTS
    requirements = _extract_requirements(tool_code)
    install_log  = ""
    if requirements:
        pip_ok, pip_log = _install(requirements)
        if not pip_ok:
            return f"Erro ao instalar dependências {requirements} — tool não criada.\n{pip_log}"
        install_log = f"\n{pip_log}"

    # 5. salva o arquivo
    tools_dir = Path(__file__).parent
    tools_dir.mkdir(exist_ok=True)
    file_path = tools_dir / f"{safe_name}.py"

    try:
        file_path.write_text(tool_code, encoding="utf-8")
    except OSError as e:
        return f"Erro ao salvar arquivo: {e}"

    # 6. fallback: auto-install se o modelo esqueceu o REQUIREMENTS
    err = _try_import_and_fix(file_path)
    if err:
        file_path.unlink(missing_ok=True)
        return f"Erro ao validar tool '{safe_name}': {err}"

    return f"Tool '{safe_name}' criada em {file_path}.{install_log}"