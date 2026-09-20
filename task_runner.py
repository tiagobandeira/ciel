"""
task_runner.py — Executor de tasks com fila determinística.

Fluxo:
  1. Chama o modelo UMA vez para gerar um plano de ações (JSON).
  2. Executa em fila todas as ações determinísticas sem chamar o modelo.
  3. Quando encontra uma ação "model", chama run_agent com o contexto acumulado.
  4. Retorna AgentResult igual ao run_agent normal — transparente pra CLI.

Contagem de steps:
  - Tools determinísticas NÃO incrementam step — são sub-ações do step atual.
  - Apenas chamadas ao modelo (planejamento, ações "model", consolidador)
    incrementam step, espelhando o comportamento do agent_loop.
  - Display: "step N › ação K" para tools dentro do mesmo step N.

Uso em cli.py (substituir a chamada de run_agent na task):

    from task_runner import run_task

    agent_result = run_task(
        task, tools, schema, args.model, agent_info,
        history=history[:-1],
        session_id=str(current_session_id) if current_session_id else None,
        max_steps=MAX_STEPS_TASK,
        mcp_manager=mcp_manager,
        **_make_run_callbacks(session_flags),
    )

Flag de comparação A/B — para testar com e sem o task_runner:

    python cli.py --task tasks/noticias.md              # usa task_runner (novo)
    python cli.py --task tasks/noticias.md --no-queue   # usa run_agent direto (antigo)
"""

from __future__ import annotations

import json
import re
import inspect
from typing import Callable

import requests

from agent_loop import (
    AgentResult,
    run_agent,
    _call_model,
    _build_system_prompt,
    _parse_response,
    OLLAMA_URL,
    MAX_STEPS_TASK,
)

# ── limites de conteúdo ─────────────────────────────────────────────────────
# Aumentar QUEUE_MAX_RESULT_CHARS se tools como read_url estiverem sendo cortadas.
QUEUE_MAX_RESULT_CHARS  = 20000  # máximo por resultado no checkpoint (contexto do modelo)
QUEUE_MAX_DISPLAY_CHARS = 50    # truncamento só para exibição no terminal

# ── tipos dos callbacks (mesmos do agent_loop) ────────────────────────────────

OnStep       = Callable[[int, str, str, str], None]
OnModelStart = Callable[[int], None]
OnModelEnd   = Callable[[int], None]
OnDone       = Callable[[str, int, int, int], None]
OnLimit      = Callable[[int, int, int], None]
OnError      = Callable[[str, str], None]


def _call(cb, *args):
    if cb is not None:
        cb(*args)


def _truncate(text: str, limit: int = QUEUE_MAX_DISPLAY_CHARS) -> str:
    """Trunca texto para exibição no terminal, adicionando '...' se cortado."""
    return text[:limit] + "..." if len(text) > limit else text


def _extract_text(raw: str) -> str:
    """
    Extrai texto limpo de uma resposta do modelo que pode ser:
    - Texto livre (retorna direto)
    - JSON com campo "message" (ex: {"done": true, "message": "..."})
    Remove fences de markdown (```json ... ```) se presentes.
    """
    if not raw:
        return ""
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
        text = text.strip()
    try:
        data = json.loads(text)
        if isinstance(data, dict) and "message" in data:
            return str(data["message"]).strip()
    except (json.JSONDecodeError, ValueError):
        pass
    return text


# ── prompt de planejamento ────────────────────────────────────────────────────

_PLAN_SYSTEM = (
    "Você é um planejador de execução de tasks. "
    "Responda APENAS com JSON puro, sem markdown, sem texto adicional."
)

