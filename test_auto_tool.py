"""
Testa a lógica do auto-tool sem precisar do Ollama.

Verifica:
  1. Descarte do system prompt na probe (_ask_model_for_tool_proposal)
  2. Validação da proposta — campos mínimos obrigatórios
  3. Montagem da instrução de criação (_build_create_instruction)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

# ── cores simples pro terminal ────────────────────────────────────────────────
G   = "\033[92m"
Y   = "\033[93m"
R   = "\033[91m"
B   = "\033[94m"
DIM = "\033[2m"
RST = "\033[0m"
HR  = f"{DIM}{'─' * 60}{RST}"

def ok(msg):   print(f"  {G}✓{RST} {msg}")
def warn(msg): print(f"  {Y}⚠{RST} {msg}")
def err(msg):  print(f"  {R}✗{RST} {msg}")

all_passed = True

def check(cond, msg_ok, msg_err):
    global all_passed
    if cond:
        ok(msg_ok)
    else:
        err(msg_err)
        all_passed = False


# ══════════════════════════════════════════════════════════════════════════════
print(f"\n{B}1. Descarte do system prompt na probe{RST}")
print(HR)

# simula messages como chegam ao final do run_agent (steps esgotados)
messages_com_system = [
    {"role": "system",    "content": "system prompt completo do agente com schema agêntico"},
    {"role": "user",      "content": "converte o arquivo data.csv para JSON"},
    {"role": "assistant", "content": '{"tool": "csv_para_json", "args": {"path": "data.csv"}}'},
    {"role": "user",      "content": "Resultado da tool: Tool 'csv_para_json' não existe. Disponíveis: [...]"},
    {"role": "assistant", "content": '{"tool": "csv_para_json", "args": {"path": "data.csv"}}'},
    {"role": "user",      "content": "Resultado da tool: Tool 'csv_para_json' não existe. Disponíveis: [...]"},
]

history_only = [m for m in messages_com_system if m["role"] != "system"]

check(
    len(history_only) == len(messages_com_system) - 1,
    f"system prompt descartado — probe tem {len(history_only)} mensagens",
    f"esperado {len(messages_com_system) - 1} mensagens, got {len(history_only)}",
)
check(
    all(m["role"] != "system" for m in history_only),
    "nenhuma mensagem system na probe",
    "probe ainda contém mensagem system",
)

roles = [m["role"] for m in history_only]
esperado = ["user", "assistant", "user", "assistant", "user"]
check(
    roles == esperado,
    f"ordem correta: {roles}",
    f"ordem inesperada: {roles} (esperado {esperado})",
)


# ══════════════════════════════════════════════════════════════════════════════
print(f"\n{B}2. Validação da proposta — campos mínimos{RST}")
print(HR)

# replica a lógica de validação do _ask_model_for_tool_proposal
def valida_proposta(parsed: dict) -> bool:
    return (
        parsed.get("criar_tool") is True
        and bool(parsed.get("nome"))
        and bool(parsed.get("descricao"))
    )

casos = [
    # (parsed,                                                    esperado, descricao)
    (
        {"criar_tool": True, "nome": "csv_para_json", "descricao": "converte CSV para JSON", "parametros": []},
        True,
        "proposta completa — deve aceitar",
    ),
    (
        {"criar_tool": False},
        False,
        "criar_tool=false — deve rejeitar",
    ),
    (
        {"criar_tool": True, "nome": "", "descricao": "algo"},
        False,
        "nome vazio — deve rejeitar",
    ),
    (
        {"criar_tool": True, "nome": "csv_para_json", "descricao": ""},
        False,
        "descricao vazia — deve rejeitar",
    ),
    (
        # modelo respondeu no formato agêntico em vez de {"criar_tool": ...}
        {"tool": "create_tool", "args": {"tool_name": "csv_para_json", "tool_code": "..."}},
        False,
        "resposta no formato agêntico — deve rejeitar",
    ),
    (
        {"done": True, "message": "não consegui completar"},
        False,
        "resposta done — deve rejeitar",
    ),
    (
        {"criar_tool": True, "nome": "csv_para_json"},
        False,
        "sem descricao — deve rejeitar",
    ),
]

for parsed, esperado, desc in casos:
    resultado = valida_proposta(parsed)
    check(resultado == esperado, desc, f"FALHOU: {desc}")


# ══════════════════════════════════════════════════════════════════════════════
print(f"\n{B}3. Montagem da instrução de criação (_build_create_instruction){RST}")
print(HR)

# replica _build_create_instruction do cli.py
def build_create_instruction(proposal: dict) -> str:
    params_desc = "; ".join(
        f"{p['nome']} ({p.get('tipo', 'str')}): {p.get('descricao', '')}"
        for p in proposal.get("parametros", [])
    )
    return (
        f"Crie a tool '{proposal['nome']}' que: {proposal['descricao']}. "
        + (f"Parâmetros: {params_desc}." if params_desc else "Sem parâmetros além dos necessários.")
    )

proposta_com_params = {
    "nome": "csv_para_json",
    "descricao": "converte um arquivo CSV para JSON",
    "parametros": [
        {"nome": "path",   "tipo": "str", "descricao": "caminho do CSV"},
        {"nome": "output", "tipo": "str", "descricao": "caminho do JSON de saída"},
    ],
}

proposta_sem_params = {
    "nome": "get_ip",
    "descricao": "retorna o IP público da máquina",
    "parametros": [],
}

instrucao_com = build_create_instruction(proposta_com_params)
instrucao_sem = build_create_instruction(proposta_sem_params)

check("csv_para_json" in instrucao_com,  "nome da tool presente na instrução", "nome ausente")
check("path" in instrucao_com,           "param 'path' presente na instrução", "param 'path' ausente")
check("output" in instrucao_com,         "param 'output' presente na instrução", "param 'output' ausente")
check("Sem parâmetros" in instrucao_sem, "tool sem params — frase correta gerada", "frase 'Sem parâmetros' ausente")

print(f"\n  {DIM}instrução com params:{RST}")
print(f"  {instrucao_com}")
print(f"\n  {DIM}instrução sem params:{RST}")
print(f"  {instrucao_sem}")


# ══════════════════════════════════════════════════════════════════════════════
print()
print(HR)
if all_passed:
    print(f"  {G}Todos os checks passaram.{RST}\n")
else:
    print(f"  {R}Alguns checks falharam — veja acima.{RST}\n")
    sys.exit(1)
