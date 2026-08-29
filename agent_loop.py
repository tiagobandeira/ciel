"""
agent_loop.py — Loop agêntico desacoplado de UI.

Contém run_agent() sem nenhum print ou dependência de Rich/prompt_toolkit.
Todo feedback de progresso é emitido via callbacks injetados pelo chamador
(CLI, TUI ou qualquer outra interface).

Callbacks disponíveis (todos opcionais):
    on_step(step, label, content, status)
        Chamado a cada step do loop.
        status: "model" | "tool" | "done" | "error" | "parse_error"

    on_model_start(step)
        Chamado imediatamente antes de chamar o modelo (útil pro spinner/thinking).

    on_model_end(step)
        Chamado logo após a resposta do modelo chegar.

    on_done(message, steps, tokens_in, tokens_out)
        Chamado quando o agente conclui com "done".

    on_limit(steps, tokens_in, tokens_out)
        Chamado quando os steps se esgotam sem conclusão.

    on_error(kind, message)
        Chamado em erros de conexão ou parse irrecuperável.
        kind: "connection" | "parse"

Uso mínimo (sem callbacks — loop silencioso):
    result = run_agent(user_input, tools, schema, model, agent_info)

Uso com callbacks (CLI):
    result = run_agent(..., on_step=meu_print_step, on_done=meu_print_done)
"""

from __future__ import annotations

import inspect
import json
import re
from pathlib import Path
from typing import Callable

import requests

# ── config padrão (pode ser sobrescrita pelo chamador) ────────────────────────

OLLAMA_URL    = "http://localhost:11434/api/chat"
MAX_STEPS     = 9
MAX_STEPS_TASK = 9

# ── tipos dos callbacks ───────────────────────────────────────────────────────

OnStep       = Callable[[int, str, str, str], None]   # step, label, content, status
OnModelStart = Callable[[int], None]                   # step
OnModelEnd   = Callable[[int], None]                   # step
OnDone       = Callable[[str, int, int, int], None]    # msg, steps, tok_in, tok_out
OnLimit      = Callable[[int, int, int], None]         # steps, tok_in, tok_out
OnError      = Callable[[str, str], None]              # kind, message


# ── helpers internos ──────────────────────────────────────────────────────────

def _call(cb, *args):
    """Chama um callback se não for None."""
    if cb is not None:
        cb(*args)


def _parse_response(text: str) -> dict:
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


def _call_model(messages: list, model: str, ollama_url: str) -> tuple[str, int, int]:
    payload = {"model": model, "messages": messages, "stream": False}
    resp = requests.post(ollama_url, json=payload, timeout=120)
    resp.raise_for_status()
    data = resp.json()
    return (
        data["message"]["content"],
        data.get("prompt_eval_count", 0),
        data.get("eval_count", 0),
    )


def _build_system_prompt(
    agent_info: dict,
    schema: list,
    web_base_url: str | None = None,
    session_id: str | None = None,
) -> str:
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
            f" exato, por exemplo: 'arquivo salvo em: data/user/relatorio.pdf'."
            f"\nO frontend vai converter esse caminho em link de download automaticamente."
        )
    return "".join(parts)


def _ask_model_for_tool_proposal(
    messages: list, model: str, ollama_url: str
) -> dict | None:
    """Verifica se uma nova tool resolveria a tarefa (chamada extra ao modelo)."""
    history_only = [m for m in messages if m["role"] != "system"]
    probe = [
        {
            "role": "system",
            "content": (
                "Você é um analista de capacidades de agentes. "
                "Responda APENAS com JSON puro, sem markdown, sem texto adicional."
            ),
        },
        *history_only,
        {
            "role": "user",
            "content": (
                "Você não conseguiu completar a tarefa com as tools disponíveis.\n"
                "Analise o histórico e responda APENAS em JSON puro:\n\n"
                "Se uma nova tool resolveria o problema:\n"
                '{"criar_tool": true, "nome": "nome_em_snake_case", '
                '"descricao": "o que a tool faz em uma linha", '
                '"parametros": [{"nome": "param", "tipo": "str", "descricao": "o que é"}]}\n\n'
                "Se a tarefa é impossível ou não depende de tool nova:\n"
                '{"criar_tool": false}'
            ),
        },
    ]
    try:
        raw, _, _ = _call_model(probe, model, ollama_url)
        parsed = _parse_response(raw)
        if parsed.get("criar_tool") is True and parsed.get("nome") and parsed.get("descricao"):
            return parsed
    except Exception:
        pass
    return None


# ── resultado do run_agent ────────────────────────────────────────────────────

class AgentResult:
    """
    Encapsula o resultado do run_agent de forma explícita.

    Atributos:
        status  : "done" | "needs_tool" | "limit" | "error"
        message : resposta final ou mensagem de erro
        proposal: dict com proposta de nova tool (só quando status="needs_tool")
        tokens_in / tokens_out: totais da chamada
        steps   : número de steps executados
    """

    def __init__(
        self,
        status: str,
        message: str = "",
        proposal: dict | None = None,
        tokens_in: int = 0,
        tokens_out: int = 0,
        steps: int = 0,
    ):
        self.status   = status
        self.message  = message
        self.proposal = proposal
        self.tokens_in  = tokens_in
        self.tokens_out = tokens_out
        self.steps    = steps

    @property
    def ok(self) -> bool:
        return self.status == "done"

    def __repr__(self) -> str:
        return (
            f"AgentResult(status={self.status!r}, steps={self.steps}, "
            f"tok={self.tokens_in}+{self.tokens_out})"
        )


# ── run_agent ─────────────────────────────────────────────────────────────────

