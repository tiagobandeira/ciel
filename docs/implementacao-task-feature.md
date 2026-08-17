# Implementação: feature `/task`

> Referência técnica baseada no código atual do `cli.py`.  
> Três pontos de alteração — nenhum toca o loop principal.

---

## Visão geral

```
/task <arquivo.md>   → executa task exata
/task <prompt>       → busca task por nome e executa (ou lista candidatas)
```

O `/task` é interceptado **antes** do `run_agent`, igual aos outros comandos
(`/tools`, `/source`, `/history`, etc.). O loop `run_agent` não muda nada.

---

## 1. Pasta de tasks

Criar `tasks/` na raiz do projeto (mesma convenção de `agents/`, `tools/`).

```
tasks/
├── noticias-do-dia.md
└── noticias-auto.md
```

---

## 2. Parser do arquivo `.md`

Função auxiliar nova — fora do loop, lida com leitura e validação:

```python
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
```

---

## 3. MAX_STEPS para tasks

No topo do arquivo, junto com as constantes:

```python
MAX_STEPS       = 6
MAX_STEPS_TASK  = 9   # +3 para tasks (plano já vem pronto)
```

O `run_agent` já recebe `MAX_STEPS` implicitamente via closure — basta torná-lo
parâmetro opcional:

```python
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
    max_steps: int = MAX_STEPS,          # <-- adicionar este parâmetro
) -> str | dict:
    ...
    for step in range(1, max_steps + 1):  # <-- usar max_steps em vez de MAX_STEPS
        ...
```

---

## 4. Handler do comando `/task`

Inserir no loop principal, junto com os outros handlers de comando
(logo após o bloco `/promover`, antes do trecho que salva o turno do user):

```python
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

    result = run_agent(
        task_prompt, tools, schema, args.model, agent_info,
        history=history[:-1],
        session_id=str(current_session_id) if current_session_id else None,
        max_steps=MAX_STEPS_TASK,          # <-- usa o limite expandido
    )

    if isinstance(result, dict) and result.get("status") == "needs_tool":
        result, tools, schema = _handle_auto_tool(
            result, task_prompt, tools, schema,
            args.model, agent_info, history, safe=args.safe,
        )
        header(args.model, agent_info["name"], tools, safe=args.safe)
        completer = make_completer(tools)

    ts = datetime.now().strftime("%a %H:%M")
    history.append({"role": "agent", "content": result, "ts": ts})
    print_history_entry("agent", result, ts)
    print_turn_separator()

    if current_session_id is not None:
        store.append_turn(current_session_id, "agent", result, ts)

    continue
```

---

## 5. Autocomplete

Adicionar `/task` e `/task <nome>` ao `CMDS`:

```python
CMDS = [
    ...
    "/task",
]
```

E na função `make_completer`, adicionar os nomes das tasks:

```python
def make_completer(tools_dict: dict) -> WordCompleter:
    tool_names   = list(tools_dict.keys())
    agent_names  = [f"/agente {a}" for a in list_agents()]
    task_names   = [f"/task {p.stem}" for p in Path("tasks").glob("*.md")] if Path("tasks").exists() else []
    return WordCompleter(CMDS + tool_names + agent_names + task_names, sentence=True)
```

---

## 6. Ajuda

Adicionar linha no `/ajuda`:

```python
"  [yellow]/task[/yellow]                    lista tasks disponíveis\n"
"  [yellow]/task [white]<nome ou prompt>[/white][/yellow]  executa task pelo nome ou busca\n"
"  [yellow]/task [white]<arquivo.md>[/white][/yellow]      executa task por caminho direto\n"
```

---

## Resumo das mudanças

| O que | Onde | Impacto |
|---|---|---|
| `load_task`, `find_tasks`, `build_task_prompt` | novas funções no `cli.py` | nenhum no loop |
| `MAX_STEPS_TASK = 9` | constantes no topo | nenhum no comportamento atual |
| parâmetro `max_steps` no `run_agent` | assinatura da função | retrocompatível (default = `MAX_STEPS`) |
| handler `/task` | loop principal, junto com outros handlers | isolado por `continue` |
| autocomplete e `/ajuda` | `make_completer` e bloco de ajuda | cosmético |

O loop central (`run_agent`) e o auto tool (`_handle_auto_tool`) não mudam em
nada. A feature é aditiva.

---

## Status

> Não implementado. Referência para quando o caso de uso aparecer na prática.
