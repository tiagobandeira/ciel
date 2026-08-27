# test_secondary_model.py
import sys
from pathlib import Path

sys.path.insert(0, ".")
from tools.secondary_model import _inject_files

G   = "\033[92m"
R   = "\033[91m"
B   = "\033[94m"
DIM = "\033[2m"
RST = "\033[0m"
HR  = f"{DIM}{'─' * 60}{RST}"

all_passed = True

def check(cond, msg_ok, msg_err):
    global all_passed
    if cond:
        print(f"  {G}✓{RST} {msg_ok}")
    else:
        print(f"  {R}✗{RST} {msg_err}")
        all_passed = False

print(f"\n{B}1. files=None ou [] — prompt não é alterado{RST}")
print(HR)
prompt = "refatora esse módulo"
check(_inject_files(prompt, None)  == prompt, "files=None: prompt intacto", "FALHOU")
check(_inject_files(prompt, [])    == prompt, "files=[]: prompt intacto",   "FALHOU")

print(f"\n{B}2. arquivo existente — conteúdo injetado antes do prompt{RST}")
print(HR)
# usa um arquivo que existe no projeto
result = _inject_files(prompt, ["tools/calculator.py"])
check("## Contexto — arquivos fornecidos" in result, "bloco de contexto presente", "bloco ausente")
check(result.index("## Contexto") < result.index(prompt),  "contexto vem antes do prompt", "ordem errada")
check("tools/calculator.py" in result, "nome do arquivo presente", "nome ausente")
check("---" in result, "separador presente", "separador ausente")

print(f"\n{B}3. arquivo inexistente — aviso inline, prompt preservado{RST}")
print(HR)
result = _inject_files(prompt, ["nao_existe.py"])
check("não encontrado" in result, "aviso de arquivo não encontrado", "aviso ausente")
check(prompt in result,           "prompt preservado mesmo com erro", "prompt ausente")

print(f"\n{B}4. mix: arquivo válido + inexistente{RST}")
print(HR)
result = _inject_files(prompt, ["tools/calculator.py", "nao_existe.py"])
check("calculator.py" in result,  "arquivo válido presente",    "arquivo válido ausente")
check("não encontrado" in result, "aviso do inválido presente", "aviso ausente")
check(prompt in result,           "prompt preservado",          "prompt ausente")

print(f"\n{B}5. schema do registry — files aparece no schema{RST}")
print(HR)
from tools_registry import load_tools, tools_schema
tools  = load_tools()
schema = tools_schema(tools)
entry  = next((e for e in schema if e["name"] == "secondary_model"), None)
check(entry is not None, "secondary_model no schema", "secondary_model ausente")
if entry:
    params = [p["name"] for p in entry.get("parameters", [])]
    check("files" in params, f"'files' no schema: {params}", f"'files' ausente — params: {params}")
    check("prompt" in params, "'prompt' no schema", "'prompt' ausente")

print()
print(HR)
if all_passed:
    print(f"  {G}Todos os checks passaram.{RST}\n")
else:
    print(f"  {R}Alguns checks falharam — veja acima.{RST}\n")
    sys.exit(1)