_PLAN_TEMPLATE = """\
Analise a task abaixo e produza um plano de execução em JSON.

Task: {nome}
Objetivo: {objetivo}
Ações definidas:
{acoes}

Resultado esperado: {resultado}

Regras do plano:

1. Cada ação vira um objeto no array "actions" com os campos:
   - "id": identificador único (ex: "a1", "a2", ...)
   - "type": "tool" ou "model"
   - "tool": nome da tool (apenas quando type = "tool")
   - "args": parâmetros da tool quando conhecidos, {{}} se não souber
   - "descricao": o que esta ação faz

2. Use type "tool" SOMENTE quando:
   - A ação chama a MESMA tool que as ações adjacentes consecutivas.
   - Os args são conhecidos antecipadamente e não dependem de raciocínio.
   - Ex: três chamadas a "calculator" → três objetos type "tool" consecutivos.

3. Use type "model" quando:
   - A ação usa uma tool DIFERENTE da anterior ou da próxima.
   - Uma única tool isolada (não faz parte de um grupo repetido da mesma tool).
   - A ação exige interpretação, análise ou raciocínio sobre resultados anteriores.
   - Os args dependem de um resultado ainda não disponível no plano.
   - Ex: "web_search" seguida de "read_url" → ambas type "model".

4. Preserve a ordem lógica das ações.
5. Se uma ação sugere [tool: nome], use esse nome no campo "tool".

Responda SOMENTE com este JSON, sem markdown, sem texto adicional:
{{
  "actions": [ ... ]
}}
"""

def _build_plan_prompt(task: dict) -> str:
    acoes_fmt = "\n".join(f"  {i+1}. {a}" for i, a in enumerate(task["acoes"]))
    return _PLAN_TEMPLATE.format(
        nome=task.get("nome", ""),
        objetivo=task.get("objetivo", ""),
        acoes=acoes_fmt,
        resultado=task.get("resultado", ""),
    )


def _request_plan(task: dict, model: str, ollama_url: str) -> list[dict] | None:
    """
    Chama o modelo uma vez para obter o plano de execução.
    Retorna lista de actions ou None se falhar.
    """
    messages = [
        {"role": "system", "content": _PLAN_SYSTEM},
        {"role": "user",   "content": _build_plan_prompt(task)},
    ]
    try:
        raw, _, _ = _call_model(messages, model, ollama_url)
        parsed = _parse_response(raw)
        actions = parsed.get("actions")
        if isinstance(actions, list) and actions:
            return actions
    except Exception:
        pass
    return None


# ── validação de grupos de tools ─────────────────────────────────────────────

def _validate_tool_groups(
    actions: list[dict],
    allowed_tools: set[str] | None = None,
) -> list[dict]:
    """
    Guard de runtime: rebaixa para "model" blocos de tools que não devem
    ser agrupados.

    Regras:
    - allowed_tools=None  → qualquer tool pode ser agrupada (grupo: tudo)
    - allowed_tools={...} → só as tools listadas podem ser agrupadas
    - Bloco contíguo só é válido se todas as ações usam a MESMA tool
      E essa tool está em allowed_tools (ou allowed_tools é None).
    - Caso contrário, o bloco inteiro vira "model".
    """
    result: list[dict] = []
    i = 0
    while i < len(actions):
        action = actions[i]
        if action.get("type") != "tool":
            result.append(action)
            i += 1
            continue

        # coleta o bloco contíguo de tools
        block_start = i
        while i < len(actions) and actions[i].get("type") == "tool":
            i += 1
        block = actions[block_start:i]

        # verifica homogeneidade e permissão
        tools_no_bloco = {a.get("tool", "") for a in block}
        tool_unica = next(iter(tools_no_bloco)) if len(tools_no_bloco) == 1 else None
        permitida  = (
            tool_unica is not None
            and (allowed_tools is None or tool_unica in allowed_tools)
        )

        if permitida:
            # bloco homogêneo e permitido — mantém como fila
            result.extend(block)
        else:
            # bloco misto ou tool não permitida — rebaixa para "model"
            tools_str = ", ".join(sorted(tools_no_bloco))
            rebaixado = {
                "id":        block[0]["id"],
                "type":      "model",
                "descricao": (
                    f"Executar sequência ({tools_str}) — {len(block)} ações"
                ),
                "_rebaixado_de": [a["id"] for a in block],
            }
            result.append(rebaixado)

    return result


# ── checkpoint ────────────────────────────────────────────────────────────────