def run_agent(
    user_input: str,
    tools: dict,
    schema: list,
    model: str,
    agent_info: dict,
    *,
    history: list[dict] | None = None,
    image_b64: str | None = None,
    web_base_url: str | None = None,
    context_injection: str | None = None,
    session_id: str | None = None,
    max_steps: int = MAX_STEPS,
    ollama_url: str = OLLAMA_URL,
    # callbacks
    on_step: OnStep | None = None,
    on_model_start: OnModelStart | None = None,
    on_model_end: OnModelEnd | None = None,
    on_done: OnDone | None = None,
    on_limit: OnLimit | None = None,
    on_error: OnError | None = None,
) -> AgentResult:
    """
    Executa o loop agêntico e retorna um AgentResult.

    Não imprime nada — todo feedback vai pelos callbacks.
    Compatível com execução em thread (Textual @work).
    """
    total_in  = 0
    total_out = 0

    system_prompt = _build_system_prompt(
        agent_info, schema,
        web_base_url=web_base_url,
        session_id=session_id,
    )
    if context_injection:
        system_prompt = f"{system_prompt}\n\n{context_injection}"

    # reconstrói contexto dos turnos anteriores
    context: list[dict] = []
    for entry in (history or []):
        role = "user" if entry["role"] == "user" else "assistant"
        context.append({"role": role, "content": entry["content"]})

    # monta mensagem inicial (com imagem se houver)
    if image_b64:
        first_msg = {
            "role": "user",
            "content": user_input or "Descreva e analise esta imagem.",
            "images": [image_b64],
        }
    else:
        first_msg = {"role": "user", "content": user_input}

    messages = [
        {"role": "system", "content": system_prompt},
        *context,
        first_msg,
    ]

    for step in range(1, max_steps + 1):
        _call(on_model_start, step)
        _call(on_step, step, "modelo", "aguardando…", "model")

        try:
            raw, t_in, t_out = _call_model(messages, model, ollama_url)
            total_in  += t_in
            total_out += t_out
        except requests.RequestException as e:
            msg = f"Erro de conexão com Ollama: {e}"
            _call(on_error, "connection", str(e))
            return AgentResult("error", msg, tokens_in=total_in, tokens_out=total_out, steps=step)
        finally:
            _call(on_model_end, step)

        parsed = _parse_response(raw)

        # ── done ──────────────────────────────────────────────────────────────
        if parsed.get("done"):
            msg = parsed.get("message", "Concluído.")
            _call(on_step, step, "done", msg, "done")
            _call(on_done, msg, step, total_in, total_out)
            return AgentResult("done", msg, tokens_in=total_in, tokens_out=total_out, steps=step)

        # ── parse error ───────────────────────────────────────────────────────
        if "error" in parsed:
            _call(on_step, step, "parse error", parsed["error"], "parse_error")
            messages.append({"role": "assistant", "content": raw})
            messages.append({
                "role": "user",
                "content": "Resposta inválida. Retorne APENAS JSON no formato especificado.",
            })
            continue

        # ── tool call ─────────────────────────────────────────────────────────
        tool_name = parsed.get("tool", "")
        args      = parsed.get("args", {})

        _call(on_step, step, f"tool › {tool_name}", json.dumps(args, ensure_ascii=False)[:80], "tool")

        if tool_name not in tools:
            feedback = f"Tool '{tool_name}' não existe. Disponíveis: {list(tools.keys())}"
            _call(on_step, step, "erro", feedback, "error")
        else:
            try:
                if tool_name in ("list_sources", "search_knowledge"):
                    args.setdefault("agent_id", agent_info.get("id", "general"))
                    args.setdefault("session_id", str(session_id) if session_id else "")
                if tool_name == "secondary_model":
                    args.setdefault("session_id", str(session_id) if session_id else "_nosession")

                feedback = tools[tool_name]["fn"](**args)
                _call(on_step, step, "resultado", str(feedback)[:100], "done")

                # reload automático após criação de tool
                if tool_name in ("create_tool", "create_temp_tool") and "Erro" not in str(feedback):
                    from tools_registry import load_tools, tools_schema
                    from agent_loader import filter_tools
                    all_updated = load_tools()
                    tools.clear()
                    tools.update(filter_tools(all_updated, agent_info.get("allowed_tools")))
                    schema.clear()
                    schema.extend(tools_schema(tools))
                    messages[0]["content"] = _build_system_prompt(agent_info, schema)
                    _call(on_step, step, "registry", f"{len(tools)} tools carregadas", "done")

            except TypeError as e:
                sig = inspect.signature(tools[tool_name]["fn"])
                feedback = (
                    f"Args inválidos para '{tool_name}': {e}. "
                    f"Assinatura correta: {tool_name}{sig}. "
                    f"Args recebidos: {list(args.keys())}"
                )
                _call(on_step, step, "erro", feedback, "error")
            except Exception as e:
                feedback = f"Erro ao executar tool: {e}"
                _call(on_step, step, "erro", feedback, "error")

        messages.append({"role": "assistant", "content": raw})
        messages.append({"role": "user", "content": f"Resultado da tool: {feedback}"})

    # ── steps esgotados ───────────────────────────────────────────────────────
    proposal = _ask_model_for_tool_proposal(messages, model, ollama_url)

    if proposal:
        _call(on_limit, max_steps, total_in, total_out)
        return AgentResult(
            "needs_tool",
            proposal=proposal,
            tokens_in=total_in,
            tokens_out=total_out,
            steps=max_steps,
        )

    _call(on_limit, max_steps, total_in, total_out)
    return AgentResult(
        "limit",
        "⚠ Limite de steps atingido sem conclusão.",
        tokens_in=total_in,
        tokens_out=total_out,
        steps=max_steps,
    )
