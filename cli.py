"""
CLI interativa do agente — TUI com rich.
Mantém histórico da conversa, mostra steps em tempo real e tools carregadas.

Uso:
  python cli.py
  python cli.py --agent csv_manager
  python cli.py --agent general --model gemma4:cloud
  python cli.py --agent dev_helper --safe
  python cli.py --list-agents
"""

import sys
import json
import base64
import re
import argparse
from pathlib import Path
from datetime import datetime

import pyperclip
import requests
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.rule import Rule
from rich.markup import escape
from rich.live import Live
from rich.prompt import Prompt
from rich.spinner import Spinner
from prompt_toolkit import prompt as pt_prompt
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.styles import Style as PtStyle

from tools_registry import load_tools, tools_schema
from agent_loader import load_agent, filter_tools, list_agents
from history_store import HistoryStore, DB_PATH
from history_ui import SessionPicker, format_conversation_preview, build_context_injection

# ── config ────────────────────────────────────────────────────────────────────
OLLAMA_URL       = "http://localhost:11434/api/chat"
DEFAULT_MODEL    = "gemma4:cloud" #ou local "gemma4:e2b-it-qat"
DEFAULT_AGENT    = "general"
MAX_STEPS        = 6
MAX_STEPS_TASK   = 9   # +3 para tasks 
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}

# Tools que executam código arbitrário — bloqueadas com --safe
UNSAFE_TOOLS = {"run_script"}

# ── paleta ────────────────────────────────────────────────────────────────────
CLR_BORDER  = "bright_black"
CLR_USER    = "cyan"
CLR_AGENT   = "green"
CLR_TOOL    = "yellow"
CLR_STEP    = "bright_black"
CLR_OK      = "green"
CLR_ERR     = "red"
CLR_WARN    = "yellow"

console = Console()

# ── nome da ferramenta ────────────────────────────────────────────────────────
NAME = "Ciel CLI"   # altere aqui quando decidir o nome definitivo
VERSION = "1.0.0"

def _banner() -> str:
    """Banner minimalista: ponto + nome em negrito."""
    return (
        f"  [bold white]{NAME}[/bold white] "
        f"[bright_black](V{VERSION})[/bright_black]"
    )


# ── helpers de display ────────────────────────────────────────────────────────

def header(model: str, agent_name: str, tools: dict, safe: bool = False):
    console.clear()

    n_perm = sum(1 for v in tools.values() if v.get("categoria", "permanente") == "permanente")
    n_temp = len(tools) - n_perm
    tools_line = f"{len(tools)} tools"
    if n_temp:
        tools_line += f"  [bright_black]({n_perm} permanentes · {n_temp} temp)[/bright_black]"

    safe_badge = "  [yellow]⚠ modo seguro[/yellow]\n" if safe else ""

    ascii_art = """
             ██████╗██╗███████╗██╗     
            ██╔════╝██║██╔════╝██║     
            ██║     ██║█████╗  ██║     
            ██║     ██║██╔══╝  ██║     
            ╚██████╗██║███████╗███████╗
             ╚═════╝╚═╝╚══════╝╚══════╝
    """

    content = (
        f"{_banner()}\n"
        f"\n"
        f"{safe_badge}"
        f"  [bright_black]agent:[/bright_black] [cyan]{agent_name}[/cyan]   "
        f"[bright_black]model:[/bright_black] [white]{model}[/white]\n"
        f"  [bright_black]tools:[/bright_black] [yellow]{tools_line}[/yellow]\n"
        f"{ascii_art}"
        f"\n"
        f"  [bright_black]/  comandos  ·  tab  completar  ·  /ajuda  ajuda[/bright_black] \n"
    )
    console.print(Panel(
        content,
        border_style=CLR_BORDER,
        padding=(0, 1),
        expand=False,
    ))
    console.print()


def print_history_entry(role: str, content: str, ts: str = "", tokens_in: int = 0, tokens_out: int = 0):
    if role == "user":
        label = f"[{CLR_USER}]você[/{CLR_USER}]"
        style = CLR_USER
    else:
        label = f"[{CLR_AGENT}]agente[/{CLR_AGENT}]"
        style = CLR_AGENT

    ts_str = f" [bright_black]{ts}[/bright_black]" if ts else ""
    
    # tokens alinhados à direita — só exibe se tiver valor
    if tokens_in or tokens_out:
        tok_str = f"[bright_black]↑{tokens_in:,} ↓{tokens_out:,}[/bright_black]"
        width = console.width
        # calcula espaço entre label+ts e tokens
        label_plain = f"{role}  {ts}"  # aproximação do tamanho real
        pad = width - len(label_plain) - len(f"↑{tokens_in:,} ↓{tokens_out:,}") - 2
        header_line = f"{label}{ts_str}{' ' * max(pad, 4)}{tok_str}"
    else:
        header_line = f"{label}{ts_str}"

    console.print(header_line)
    console.print(Panel(escape(content), border_style=style, padding=(0, 1)))
    console.print()


def print_step(step: int, label: str, content: str, color: str = CLR_STEP):
    console.print(
        f"  [{color}]step {step} › {label}[/{color}]  "
        f"[bright_black]{escape(content[:120])}[/bright_black]"
    )


def print_rule(label: str = ""):
    console.print(Rule(label, style=CLR_BORDER))


def print_agent_footer(n_steps: int):
    """Rodapé discreto com o número de steps usados pelo agente."""
    if n_steps > 1:
        console.print(f"  [bright_black]{n_steps} steps[/bright_black]\n")


def print_turn_separator():
    """Separador sutil entre rodadas (user + agente)."""
    console.print(Rule(style=CLR_BORDER))
    console.print()


def print_agents_list():
    """Imprime os agentes disponíveis e sai."""
    agents = list_agents()
    console.print("\n[bold white]Agentes disponíveis:[/bold white]")
    for a in agents:
        try:
            info = load_agent(a)
            console.print(f"  [yellow]{a}[/yellow]  [bright_black]{info['description'][:70]}[/bright_black]")
        except Exception:
            console.print(f"  [yellow]{a}[/yellow]")
    console.print()


def print_auto_tool_proposal(proposal: dict):
    """Exibe a proposta de nova tool de forma legível."""
    nome   = proposal.get("nome", "?")
    desc   = proposal.get("descricao", "?")
    params = proposal.get("parametros", [])

    console.print()
    console.print(Panel(
        f"[bold]Nome:[/bold] [yellow]{nome}[/yellow]\n"
        f"[bold]O que faz:[/bold] {desc}\n"
        f"[bold]Parâmetros:[/bold] "
        + (", ".join(f"[cyan]{p['nome']}[/cyan] ({p.get('tipo','str')})" for p in params) or "nenhum"),
        title="[yellow]⚡ Auto Tool — proposta do agente[/yellow]",
        border_style=CLR_WARN,
        padding=(0, 1),
    ))
    console.print()


# ── core do agente ────────────────────────────────────────────────────────────

