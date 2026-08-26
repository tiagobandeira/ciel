"""
Testa o tools_registry sem precisar do Ollama.

Verifica:
  1. Schema gerado — o que o modelo recebe no system prompt
  2. Casos específicos: com anotação, sem anotação, sem params, legado
  3. Simulação de chamada correta vs. errada (o TypeError recovery)
"""

import json
import sys
import inspect
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from tools_registry import load_tools, tools_schema

# ── cores simples pro terminal ────────────────────────────────────────────────
G  = "\033[92m"   # verde
Y  = "\033[93m"   # amarelo
R  = "\033[91m"   # vermelho
B  = "\033[94m"   # azul
DIM = "\033[2m"
RST = "\033[0m"
HR  = f"{DIM}{'─' * 60}{RST}"

def ok(msg):  print(f"  {G}✓{RST} {msg}")
def warn(msg): print(f"  {Y}⚠{RST} {msg}")
def err(msg):  print(f"  {R}✗{RST} {msg}")


# ══════════════════════════════════════════════════════════════════════════════
print(f"\n{B}1. Carregando tools{RST}")
print(HR)

tools = load_tools()
schema = tools_schema(tools)

print(f"  Tools carregadas: {list(tools.keys())}")


# ══════════════════════════════════════════════════════════════════════════════
print(f"\n{B}2. Schema completo (o que o modelo recebe){RST}")
print(HR)
print(json.dumps(schema, ensure_ascii=False, indent=2))


# ══════════════════════════════════════════════════════════════════════════════
print(f"\n{B}3. Checagens por tool{RST}")
print(HR)

schema_by_name = {e["name"]: e for e in schema}

cases = [
    # (tool,                  params_esperados,                              descricao_do_caso)
    ("list_directory",     ["directory", "ext", "recursive"],               "com anotações; alias 'path' oculto via **kwargs"),
    ("read_file",          ["path", "encoding"],                            "com anotações + docstring de params"),
    ("calculator",         ["operation", "a", "b"],                         "3 params tipados: operation, a, b"),
    ("get_local_datetime", [],                                               "sem parâmetros — não deve ter 'parameters'"),
    ("web_search_extended",["query", "limit", "extract", "max_results_with_content"], "params reais atuais"),
]

all_passed = True
for tool_name, expected_params, desc in cases:
    entry = schema_by_name.get(tool_name)
    if not entry:
        err(f"{tool_name}: não encontrada no schema")
        all_passed = False
        continue

    actual_params = [p["name"] for p in entry.get("parameters", [])]

    if set(actual_params) == set(expected_params):
        ok(f"{tool_name}: {actual_params}  [{desc}]")
    else:
        err(f"{tool_name}: esperado {expected_params}, got {actual_params}  [{desc}]")
        all_passed = False

    # tool sem params não deve ter a chave "parameters" no schema
    if not expected_params and "parameters" in entry:
        err(f"{tool_name}: chave 'parameters' presente mas deveria estar ausente")
        all_passed = False
    if not expected_params and "parameters" not in entry:
        ok(f"{tool_name}: chave 'parameters' ausente corretamente")


# ══════════════════════════════════════════════════════════════════════════════
print(f"\n{B}4. Simulação de chamada correta vs. errada (TypeError recovery){RST}")
print(HR)

# simula o que o modelo faz: chama fn(**args)
def simulate_call(tool_name, args):
    fn = tools[tool_name]["fn"]
    try:
        result = fn(**args)
        ok(f"{tool_name}({args})  →  {repr(result)[:60]}")
        return True
    except TypeError as e:
        sig = inspect.signature(fn)
        feedback = (
            f"Args inválidos para '{tool_name}': {e}. "
            f"Assinatura correta: {tool_name}{sig}. "
            f"Args recebidos: {list(args.keys())}"
        )
        err(f"TypeError: {feedback}")
        return False

# chamadas corretas — usando a assinatura real de cada tool
simulate_call("list_directory", {"directory": "."})
simulate_call("calculator",     {"operation": "add", "a": 2, "b": 6})
simulate_call("get_local_datetime", {})

# alias de compatibilidade: 'path' chega via **kwargs, não deve quebrar
print(f"  {DIM}-- alias 'path' ainda deve funcionar (via **kwargs):{RST}")
simulate_call("list_directory", {"path": "."})   # deve passar — alias absorvido por **kwargs

# chamada errada: param inexistente — deve falhar com TypeError informativo
print(f"  {DIM}-- simulando param inexistente (chute do modelo):{RST}")
simulate_call("calculator", {"expression": "2 + 2 * 3"})   # deve falhar


# ══════════════════════════════════════════════════════════════════════════════
print(f"\n{B}5. Defaults: modelo pode omitir params opcionais?{RST}")
print(HR)

# params com default devem funcionar sem ser passados
simulate_call("list_directory", {"directory": "."})           # omite recursive
simulate_call("read_file",      {"path": "tools_registry.py"})  # omite encoding


# ══════════════════════════════════════════════════════════════════════════════
print()
print(HR)
if all_passed:
    print(f"  {G}Todos os checks passaram.{RST}\n")
else:
    print(f"  {R}Alguns checks falharam — veja acima.{RST}\n")
    sys.exit(1)