class TaskCheckpoint:
    """
    Estado mínimo da execução — permite saber o que já rodou
    e acumular resultados para passar ao modelo quando necessário.
    """

    def __init__(self, actions: list[dict]):
        self.actions   = actions
        self.completed : list[str] = []
        self.failed    : list[str] = []
        self.skipped   : list[str] = []
        self.results   : dict[str, str] = {}   # id → resultado da tool

    def mark_done(self, action_id: str, result: str):
        self.completed.append(action_id)
        self.results[action_id] = result

    def mark_failed(self, action_id: str, error: str):
        self.failed.append(action_id)
        self.results[action_id] = f"[ERRO] {error}"

    def mark_skipped(self, action_id: str):
        self.skipped.append(action_id)

    def summary(self) -> str:
        """
        Texto resumido para injetar no contexto do modelo.
        Usa a descrição da ação como rótulo (sem IDs internos) e omite erros.
        """
        lines = ["Informações coletadas:"]
        for action in self.actions:
            aid = action["id"]
            result = self.results.get(aid, "")
            if result and not result.startswith("[ERRO]"):
                desc = action.get("descricao", "")
                lines.append(f"  - {desc}: {result[:QUEUE_MAX_RESULT_CHARS]}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "completed": self.completed,
            "failed":    self.failed,
            "skipped":   self.skipped,
            "results":   {k: v[:10000] for k, v in self.results.items()},
        }


# ── execução de tool determinística ──────────────────────────────────────────

def _execute_tool(
    action: dict,
    tools: dict,
    agent_info: dict,
    session_id: str | None,
    on_confirm_tool: Callable | None,
    on_confirm_path: Callable | None,
    on_ask_user: Callable | None,
) -> tuple[bool, str]:
    """
    Executa uma tool determinística diretamente, sem chamar o modelo.
    Retorna (sucesso: bool, resultado: str).
    """
    tool_name = action.get("tool", "")
    args      = action.get("args", {}) or {}

    if tool_name not in tools:
        return False, f"Tool '{tool_name}' não encontrada. Disponíveis: {list(tools.keys())}"

    # workspace guard
    if on_confirm_path is not None:
        try:
            from tool_dispatch import get_path_checks
            from workspace import get_workspace
            for arg_name, need_write in get_path_checks(tool_name, tools):
                raw_path = args.get(arg_name)
                if not raw_path:
                    continue
                _, _err = get_workspace().check(raw_path, need_write)
                if _err:
                    allowed = on_confirm_path(raw_path, need_write)
                    if not allowed:
                        return False, f"Acesso a '{raw_path}' negado."
        except Exception:
            pass

    # confirmação de tools sensíveis
    try:
        from tool_dispatch import needs_confirmation
        if needs_confirmation(tool_name, False):
            if on_confirm_tool is None:
                return False, f"Tool '{tool_name}' bloqueada: requer confirmação."
            tool_code = args.get("tool_code", "")
            if not on_confirm_tool(tool_name, tool_code):
                return False, f"Execução de '{tool_name}' recusada."
    except Exception:
        pass

    # injeções especiais (mesmo comportamento do agent_loop)
    if tool_name == "run_script":
        try:
            from workspace import get_workspace as _gws
            args.setdefault("cwd", str(_gws().default_root))
        except Exception:
            pass

    if tool_name in ("list_sources", "search_knowledge"):
        args.setdefault("agent_id", agent_info.get("id", "general"))
        args.setdefault("session_id", str(session_id) if session_id else "")

    if tools.get(tool_name, {}).get("interactive") and on_ask_user is not None:
        args.setdefault("perguntar", on_ask_user)

    try:
        result = tools[tool_name]["fn"](**args)
        return True, str(result)
    except TypeError as e:
        sig = inspect.signature(tools[tool_name]["fn"])
        return False, (
            f"Args inválidos para '{tool_name}': {e}. "
            f"Assinatura: {tool_name}{sig}. Recebidos: {list(args.keys())}"
        )
    except Exception as e:
        return False, f"Erro ao executar '{tool_name}': {e}"


# ── run_task ──────────────────────────────────────────────────────────────────