def build_system_prompt(agent_info: dict, schema: list, web_base_url: str | None = None, session_id: str | None = None) -> str:
    """Combina o system prompt do agente com o schema de tools disponíveis."""
    
    # carrega instruções core
    core_prompt = ""
    core_path = Path("system/core_prompt.md")
    if core_path.exists():
        core_prompt = core_path.read_text(encoding="utf-8").strip()

    tools_block = json.dumps(schema, ensure_ascii=False, indent=2)
    parts = [
        core_prompt,
        f"\n\n---\n\n{agent_info['system_prompt']}",
        f"\n\n## Tools disponíveis\n{tools_block}",
        f"\n\n## Sessão atual"
        f"\nagent_id: {agent_info.get('id', 'general')}"
        f"\nsession_id: {session_id or f'_nosession_{id(agent_info)}'}",
    ]

    if web_base_url:
        parts.append(
            f"\n\n## Contexto de execução"
            f"\nVocê está rodando como servidor web acessível em {web_base_url}."
            f"\nQuando gerar ou salvar arquivos para o usuário, salve SEMPRE em data/user/ ."
            f"\nNa sua resposta final (done → message), mencione o arquivo com o caminho relativo"
            f" exato, por exemplo: \'arquivo salvo em: data/user/relatorio.pdf\'."
            f"\nO frontend vai converter esse caminho em link de download automaticamente."
        )

    return "".join(parts)


def parse_response(text: str) -> dict:
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    return {"error": f"resposta não parseável: {text[:200]}"}