def run_task(
    task: dict,
    tools: dict,
    schema: list,
    model: str,
    agent_info: dict,
    *,
    history: list[dict] | None = None,
    session_id: str | None = None,
    max_steps: int = MAX_STEPS_TASK,
    max_steps_per_model: int = 3,   # teto de steps por ação "model" individual
    ollama_url: str = OLLAMA_URL,
    mcp_manager=None,
    # callbacks — mesma assinatura do run_agent
    on_step: OnStep | None = None,
    on_model_start: OnModelStart | None = None,
    on_model_end: OnModelEnd | None = None,
    on_done: OnDone | None = None,
    on_limit: OnLimit | None = None,
    on_error: OnError | None = None,
    on_confirm_tool: Callable | None = None,
    on_confirm_path: Callable | None = None,
    on_ask_user: Callable | None = None,
    on_queue_action: Callable | None = None,  # callback para sub-ações de fila
) -> AgentResult:
    """
    Executa uma task com fila determinística.

    Contagem de steps espelha o agent_loop: só incrementa quando o modelo
    é chamado. Tools determinísticas são sub-ações do step corrente e não
    consomem step. Display: "step N › ação K" para tools dentro do step N.

    Retorna AgentResult — compatível com o retorno de run_agent.
    """
    total_in  = 0
    total_out = 0
    step      = 0   # incrementa APENAS em chamadas ao modelo
    action_idx = 0  # contador de sub-ações dentro do step atual (display)

    # ── step 1: planejamento ──────────────────────────────────────────────────
    step += 1
    action_idx = 0
    _call(on_model_start, step)
    _call(on_step, step, "planejando", task.get("nome", "task"), "model")

    # ── campo 'grupo' da task ─────────────────────────────────────────────
    # grupo: ''      → sem campo → comportamento antigo (run_agent direto)
    # grupo: 'tudo'  → planner livre pra agrupar qualquer tool repetida
    # grupo: 'a, b'  → planner só agrupa as tools listadas; outras → model
    group_field = task.get("grupo", "").strip().lower()

    if not group_field:
        # sem campo grupo → comportamento antigo, sem planner
        _call(on_model_end, step)
        _call(on_step, step, "plano", "sem grupo definido — usando run_agent direto", "done")
        from cli import build_task_prompt
        return run_agent(
            build_task_prompt(task), tools, schema, model, agent_info,
            history=history,
            session_id=session_id,
            max_steps=max_steps,
            ollama_url=ollama_url,
            mcp_manager=mcp_manager,
            on_step=on_step,
            on_model_start=on_model_start,
            on_model_end=on_model_end,
            on_done=on_done,
            on_limit=on_limit,
            on_error=on_error,
            on_confirm_tool=on_confirm_tool,
            on_confirm_path=on_confirm_path,
            on_ask_user=on_ask_user,
        )

    # allowed_tools: None = qualquer tool; set = só as listadas
    allowed_tools: set[str] | None = (
        None if group_field == "tudo"
        else {t.strip() for t in group_field.split(",") if t.strip()}
    )

    try:
        actions = _request_plan(task, model, ollama_url)
    except requests.RequestException as e:
        _call(on_error, "connection", str(e))
        return AgentResult("error", f"Erro de conexão ao planejar: {e}", steps=step)
    finally:
        _call(on_model_end, step)

    if not actions:
        # fallback: sem plano, delega pro run_agent normal
        _call(on_step, step, "plano falhou", "usando run_agent direto", "error")
        from cli import build_task_prompt   # evita import circular no topo
        return run_agent(
            build_task_prompt(task), tools, schema, model, agent_info,
            history=history,
            session_id=session_id,
            max_steps=max_steps,
            ollama_url=ollama_url,
            mcp_manager=mcp_manager,
            on_step=on_step,
            on_model_start=on_model_start,
            on_model_end=on_model_end,
            on_done=on_done,
            on_limit=on_limit,
            on_error=on_error,
            on_confirm_tool=on_confirm_tool,
            on_confirm_path=on_confirm_path,
            on_ask_user=on_ask_user,
        )

    actions = _validate_tool_groups(actions, allowed_tools)

    # Se o plano não tiver nenhuma ação "tool", o task_runner não agrega
    # valor — seria só overhead de planejamento + consolidador em cima do
    # run_agent normal. Descarta o plano e delega direto pro run_agent.
    has_tool_actions = any(a.get("type") == "tool" for a in actions)
    if not has_tool_actions:
        _call(on_step, step, "plano", "sem fila — usando run_agent direto", "done")
        from cli import build_task_prompt
        return run_agent(
            build_task_prompt(task), tools, schema, model, agent_info,
            history=history,
            session_id=session_id,
            max_steps=max_steps,
            ollama_url=ollama_url,
            mcp_manager=mcp_manager,
            on_step=on_step,
            on_model_start=on_model_start,
            on_model_end=on_model_end,
            on_done=on_done,
            on_limit=on_limit,
            on_error=on_error,
            on_confirm_tool=on_confirm_tool,
            on_confirm_path=on_confirm_path,
            on_ask_user=on_ask_user,
        )

    _call(on_step, step, "plano", f"{len(actions)} ações planejadas", "done")

    checkpoint = TaskCheckpoint(actions)

    # ── execução da fila ──────────────────────────────────────────────────────
    # Regra de contagem:
    #   - type "tool"  → NÃO incrementa step; é sub-ação do step atual.
    #                    Display: "step {step} › ação {action_idx}"
    #   - type "model" → incrementa step (chama o modelo).
    # O consolidador final também consome 1 step — verificamos o limite antes.

    total_tool_actions = sum(1 for a in actions if a.get("type") == "tool")

    for action in actions:
        aid   = action.get("id", "?")
        atype = action.get("type", "tool")
        desc  = action.get("descricao", aid)

        # ── ação determinística (tool) ────────────────────────────────────────
        if atype == "tool":
            action_idx += 1
            tool_name = action.get("tool", "")
            label = f"ação {action_idx} › {tool_name}"
            if on_queue_action is not None:
                _call(on_queue_action, action_idx, total_tool_actions, label, desc, "tool")
            else:
                _call(on_step, step, label, desc, "tool")

            ok, result = _execute_tool(
                action, tools, agent_info, session_id,
                on_confirm_tool, on_confirm_path, on_ask_user,
            )

            if ok:
                if on_queue_action is not None:
                    _call(on_queue_action, action_idx, total_tool_actions, "resultado", _truncate(result), "result")
                else:
                    _call(on_step, step, "resultado", result[:100], "done")
                checkpoint.mark_done(aid, result)
            else:
                if on_queue_action is not None:
                    _call(on_queue_action, action_idx, total_tool_actions, "erro", _truncate(result), "error")
                else:
                    _call(on_step, step, "erro", result[:100], "error")
                checkpoint.mark_failed(aid, result)
                # falha não bloqueante — continua a fila

        # ── ação adaptativa (model) ───────────────────────────────────────────
        elif atype == "model":
            # verifica limite ANTES de consumir o step
            # (reserva +1 para o consolidador final)
            if step + 1 >= max_steps:
                _call(on_limit, max_steps, total_in, total_out)
                return AgentResult(
                    "limit",
                    f"⚠ Limite de steps atingido. Completadas: {checkpoint.completed}",
                    tokens_in=total_in,
                    tokens_out=total_out,
                    steps=step,
                )

            step += 1
            action_idx = 0
            # NÃO chama on_model_start/end aqui: o run_agent aninhado já
            # gerencia o ciclo de vida do spinner internamente.
            _call(on_step, step, "modelo", desc, "model")

            # Inclui o que já foi coletado para evitar que o sub-agente
            # refaça buscas ou ações que as etapas anteriores já executaram.
            context_so_far = (
                f"Task: {task.get('nome', '')}\n"
                f"Objetivo: {task.get('objetivo', '')}\n\n"
                f"{checkpoint.summary()}\n\n"
                f"Tarefa desta etapa: {desc}\n\n"
                f"IMPORTANTE: as informações acima já foram coletadas. "
                f"Não repita buscas ou ações já realizadas. "
                f"Execute apenas o que esta etapa pede."
            )

            # Teto por ação: cada sub-agente usa no máximo max_steps_per_model
            # steps, independente do orçamento total restante.
            steps_restantes = max(1, max_steps - step - 1)  # -1 reserva consolidador
            sub_max = min(max_steps_per_model, steps_restantes)

            sub_result = run_agent(
                context_so_far, tools, schema, model, agent_info,
                history=history,
                session_id=session_id,
                max_steps=sub_max,
                ollama_url=ollama_url,
                mcp_manager=mcp_manager,
                on_step=on_step,
                on_model_start=on_model_start,
                on_model_end=on_model_end,
                on_confirm_tool=on_confirm_tool,
                on_confirm_path=on_confirm_path,
                on_ask_user=on_ask_user,
            )

            total_in  += sub_result.tokens_in
            total_out += sub_result.tokens_out
            # NÃO soma sub_result.steps: o contador step reflete apenas
            # chamadas ao modelo do task_runner, não steps internos do run_agent.

            if sub_result.status == "error":
                _call(on_error, "connection", sub_result.message)
                return AgentResult(
                    "error", sub_result.message,
                    tokens_in=total_in, tokens_out=total_out, steps=step,
                )

            result = sub_result.message
            checkpoint.mark_done(aid, result)

        else:
            # tipo desconhecido — pula sem consumir step
            _call(on_step, step, "skip", f"tipo desconhecido: {atype}", "error")
            checkpoint.mark_skipped(aid)

    # ── step final: resposta consolidada ─────────────────────────────────────
    if step >= max_steps:
        # sem step disponível para consolidar — entrega o melhor resultado
        # que o modelo produziu nas ações "model" anteriores
        msg = _build_final_message(task, checkpoint)
        _call(on_done, msg, step, total_in, total_out)
        return AgentResult("done", msg, tokens_in=total_in, tokens_out=total_out, steps=step)

    step += 1
    action_idx = 0
    _call(on_model_start, step)
    _call(on_step, step, "resposta final", "consolidando resultado", "model")

    final_prompt = (
        f"{checkpoint.summary()}\n\n"
        f"Com base nessas informações, escreva a resposta final para o usuário.\n"
        f"Objetivo: {task.get('resultado', '')}\n\n"
        f"Responda em texto corrido, bem formatado e organizado. "
        f"Não mencione IDs de ações, erros internos ou detalhes técnicos da execução. "
        f"Não use JSON."
    )

    try:
        system_prompt = _build_system_prompt(agent_info, schema, session_id=session_id)
        context: list[dict] = []
        for entry in (history or []):
            role = "user" if entry["role"] == "user" else "assistant"
            context.append({"role": role, "content": entry["content"]})

        messages = [
            {"role": "system",    "content": system_prompt},
            *context,
            {"role": "user",      "content": final_prompt},
        ]
        raw, t_in, t_out = _call_model(messages, model, ollama_url)
        total_in  += t_in
        total_out += t_out
    except requests.RequestException as e:
        _call(on_error, "connection", str(e))
        msg = _build_final_message(task, checkpoint)
        return AgentResult("done", msg, tokens_in=total_in, tokens_out=total_out, steps=step)
    finally:
        _call(on_model_end, step)

    # _extract_text lida com texto puro, JSON {"message": ...} e fences markdown.
    msg = _extract_text(raw) or _build_final_message(task, checkpoint)

    _call(on_step, step, "done", msg[:100], "done")
    _call(on_done, msg, step, total_in, total_out)
    return AgentResult("done", msg, tokens_in=total_in, tokens_out=total_out, steps=step)


def _build_final_message(task: dict, checkpoint: TaskCheckpoint) -> str:
    """
    Fallback quando o modelo não responde no step final.
    Concatena resultados úteis sem expor IDs internos ou mensagens de erro.
    Prioriza o último resultado de ação "model" (mais elaborado).
    """
    # tenta usar o resultado da última ação "model" como resposta principal
    for action in reversed(checkpoint.actions):
        if action.get("type") == "model":
            aid = action["id"]
            result = checkpoint.results.get(aid, "")
            if result and not result.startswith("[ERRO]"):
                return result

    # fallback: concatena todos os resultados úteis
    lines = []
    for action in checkpoint.actions:
        aid = action["id"]
        result = checkpoint.results.get(aid, "")
        if result and not result.startswith("[ERRO]"):
            lines.append(result[:QUEUE_MAX_RESULT_CHARS])
    return "\n\n".join(lines) if lines else f"Task {task.get('nome', '')} concluída."