def build_first_message(user_input: str, image_b64: str | None = None) -> dict:
    # imagem passada diretamente (ex: vinda do servidor web)
    if image_b64:
        return {
            "role": "user",
            "content": user_input or "Descreva e analise esta imagem.",
            "images": [image_b64],
        }
    # imagem referenciada por path no input (modo CLI)
    path = Path(user_input.strip())
    if path.exists() and path.suffix.lower() in IMAGE_EXTENSIONS:
        with open(path, "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode()
        return {
            "role": "user",
            "content": "Extraia os dados relevantes desta imagem e adicione ao CSV.",
            "images": [img_b64],
        }
    return {"role": "user", "content": user_input}


def call_model(messages: list, model: str) -> tuple[str, int, int]:
    payload = {"model": model, "messages": messages, "stream": False}
    resp = requests.post(OLLAMA_URL, json=payload, timeout=120)
    resp.raise_for_status()
    data = resp.json()
    content   = data["message"]["content"]
    tokens_in  = data.get("prompt_eval_count", 0)  # tokens de entrada
    tokens_out = data.get("eval_count", 0)          # tokens de saída
    return content, tokens_in, tokens_out


def call_model_with_spinner(messages: list, model: str) -> tuple[str, int, int]:
    """Chama o modelo exibindo um spinner enquanto aguarda a resposta."""
    with Live(
        Spinner("dots", text=" [bright_black]pensando…[/bright_black]"),
        console=console,
        refresh_per_second=10,
        transient=True,
    ):
        return call_model(messages, model)


def _ask_model_for_tool_proposal(messages: list, model: str) -> dict | None:
    """
    Faz uma chamada extra ao modelo perguntando se uma nova tool
    resolveria a tarefa. Retorna a proposta parseada ou None.
    """
    probe = messages + [{
        "role": "user",
        "content": (
            "Você não conseguiu completar a tarefa com as tools disponíveis. "
            "Analise a tarefa e responda APENAS em JSON puro, sem texto adicional:\n\n"
            "Se uma nova tool poderia resolver:\n"
            '{"criar_tool": true, "nome": "nome_em_snake_case", '
            '"descricao": "o que a tool faz em uma linha", '
            '"parametros": [{"nome": "param", "tipo": "str", "descricao": "o que é"}]}\n\n'
            "Se a tarefa é impossível ou não depende de uma tool:\n"
            '{"criar_tool": false}'
        ),
    }]
    try:
        raw , _ ,_ = call_model(probe, model)
        parsed = parse_response(raw)
        if parsed.get("criar_tool") is True:
            # valida campos mínimos
            if parsed.get("nome") and parsed.get("descricao"):
                return parsed
    except Exception:
        pass
    return None


def load_task(path: Path) -> dict | None:
    """
    Lê um arquivo .md de task e retorna dict com:
      { "nome": str, "objetivo": str, "acoes": list[str], "resultado": str }
    Retorna None se o arquivo não seguir o formato mínimo.
    """
    if not path.exists():
        return None

    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    nome     = ""
    objetivo = ""
    acoes    = []
    resultado = ""
    section  = None

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## task:"):
            nome = stripped.split(":", 1)[1].strip()
        elif stripped.startswith("objetivo:"):
            objetivo = stripped.split(":", 1)[1].strip()
            section  = None
        elif stripped == "ações:" or stripped == "acoes:":
            section = "acoes"
        elif stripped.startswith("resultado esperado:"):
            resultado = stripped.split(":", 1)[1].strip()
            section   = None
        elif section == "acoes" and stripped.startswith("-"):
            acoes.append(stripped[1:].strip())

    if not nome or not acoes:
        return None

    return {"nome": nome, "objetivo": objetivo, "acoes": acoes, "resultado": resultado}


def find_tasks(query: str, tasks_dir: Path) -> list[Path]:
    """
    Busca tasks cujo nome contenha o query (case-insensitive).
    Retorna lista de paths ordenada por relevância (match exato primeiro).
    """
    if not tasks_dir.exists():
        return []
    q = query.lower().replace(" ", "-")
    matches = [p for p in tasks_dir.glob("*.md") if q in p.stem.lower()]
    # match exato primeiro
    matches.sort(key=lambda p: (0 if p.stem.lower() == q else 1, p.stem))
    return matches


def build_task_prompt(task: dict) -> str:
    """
    Converte a task num prompt direto pro run_agent.
    O agente recebe o plano pronto e age como executor/inspetor.
    """
    acoes_fmt = "\n".join(f"  {i+1}. {a}" for i, a in enumerate(task["acoes"]))
    return (
        f"Execute a seguinte task: {task['nome']}\n\n"
        f"Objetivo: {task['objetivo']}\n\n"
        f"Ações a executar em ordem:\n{acoes_fmt}\n\n"
        f"Resultado esperado: {task['resultado']}\n\n"
        f"Siga as ações na ordem indicada. Se uma ação especificar [tool: nome], "
        f"use essa tool. Caso contrário, escolha a tool mais adequada disponível."
    )


def run_agent(
    user_input: str,
    tools: dict,
    schema: list,
    model: str,
    agent_info: dict,
    history: list[dict] | None = None,
    image_b64: str | None = None,
    web_base_url: str | None = None,
    context_injection: str | None = None,
    session_id: str | None = None,
    max_steps: int = MAX_STEPS,   
) -> str | dict:
    """
    Executa o loop agêntico.

    Retorna:
      str  → mensagem final (sucesso ou falha simples)
      dict → {"status": "needs_tool", "proposal": {...}}
               quando o modelo propõe criar uma nova tool

    context_injection: bloco de texto (resumo de sessão anterior) adicionado
                       ao final do system prompt para dar contexto de branch.
    """
    # ── contadores de tokens ───────────────────────────────────────────────
    total_in  = 0
    total_out = 0
    system_prompt = build_system_prompt(agent_info, schema, web_base_url=web_base_url, session_id=session_id)
    if context_injection:
        system_prompt = f"{system_prompt}\n\n{context_injection}"

    # Reconstrói contexto dos turnos anteriores para o modelo
    context: list[dict] = []
    for entry in (history or []):
        role = "user" if entry["role"] == "user" else "assistant"
        context.append({"role": role, "content": entry["content"]})

    messages = [
        {"role": "system", "content": system_prompt},
        *context,
        build_first_message(user_input, image_b64=image_b64),
    ]

    print_rule("executando")

    for step in range(1, max_steps + 1):
        print_step(step, "modelo", "aguardando…", CLR_STEP)

        try:
            #raw = call_model_with_spinner(messages, model)
            raw, t_in, t_out = call_model_with_spinner(messages, model)
            total_in  += t_in
            total_out += t_out
        except requests.RequestException as e:
            console.print(f"  [{CLR_ERR}]erro de conexão: {e}[/{CLR_ERR}]")
            # erro de conexão
            return f"Erro de conexão com Ollama: {e}", total_in, total_out

        parsed = parse_response(raw)

        if parsed.get("done"):
            msg = parsed.get("message", "Concluído.")
            print_step(step, "done", msg, CLR_OK)
            print_rule()
            print_agent_footer(step)
            return msg, total_in, total_out

        if "error" in parsed:
            print_step(step, "parse error", parsed["error"], CLR_ERR)
            messages.append({"role": "assistant", "content": raw})
            messages.append({
                "role": "user",
                "content": "Resposta inválida. Retorne APENAS JSON no formato especificado.",
            })
            continue

        tool_name = parsed.get("tool", "")
        args      = parsed.get("args", {})

        print_step(step, f"tool › {tool_name}", json.dumps(args, ensure_ascii=False)[:80], CLR_TOOL)

        if tool_name not in tools:
            feedback = f"Tool '{tool_name}' não existe. Disponíveis: {list(tools.keys())}"
            print_step(step, "erro", feedback, CLR_ERR)
        else:
            try:
                #feedback = tools[tool_name]["fn"](**args)
                if tool_name in ("list_sources", "search_knowledge"):
                    args.setdefault("agent_id", agent_info.get("id", "general"))
                    args.setdefault("session_id", str(session_id) if session_id else "")
                # ── injeta session_id no modelo secundário ────────────────────
                if tool_name == "secondary_model":
                    args.setdefault("session_id", str(session_id) if session_id else "_nosession")
                feedback = tools[tool_name]["fn"](**args)
                print_step(step, "resultado", str(feedback)[:100], CLR_OK)

                # reload automático após criação de tool ──────────────────────

                if tool_name in ("create_tool", "create_temp_tool") and "Erro" not in str(feedback):
                    all_updated = load_tools()
                    tools.clear()
                    tools.update(filter_tools(all_updated, agent_info.get("allowed_tools")))
                    schema.clear()
                    schema.extend(tools_schema(tools))
                    messages[0]["content"] = build_system_prompt(agent_info, schema)
                    print_step(step, "registry", f"{len(tools)} tools carregadas", CLR_OK)

            except TypeError as e:
                # mostra assinatura real pro modelo corrigir os args ──────────
                import inspect
                sig      = inspect.signature(tools[tool_name]["fn"])
                feedback = (
                    f"Args inválidos para '{tool_name}': {e}. "
                    f"Assinatura correta: {tool_name}{sig}"
                )
                print_step(step, "erro", feedback, CLR_ERR)
            except Exception as e:
                feedback = f"Erro ao executar tool: {e}"
                print_step(step, "erro", feedback, CLR_ERR)

        messages.append({"role": "assistant", "content": raw})
        messages.append({"role": "user", "content": f"Resultado da tool: {feedback}"})

    # ── steps esgotados: tenta propor auto tool ───────────────────────────────
    print_rule()
    console.print(f"  [{CLR_WARN}]steps esgotados — verificando se uma nova tool resolveria...[/{CLR_WARN}]")
    proposal = _ask_model_for_tool_proposal(messages, model)


    if proposal:
        return {"status": "needs_tool", "proposal": proposal}, total_in, total_out
    # steps esgotados sem auto tool
    return "⚠ Limite de steps atingido sem conclusão.", total_in, total_out


# ── loop principal da CLI ─────────────────────────────────────────────────────

def _build_create_instruction(proposal: dict) -> str:
    """Monta a instrução de criação de tool a partir da proposta."""
    params_desc = "; ".join(
        f"{p['nome']} ({p.get('tipo', 'str')}): {p.get('descricao', '')}"
        for p in proposal.get("parametros", [])
    )
    return (
        f"Crie a tool '{proposal['nome']}' que: {proposal['descricao']}. "
        + (f"Parâmetros: {params_desc}." if params_desc else "Sem parâmetros além dos necessários.")
    )


def _reload_tools(agent_info: dict, safe: bool) -> tuple[dict, list]:
    """Recarrega tools do disco e devolve (tools, schema) filtrados."""
    all_tools = load_tools()
    tools     = filter_tools(all_tools, agent_info["allowed_tools"])
    if safe:
        tools = {k: v for k, v in tools.items() if k not in UNSAFE_TOOLS}
    return tools, tools_schema(tools)


def _handle_auto_tool(
    result: dict,
    user_input: str,
    tools: dict,
    schema: list,
    model: str,
    agent_info: dict,
    history: list[dict],
    safe: bool,
) -> tuple[str, dict, list]:
    """
    Lida com o retorno needs_tool do run_agent.

    Pergunta ao usuário entre 3 opções:
      [s] salvar permanente  → tools/<nome>.py  via create_tool
      [t] temporária         → tools/temp/<nome>.py via create_temp_tool
      [n] não criar          → falha normal

    Retorna (mensagem_final, tools_atualizado, schema_atualizado).
    """
    # ── contadores de sessão ───────────────────────────────────────────────
    session_tokens_in  = 0
    session_tokens_out = 0

    proposal  = result["proposal"]
    tool_name = proposal["nome"]
    print_auto_tool_proposal(proposal)

    console.print(
        f"  [bold]{tool_name}[/bold]\n"
        f"  [{CLR_OK}][s][/{CLR_OK}] salvar permanente   "
        f"  [{CLR_WARN}][t][/{CLR_WARN}] tool temporária   "
        f"  [{CLR_ERR}][n][/{CLR_ERR}] não criar\n"
    )
    confirm = Prompt.ask(
        f"[{CLR_WARN}]O que fazer?[/{CLR_WARN}]",
        choices=["s", "t", "n"],
        default="n",
    ).strip().lower()

    if confirm == "n":
        return "⚠ Tarefa não concluída — tool necessária não foi criada.", tools, schema

    # ── decide qual tool de criação usar ─────────────────────────────────────
    is_temp          = (confirm == "t")
    create_tool_name = "create_temp_tool" if is_temp else "create_tool"
    tipo_label       = "temporária" if is_temp else "permanente"

    # verifica se a tool de criação está disponível
    if create_tool_name not in tools:
        console.print(f"  [{CLR_ERR}]tool '{create_tool_name}' não encontrada no registry.[/{CLR_ERR}]")
        return f"⚠ Criação falhou — '{create_tool_name}' não disponível.", tools, schema

    console.print(f"\n  [{CLR_WARN}]criando tool {tipo_label}...[/{CLR_WARN}]")

    create_instruction = _build_create_instruction(proposal)
    # instrução extra pra tool temporária — garante que o modelo usa a tool certa
    if is_temp:
        create_instruction += " Use a tool 'create_temp_tool' para salvar."

    create_result,  _, _ = run_agent(
        create_instruction,
        tools,
        schema,
        model,
        agent_info,
        history=None,  # contexto isolado — não contamina histórico da tarefa
    )

    create_msg = create_result if isinstance(create_result, str) else "?"
    console.print(f"  [{CLR_OK}]resultado: {escape(str(create_msg)[:120])}[/{CLR_OK}]\n")

    # ── recarrega e valida ────────────────────────────────────────────────────
    tools_antes        = set(tools.keys())
    new_tools, new_schema = _reload_tools(agent_info, safe)
    tools_novas        = set(new_tools.keys()) - tools_antes

    from tools_registry import TOOLS_DIR, TOOLS_TEMP_DIR
    console.print(f"  [bright_black]registry: {TOOLS_DIR} | temp: {TOOLS_TEMP_DIR}[/bright_black]")
    console.print(f"  [bright_black]tools novas detectadas: {tools_novas or 'nenhuma'}[/bright_black]\n")

    # aceita o nome da proposta OU qualquer tool nova que apareceu no registry
    tool_criada = tool_name if tool_name in new_tools else (
        next(iter(tools_novas)) if len(tools_novas) == 1 else None
    )

    if not tool_criada:
        tools_dir  = TOOLS_TEMP_DIR if is_temp else TOOLS_DIR
        candidatos = list(tools_dir.glob(f"*{tool_name}*.py"))
        if candidatos:
            console.print(
                f"  [{CLR_WARN}]arquivo encontrado mas não importado: "
                f"{candidatos[0].name} — verifique erros de sintaxe.[/{CLR_WARN}]"
            )
        else:
            console.print(f"  [{CLR_ERR}]nenhum arquivo criado em {tools_dir}[/{CLR_ERR}]")
        return "⚠ Criação da tool falhou — tarefa não concluída.", new_tools, new_schema

    categoria = new_tools[tool_criada].get("categoria", "permanente")
    console.print(
        f"  [{CLR_OK}]tool '{tool_criada}' [{categoria}] carregada. "
        f"Reexecutando tarefa original...[/{CLR_OK}]\n"
    )

    # ── reexecuta tarefa original ─────────────────────────────────────────────
    retry_result, _, _ = run_agent(
        user_input,
        new_tools,
        new_schema,
        model,
        agent_info,
        history=history[:-1]
    )

    # registra uso no temp-log se for temporária e executou com sucesso
    if is_temp and isinstance(retry_result, str) and "temp_log" in new_tools:
        try:
            new_tools["temp_log"]["fn"](tool_criada)
        except Exception:
            pass

    # se o retry também pedir tool, não entra em loop
    if isinstance(retry_result, dict) and retry_result.get("status") == "needs_tool":
        return "⚠ Tarefa não concluída mesmo após criar a tool.", new_tools, new_schema

    return retry_result, new_tools, new_schema


def _save_session(
    store: "HistoryStore",
    history: list[dict],
    agent_info: dict,
    model: str,
    agent_id: str,
    console: "Console",
    existing_session_id: int | None = None,
) -> int:
    """
    Salva (ou atualiza) a sessão atual no banco.
    Pede ao modelo um resumo estruturado da conversa (com título embutido).
    Retorna o session_id (novo ou existente).
    """
    # título provisório: primeiras 8 palavras do primeiro turno user
    # (substituído pelo título do resumo se o modelo gerar um)
    first_user  = next((e["content"] for e in history if e["role"] == "user"), "")
    fallback_title = " ".join(first_user.split()[:8]) if first_user else "sem título"

    if existing_session_id is None:
        sid = store.new_session(agent_id, fallback_title)
        # persiste todos os turnos da sessão de uma vez
        for entry in history:
            store.append_turn(sid, entry["role"], entry["content"], entry.get("ts", ""))
    else:
        sid = existing_session_id
        # turnos já foram salvos em tempo real
        sess = store.get_session(sid)
        if sess and not sess["title"]:
            store.update_title(sid, fallback_title)

    # gera resumo + título via modelo
    console.print("  [bright_black]gerando resumo da sessão…[/bright_black]")
    try:
        conv_text = "\n".join(
            f"[{'user' if e['role'] == 'user' else 'agente'}] {e['content']}"
            for e in history
        )
        prompt_resumo = (
            "Você é um assistente técnico. Leia a conversa abaixo e produza um resumo "
            "estruturado em português com EXATAMENTE estas três seções:\n\n"
            "TÍTULO: (1 linha curta, máx. 60 chars) — título descritivo da sessão\n"
            "CONTEXTO: (1-3 frases) — o que estava sendo feito e por quê\n"
            "ESTADO: (lista de bullets) — decisões tomadas, tools criadas, arquivos "
            "modificados, problemas resolvidos, pendências\n\n"
            "Seja objetivo e específico. Máximo de 320 palavras.\n\n"
            f"CONVERSA:\n{conv_text[:6000]}"
        )
        messages = [
            {"role": "system", "content": "Responda apenas com o resumo, sem introdução."},
            {"role": "user",   "content": prompt_resumo},
        ]
        import requests as _req
        payload  = {"model": model, "messages": messages, "stream": False}
        resp     = _req.post(OLLAMA_URL, json=payload, timeout=120)
        resp.raise_for_status()
        summary_raw = resp.json()["message"]["content"].strip()

        # extrai o título da primeira linha "TÍTULO: ..."
        title_from_summary = fallback_title
        summary_lines = summary_raw.splitlines()
        clean_lines   = []
        for line in summary_lines:
            if line.upper().startswith("TÍTULO:") or line.upper().startswith("TITULO:"):
                extracted = line.split(":", 1)[1].strip()
                if extracted:
                    title_from_summary = extracted[:60]
            else:
                clean_lines.append(line)
        summary = "\n".join(clean_lines).strip()

        store.update_title(sid, title_from_summary)
        store.save_summary(sid, summary)
        console.print(
            f"  [green]sessão #{sid} salva.[/green] "
            f"[bright_black]{title_from_summary}[/bright_black]\n"
        )
    except Exception as e:
        console.print(f"  [yellow]resumo falhou ({e}), sessão salva sem resumo.[/yellow]\n")

    return sid


def main():
    parser = argparse.ArgumentParser(description="Agent CLI")
    parser.add_argument("--model",       default=DEFAULT_MODEL,  help="modelo Ollama")
    parser.add_argument("--agent",       default=DEFAULT_AGENT,  help="persona do agente (nome do .md em /agents)")
    parser.add_argument("--safe",        action="store_true",    help="desabilita tools de execução arbitrária")
    parser.add_argument("--list-agents", action="store_true",    help="lista agentes disponíveis e sai")
    args = parser.parse_args()

    # ── contadores de sessão ───────────────────────────────────────────────
    session_tokens_in  = 0
    session_tokens_out = 0

    if args.list_agents:
        print_agents_list()
        sys.exit(0)

    # carrega agente
    try:
        agent_info = load_agent(args.agent)
    except FileNotFoundError as e:
        console.print(f"[red]Erro:[/red] {e}")
        sys.exit(1)

    # carrega e filtra tools
    all_tools = load_tools()
    tools = filter_tools(all_tools, agent_info["allowed_tools"])

    if args.safe:
        tools = {k: v for k, v in tools.items() if k not in UNSAFE_TOOLS}

    schema  = tools_schema(tools)
    history: list[dict] = []

    # ── history store ─────────────────────────────────────────────────────────
    store = HistoryStore(DB_PATH)
    current_session_id: int | None = None   # None até o user salvar ou digitar algo
    context_injection: str | None  = None   # resumo de sessão anterior (branch)

    header(args.model, agent_info["name"], tools, safe=args.safe)

    # ── prompt_toolkit: autocomplete ──────────────────────────────────────────
    CMDS = [
        "/sair", "/limpar", "/novo", "/task", "/tools", "/agente", 
        "/source", "/source --listar","/source --remover","/source --global","/source --limpar-orfas", "/limpar-temp",
        "/promover ", "/copiar", "/tokens", "/ajuda",
        "/history", "/history salvar", "/history exportar",
    ]
    pt_style = PtStyle.from_dict({"prompt": "ansibrightcyan bold"})

    def make_completer(tools_dict: dict) -> WordCompleter:
        tool_names  = list(tools_dict.keys())
        agent_names = [f"/agente {a}" for a in list_agents()]
        task_names   = [f"/task {p.stem}" for p in Path("tasks").glob("*.md")] if Path("tasks").exists() else []
        return WordCompleter(CMDS + tool_names + agent_names + task_names, sentence=True)

    completer = make_completer(tools)

    while True:
        try:
            user_input = pt_prompt("❯ ", completer=completer, style=pt_style).strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[bright_black]até mais.[/bright_black]")
            sys.exit(0)

        if not user_input:
            continue

        if user_input == "/sair":
            # pergunta se quer salvar antes de sair (só se tiver histórico não salvo)
            if history and current_session_id is None:
                console.print("  [bright_black]salvar esta conversa antes de sair?[/bright_black] \\[s/n] ", end="")
                try:
                    confirm_save = input().strip().lower()
                except (KeyboardInterrupt, EOFError):
                    confirm_save = "n"
                if confirm_save == "s":
                    current_session_id = _save_session(
                        store, history, agent_info, args.model, args.agent, console
                    )
            console.print("[bright_black]até mais.[/bright_black]")
            store.close()
            break

        if user_input == "/limpar":
            # só limpa a tela — não toca histórico nem sessão
            header(args.model, agent_info["name"], tools, safe=args.safe)
            continue

        if user_input == "/novo":
            # nova sessão: pergunta se salva, descarta histórico e reseta estado
            if history and current_session_id is None:
                console.print("  [bright_black]salvar a conversa antes de iniciar nova sessão?[/bright_black] \\[s/n] ", end="")
                try:
                    confirm_save = input().strip().lower()
                except (KeyboardInterrupt, EOFError):
                    confirm_save = "n"
                if confirm_save == "s":
                    _save_session(
                        store, history, agent_info, args.model, args.agent, console
                    )
            history.clear()
            current_session_id = None
            context_injection  = None
            header(args.model, agent_info["name"], tools, safe=args.safe)
            continue

        if user_input == "/tools":
            tbl = Table(box=None, show_header=False, padding=(0, 1))
            tbl.add_column(style="yellow",       no_wrap=True)
            tbl.add_column(style="cyan",         no_wrap=True, min_width=11)
            tbl.add_column(style="bright_black")
            for name, meta in sorted(tools.items()):
                cat  = meta.get("categoria", "permanente")
                cat_label = f"[temp]" if cat == "temp" else ""
                desc = meta["description"].split("\n")[0][:55]
                tbl.add_row(f"⚙ {name}", cat_label, desc)
            console.print(Panel(tbl, title="[yellow]tools[/yellow]", border_style=CLR_BORDER, padding=(0,1)))
            console.print()
            continue

        if user_input == "/agente":
            n = len(history)
            hist_info = f"{n} mensagens no histórico" if n else "histórico vazio"
            console.print(
                f"  [green]{agent_info['name']}[/green]  "
                f"[bright_black]{agent_info['description']}[/bright_black]\n"
                f"  [bright_black]{hist_info}[/bright_black]\n"
            )
            continue

        if user_input == "/tokens":
            total = session_tokens_in + session_tokens_out
            console.print(
                f"\n  [bright_black]tokens desta sessão:[/bright_black]\n"
                f"  [cyan]entrada:[/cyan]  {session_tokens_in:,}\n"
                f"  [cyan]saída:[/cyan]    {session_tokens_out:,}\n"
                f"  [cyan]total:[/cyan]    {total:,}\n"
            )
            continue

        if user_input.startswith("/agente "):
            novo_nome = user_input.split(" ", 1)[1].strip()
            if not novo_nome:
                continue

            # mesmo agente — só informa
            if novo_nome == agent_info.get("id", args.agent):
                console.print(
                    f"  [bright_black]agente atual já é '{novo_nome}'.[/bright_black]\n"
                )
                continue

            # tenta carregar antes de perguntar
            try:
                novo_agent_info = load_agent(novo_nome)
            except FileNotFoundError:
                agentes_disponiveis = list_agents()
                console.print(
                    f"  [{CLR_ERR}]agente '{novo_nome}' não encontrado.[/{CLR_ERR}]\n"
                    f"  [bright_black]disponíveis: {', '.join(agentes_disponiveis)}[/bright_black]\n"
                )
                continue

            # confirmação com info do histórico atual
            n = len(history)
            hist_aviso = (
                f"{n} mensagem{'ns' if n != 1 else ''} serão descartadas"
                if n else "histórico vazio"
            )
            console.print(
                f"  trocar para [green]{novo_agent_info['name']}[/green]? "
                f"[bright_black]{hist_aviso}.[/bright_black] \\[s/n] ",
                end=" "
            )
            try:
                confirm = input().strip().lower()
            except (KeyboardInterrupt, EOFError):
                confirm = "n"

            if confirm != "s":
                console.print("  [bright_black]cancelado.[/bright_black]\n")
                continue

            # pergunta se quer salvar o histórico atual antes de descartar
            if history and current_session_id is None:
                console.print(
                    "  [bright_black]salvar a conversa atual antes de trocar?[/bright_black] \\[s/n] ",
                    end=""
                )
                try:
                    confirm_save = input().strip().lower()
                except (KeyboardInterrupt, EOFError):
                    confirm_save = "n"
                if confirm_save == "s":
                    _save_session(
                        store, history, agent_info, args.model, args.agent, console
                    )

            # troca efetiva — nova sessão
            agent_info = novo_agent_info
            args.agent = novo_nome
            tools, schema = _reload_tools(agent_info, args.safe)
            history.clear()
            current_session_id = None
            context_injection  = None
            header(args.model, agent_info["name"], tools, safe=args.safe)
            completer = make_completer(tools)
            continue

        # ── /history ──────────────────────────────────────────────────────────
        if user_input in ("/history", ) or user_input.startswith("/history "):
            parts   = user_input.split(None, 1)
            subcmd  = parts[1].strip() if len(parts) > 1 else ""

            # /history salvar
            if subcmd == "salvar":
                if not history:
                    console.print("  [bright_black]nenhuma conversa para salvar.[/bright_black]\n")
                else:
                    current_session_id = _save_session(
                        store, history, agent_info, args.model, args.agent,
                        console, existing_session_id=current_session_id,
                    )
                continue

            # /history exportar
            if subcmd == "exportar":
                if current_session_id is None:
                    console.print("  [yellow]salve a conversa primeiro com /history salvar[/yellow]\n")
                else:
                    try:
                        out = store.export_markdown(current_session_id)
                        console.print(f"  [green]exportado:[/green] [white]{out}[/white]\n")
                    except Exception as e:
                        console.print(f"  [red]erro ao exportar: {e}[/red]\n")
                continue

            # /history <agent> ou /history (todas)
            agent_filter = subcmd if subcmd and subcmd not in ("salvar", "exportar") else None
            sessions = store.list_sessions(agent_filter)

            if not sessions:
                msg = f"nenhuma sessão salva para '{agent_filter}'." if agent_filter else "nenhuma sessão salva ainda."
                console.print(f"  [bright_black]{msg}[/bright_black]\n")
                continue

            title_line = f"histórico — {agent_filter}" if agent_filter else "histórico — todos os agentes"
            picked = SessionPicker(sessions, title=title_line).run()

            if picked is None:
                console.print("  [bright_black]cancelado.[/bright_black]\n")
                continue

            # mostra a conversa selecionada
            turns = store.get_turns(picked["id"])
            console.print()
            preview = format_conversation_preview(
                turns,
                session_title=picked["title"] or f"sessão #{picked['id']}",
            )
            console.print(preview)

            # pergunta o que fazer com ela
            console.print(
                "  [bright_black]"
                "[b] branch (retomar com resumo)   "
                "[e] exportar .md   "
                "[d] deletar   "
                "[enter] voltar"
                "[/bright_black]\n"
            )
            try:
                action = input("  ação: ").strip().lower()
            except (KeyboardInterrupt, EOFError):
                action = ""

            if action == "b":
                # ramifica: nova sessão filha, injeta resumo no contexto
                summary = picked["summary"]
                if not summary:
                    console.print(
                        "  [yellow]esta sessão não tem resumo. "
                        "O branch vai iniciar sem contexto anterior.[/yellow]\n"
                    )
                    context_injection = None
                else:
                    context_injection = build_context_injection(
                        summary, picked["title"] or "", picked["agent_id"]
                    )
                    console.print(
                        f"  [green]resumo injetado no contexto.[/green] "
                        f"[bright_black](~{len(summary.split())} palavras)[/bright_black]\n"
                    )

                # troca de agente se necessário
                if picked["agent_id"] != agent_info.get("id", args.agent):
                    try:
                        agent_info = load_agent(picked["agent_id"])
                        args.agent = picked["agent_id"]
                        tools, schema = _reload_tools(agent_info, args.safe)
                        completer = make_completer(tools)
                        console.print(f"  [green]agente trocado para '{agent_info['name']}'[/green]\n")
                    except FileNotFoundError:
                        console.print(
                            f"  [yellow]agente '{picked['agent_id']}' não encontrado, "
                            f"mantendo agente atual.[/yellow]\n"
                        )

                history.clear()
                current_session_id = store.branch_session(
                    picked["id"], agent_info.get("id", args.agent),
                    title=f"[branch] {picked['title'] or ''}"
                )
                header(args.model, agent_info["name"], tools, safe=args.safe)
                if context_injection:
                    console.print(
                        Panel(
                            f"[bright_black]{escape(context_injection[:400])}…[/bright_black]",
                            title="[cyan]contexto injetado[/cyan]",
                            border_style=CLR_BORDER,
                            padding=(0, 1),
                        )
                    )
                    console.print()

            elif action == "e":
                try:
                    out = store.export_markdown(picked["id"])
                    console.print(f"  [green]exportado:[/green] [white]{out}[/white]\n")
                except Exception as e:
                    console.print(f"  [red]erro: {e}[/red]\n")

            elif action == "d":
                console.print(f"  [red]deletar sessão '{picked['title']}'?[/red] \\[s/n] ", end="")
                try:
                    confirm_del = input().strip().lower()
                except (KeyboardInterrupt, EOFError):
                    confirm_del = "n"
                if confirm_del == "s":
                    store.delete_session(picked["id"])
                    console.print("  [bright_black]sessão removida.[/bright_black]\n")
                else:
                    console.print("  [bright_black]cancelado.[/bright_black]\n")
            continue

        # ── /source ──────────────────────────────────────────────────────────
        if user_input == "/source --listar":
            aid = agent_info.get("id", args.agent)
            sid = str(current_session_id) if current_session_id else None

            from knowledge.db import list_sources
            sources = list_sources(agent_id=aid, session_id=sid)

            if not sources:
                console.print("  [bright_black]nenhuma fonte indexada.[/bright_black]\n")
            else:
                console.print(f"  [white]{len(sources)} fonte(s):[/white]\n")
                for s in sources:
                    escopo = "[yellow]compartilhada[/yellow]" if s["session_id"] == "_shared" else f"[bright_black]sessão {s['session_id']}[/bright_black]"
                    console.print(
                        f"  [cyan]id={s['id']}[/cyan]  {s['filename']}  "
                        f"({s['n_chunks']} chunks · {escopo})"
                    )
                    if s.get("summary"):
                        resumo = s["summary"][:80].replace("\n", " ")
                        console.print(f"         [bright_black]↳ {resumo}…[/bright_black]")
                console.print()
            continue
        if user_input == "/source --limpar-orfas":
            from knowledge.db import cleanup_orphan_sources
            n = cleanup_orphan_sources()
            if n:
                console.print(f"  [green]✓ {n} sessão(ões) órfã(s) removida(s) do knowledge.db[/green]\n")
            else:
                console.print("  [bright_black]nenhuma fonte órfã encontrada.[/bright_black]\n")
            continue

        if user_input.startswith("/source --remover "):
            partes = user_input.split()
            if len(partes) < 3 or not partes[2].isdigit():
                console.print("  [yellow]uso: /source --remover <id>[/yellow]\n")
                continue

            source_id = int(partes[2])
            aid = agent_info.get("id", args.agent)

            from knowledge.db import get_source, delete_source
            source = get_source(source_id)

            if not source:
                console.print(f"  [red]fonte id={source_id} não encontrada.[/red]\n")
            elif source["agent_id"] != aid:
                console.print(f"  [red]fonte id={source_id} não pertence ao agente '{aid}'.[/red]\n")
            else:
                # se for cache de URL, apaga o arquivo local
                filepath = source.get("filepath", "")
                cache_path = Path(filepath)
                if "cache" in cache_path.parts:
                    try:
                        cache_path.unlink(missing_ok=True)
                        # remove a pasta da sessão se ficou vazia
                        if cache_path.parent.exists() and not any(cache_path.parent.iterdir()):
                            cache_path.parent.rmdir()
                    except Exception:
                        pass
                delete_source(source_id)
                console.print(
                    f"  [green]✓ fonte removida[/green] "
                    f"[bright_black](id={source_id} · {source['filename']})[/bright_black]\n"
                )
            continue

        if user_input.startswith("/source "):
            partes = user_input.split()
            eh_global = "--global" in partes
            partes_sem_flag = [p for p in partes[1:] if p != "--global"]
            print(partes, " ", partes_sem_flag)

            if not partes_sem_flag:
                console.print("  [yellow]uso: /source <arquivo|url> [--global][/yellow]\n")
                continue

            caminho = " ".join(partes_sem_flag)
            aid = agent_info.get("id", args.agent)

            if eh_global:
                sid = "_shared"
            else:
                if current_session_id is None:
                    current_session_id = store.new_session(
                        agent_id=aid,
                        title=f"sessão {datetime.now().strftime('%d/%m %H:%M')}",
                    )
                    console.print(f"  [bright_black]sessão criada (id={current_session_id})[/bright_black]")
                sid = str(current_session_id)

            escopo = "compartilhada" if eh_global else f"sessão {sid}"

            # ── NOVO: detecta URL ──────────────────────────────────────────
            eh_url = caminho.startswith(("http://", "https://"))

            if eh_url:
                console.print(f"  [bright_black]baixando e indexando '{caminho}'…[/bright_black]")
                console.print(f"  [bright_black]debug: agent_id='{aid}' session_id='{sid}'[/bright_black]")
                try:
                    from knowledge.ingest_url import ingest_url
                    source_id = ingest_url(
                        url        = caminho,
                        agent_id   = aid,
                        session_id = sid,
                        verbose    = False,
                    )
                    console.print(
                        f"  [green]✓ URL indexada[/green] "
                        f"[bright_black](id={source_id} · {escopo})[/bright_black]\n"
                    )
                except ValueError as e:
                    console.print(f"  [red]URL inválida: {e}[/red]\n")
                except RuntimeError as e:
                    console.print(f"  [red]erro ao baixar URL: {e}[/red]\n")
                except Exception as e:
                    console.print(f"  [red]erro ao indexar: {e}[/red]\n")
            # ── comportamento original: arquivo local ──────────────────────
            else:
                console.print(f"  [bright_black]indexando '{caminho}'…[/bright_black]")
                console.print(f"  [bright_black]debug: agent_id='{aid}' session_id='{sid}'[/bright_black]")
                try:
                    from knowledge.ingest import ingest
                    source_id = ingest(
                        filepath   = caminho,
                        agent_id   = aid,
                        session_id = sid,
                        verbose    = False,
                    )
                    console.print(
                        f"  [green]✓ fonte indexada[/green] "
                        f"[bright_black](id={source_id} · {escopo})[/bright_black]\n"
                    )
                except FileNotFoundError:
                    console.print(f"  [red]arquivo não encontrado: '{caminho}'[/red]\n")
                except Exception as e:
                    console.print(f"  [red]erro ao indexar: {e}[/red]\n")
            continue        

        if user_input in ("/ajuda", "/help", "/?"):
            console.print(Panel(
                "  [yellow]/sair[/yellow]                    encerra (pergunta se salva)\n"
                "  [yellow]/limpar[/yellow]                  limpa a tela\n"
                "  [yellow]/novo[/yellow]                    nova sessão (pergunta se salva)\n"
                "  [yellow]/task[/yellow]                    lista tasks disponíveis\n"
                "  [yellow]/task [white]<nome ou prompt>[/white][/yellow]  executa task pelo nome ou busca\n"
                "  [yellow]/task [white]<arquivo.md>[/white][/yellow]      executa task por caminho direto\n"
                "  [yellow]/tools[/yellow]                   lista as tools ativas\n"
                "  [yellow]/agente[/yellow]                  mostra agente e histórico atual\n"
                "  [yellow]/agente [white]<nome>[/white][/yellow]         troca de agente (nova sessão)\n"
                "  [yellow]/source [white]<arquivo>[/white][/yellow]        indexa arquivo nas fontes do agente\n"
                "  [yellow]/source [white]--listar[/white][/yellow]           lista fontes com IDs disponíveis\n"
                "  [yellow]/source [white]--remover <id>[/white][/yellow]     remove uma fonte pelo ID\n"
                "  [yellow]/source [white]--limpar-orfas[/white][/yellow]    remove fontes de sessões deletadas\n"
                "  [yellow]/source [white]--global <arquivo>[/white][/yellow] indexa como fonte compartilhada\n"
                "  [yellow]/limpar-temp[/yellow]             remove tools temporárias\n"
                "  [yellow]/promover[/yellow]                promove tool temp → permanente\n"
                "  [yellow]/tokens[/yellow]                  Mostra tokens gastos na sessão atual\n"
                "  [yellow]/copiar[/yellow]                  copia última resposta do agente\n"
                "  [yellow]/history[/yellow]                 lista todas as sessões salvas\n"
                "  [yellow]/history [white]<agente>[/white][/yellow]      filtra sessões por agente\n"
                "  [yellow]/history salvar[/yellow]          salva/atualiza sessão atual\n"
                "  [yellow]/history exportar[/yellow]        exporta sessão atual como .md\n"
                "  [yellow]/ajuda[/yellow]                   este menu",
                title="[white]comandos[/white]",
                border_style=CLR_BORDER,
                padding=(0, 1),
                expand=False,
            ))
            console.print()
            continue

        if user_input == "/limpar-temp":
            temp_dir = Path("tools/temp")
            removidas = []
            for f in temp_dir.glob("*.py"):
                if f.name != "__init__.py":
                    f.unlink()
                    removidas.append(f.stem)
            tools, schema = _reload_tools(agent_info, args.safe)
            header(args.model, agent_info["name"], tools, safe=args.safe)
            completer = make_completer(tools)
            if removidas:
                console.print(f"[bright_black]tools temp removidas: {', '.join(removidas)}[/bright_black]\n")
            else:
                console.print("[bright_black]nenhuma tool temporária encontrada.[/bright_black]\n")
            continue

        if user_input.startswith("/promover "):
            tool_name = user_input.split(" ", 1)[1].strip()
            src = Path("tools/temp") / f"{tool_name}.py"
            dst = Path("tools") / f"{tool_name}.py"
            if not src.exists():
                console.print(f"[red]Tool temp '{tool_name}' não encontrada.[/red]\n")
            elif dst.exists():
                console.print(f"[yellow]Já existe uma tool permanente com esse nome: {tool_name}[/yellow]\n")
            else:
                src.rename(dst)
                tools, schema = _reload_tools(agent_info, args.safe)
                header(args.model, agent_info["name"], tools, safe=args.safe)
                completer = make_completer(tools)
                console.print(f"[green]'{tool_name}' promovida para tools permanentes.[/green]\n")
            continue

        # Tasks
        if user_input.startswith("/task"):
            TASKS_DIR = Path("tasks")
            partes    = user_input.split(None, 1)
            arg       = partes[1].strip() if len(partes) > 1 else ""

            if not arg:
                # lista todas as tasks disponíveis
                if TASKS_DIR.exists():
                    tasks_disponiveis = sorted(TASKS_DIR.glob("*.md"))
                    if tasks_disponiveis:
                        console.print("\n[yellow]tasks disponíveis:[/yellow]")
                        for t in tasks_disponiveis:
                            td = load_task(t)
                            obj = td["objetivo"][:60] if td else "formato inválido"
                            console.print(f"  [cyan]{t.stem}[/cyan]  [bright_black]{obj}[/bright_black]")
                        console.print()
                    else:
                        console.print("  [bright_black]nenhuma task em tasks/[/bright_black]\n")
                else:
                    console.print("  [bright_black]pasta tasks/ não encontrada.[/bright_black]\n")
                continue

            # tenta carregar como arquivo direto
            task_path = Path(arg) if arg.endswith(".md") else TASKS_DIR / f"{arg}.md"

            if task_path.exists():
                candidates = [task_path]
            else:
                # busca por prompt livre
                candidates = find_tasks(arg, TASKS_DIR)

            if not candidates:
                console.print(f"  [red]nenhuma task encontrada para '{arg}'[/red]\n")
                continue

            if len(candidates) > 1:
                console.print(f"\n[yellow]tasks encontradas:[/yellow]")
                for i, c in enumerate(candidates, 1):
                    console.print(f"  [{CLR_OK}]{i}[/{CLR_OK}] {c.stem}")
                escolha = Prompt.ask(
                    f"[{CLR_WARN}]qual executar?[/{CLR_WARN}]",
                    choices=[str(i) for i in range(1, len(candidates) + 1)],
                )
                task_path = candidates[int(escolha) - 1]
            else:
                task_path = candidates[0]

            task = load_task(task_path)
            if not task:
                console.print(f"  [red]arquivo '{task_path.name}' não segue o formato de task.[/red]\n")
                continue

            # valida tools sugeridas antes de executar
            tools_sugeridas = []
            for acao in task["acoes"]:
                import re as _re
                m = _re.search(r"\[tool:\s*(\w+)\]", acao)
                if m:
                    tools_sugeridas.append(m.group(1))

            tools_ausentes = [t for t in tools_sugeridas if t not in tools]
            if tools_ausentes:
                console.print(
                    f"  [yellow]⚠ tools ausentes nesta task: "
                    f"{', '.join(tools_ausentes)}[/yellow]\n"
                    f"  [bright_black]o agente tentará criar as tools necessárias.[/bright_black]\n"
                )

            console.print(
                f"\n  [cyan]task:[/cyan] {task['nome']}  "
                f"[bright_black]{len(task['acoes'])} ações · até {MAX_STEPS_TASK} steps[/bright_black]\n"
            )

            task_prompt = build_task_prompt(task)
            ts = datetime.now().strftime("%a %H:%M")
            history.append({"role": "user", "content": f"/task {task['nome']}", "ts": ts})

            result, t_in, t_out = run_agent(
                task_prompt, tools, schema, args.model, agent_info,
                history=history[:-1],
                session_id=str(current_session_id) if current_session_id else None,
                max_steps=MAX_STEPS_TASK,          # <-- usa o limite expandido
            )
            session_tokens_in  += t_in
            session_tokens_out += t_out

            if isinstance(result, dict) and result.get("status") == "needs_tool":
                result, tools, schema = _handle_auto_tool(
                    result, task_prompt, tools, schema,
                    args.model, agent_info, history, safe=args.safe,
                )
                header(args.model, agent_info["name"], tools, safe=args.safe)
                completer = make_completer(tools)

            ts = datetime.now().strftime("%a %H:%M")
            history.append({"role": "agent", "content": result, "ts": ts})
            print_history_entry("agent", result, ts, t_in, t_out)
            print_turn_separator()

            if current_session_id is not None:
                store.append_turn(current_session_id, "agent", result, ts)

            continue

        if user_input == "/copiar":
            agent_entries = [e for e in history if e["role"] == "agent"]
            if not agent_entries:
                console.print("  [bright_black]nenhuma resposta para copiar.[/bright_black]\n")
            else:
                texto = agent_entries[-1]["content"]
                try:
                    pyperclip.copy(texto)
                    console.print("  [bright_black]última resposta copiada.[/bright_black]\n")
                except pyperclip.PyperclipException:
                    console.print(
                        "  [yellow]clipboard não disponível neste ambiente.[/yellow]\n"
                        "  [bright_black]instale xclip ou xsel no Linux, ou verifique permissões.[/bright_black]\n"
                    )
            continue

        ts = datetime.now().strftime("%a %H:%M")
        history.append({"role": "user", "content": user_input, "ts": ts})
        print_history_entry("user", user_input, ts)

        # salva turno do user em tempo real (se sessão já existir)
        if current_session_id is not None:
            store.append_turn(current_session_id, "user", user_input, ts)
            # título automático: primeiras 8 palavras do primeiro user_input
            sess = store.get_session(current_session_id)
            if sess and not sess["title"]:
                auto_title = " ".join(user_input.split()[:8])
                store.update_title(current_session_id, auto_title)

        # history[:-1] exclui o turno atual (já passado via user_input)
        result, t_in, t_out = run_agent(
            user_input, tools, schema, args.model, agent_info,
            history=history[:-1],
            context_injection=context_injection,
            session_id=str(current_session_id) if current_session_id else None,
        )
        session_tokens_in  += t_in
        session_tokens_out += t_out
        
        # ── auto tool ─────────────────────────────────────────────────────────
        if isinstance(result, dict) and result.get("status") == "needs_tool":
            result, tools, schema = _handle_auto_tool(
                result,
                user_input,
                tools,
                schema,
                args.model,
                agent_info,
                history,
                safe=args.safe,
            )
            # atualiza header e completer com as novas tools
            header(args.model, agent_info["name"], tools, safe=args.safe)
            completer = make_completer(tools)

        ts = datetime.now().strftime("%a %H:%M")
        history.append({"role": "agent", "content": result, "ts": ts})
        print_history_entry("agent", result, ts, t_in, t_out)
        print_turn_separator()

        # salva turno do agente em tempo real
        if current_session_id is not None:
            store.append_turn(current_session_id, "agent", result, ts)
        
        # limpa injection depois do primeiro turno (já foi usado)
        context_injection = None


if __name__ == "__main__":
    main()