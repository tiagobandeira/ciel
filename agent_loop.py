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
import time
from pathlib import Path
from typing import Callable

import requests

from llm.client import ChatResult, LLMError, OllamaClient
from llm.native_tools import to_openai_tools
from llm.roles import PERFIL_NUVEM, normalize_perfil
from trust.input_verifier import InputVerifier

# ── config padrão (pode ser sobrescrita pelo chamador) ────────────────────────

OLLAMA_URL    = "http://localhost:11434/api/chat"
MAX_STEPS     = 9
MAX_STEPS_TASK = 9
MAX_STEPS_TASK_NUVEM = 12  # escrita longa no perfil nuvem

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


def _parse_dsml_invoke(name: str, body: str) -> dict | None:
    # remove o fechamento do invoke, se existir
    body = re.split(
        r"<[^>]*DSML[^>]*/\s*invoke\s*>", body, maxsplit=1, flags=re.IGNORECASE
    )[0]

    params = re.findall(
        r"<[^>]*DSML[^>]*parameter\b[^>]*\bname\s*=\s*[\"']([^\"']+)[\"'][^>]*>"
        r"(.*?)</[^>]*DSML[^>]*parameter\s*>",
        body,
        re.DOTALL | re.IGNORECASE,
    )

    args: dict = {}
    if params:
        for pname, raw in params:
            raw = raw.strip()
            if pname.lower() in ("args", "arguments"):
                try:
                    value = json.loads(raw)
                except (ValueError, TypeError):
                    return None
                if not isinstance(value, dict):
                    return None
                args.update(value)
                continue
            try:
                args[pname] = json.loads(raw)
            except (ValueError, TypeError):
                args[pname] = raw
    else:
        try:
            value = json.loads(body.strip())
        except (ValueError, TypeError):
            return None
        if not isinstance(value, dict):
            return None
        args = value

    return {"tool": name, "args": args}


def _parse_dsml_response(text: str) -> dict | None:
    """
    Adaptador para modelos DeepSeek que emitem tool calls no formato DSML
    (``<｜｜DSML｜｜ invoke ...>``) em vez do JSON do Ciel.

    Suporta mais de um invoke: devolve ``{"actions": [...]}`` para o loop
    executar em lote. Se não houver DSML reconhecível, devolve None.
    """
    if "dsml" not in text.lower():
        return None

    invokes = re.findall(
        r"<[^>]*DSML[^>]*invoke\b[^>]*\bname\s*=\s*[\"']([^\"']+)[\"'][^>]*>"
        r"(.*?)(?=<[^>]*DSML[^>]*invoke\b|\Z)",
        text,
        re.DOTALL | re.IGNORECASE,
    )
    if not invokes:
        return None

    actions = []
    for name, body in invokes:
        action = _parse_dsml_invoke(name, body)
        if action is not None:
            actions.append(action)
    if not actions:
        return None
    if len(actions) == 1:
        return actions[0]
    return {"actions": actions}


def _first_json_object(text: str) -> dict | None:
    """Extrai o primeiro objeto JSON completo, mesmo com prosa/múltiplos JSONs."""
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


def _parse_response(text: str) -> dict:
    if "dsml" in text.lower():
        dsml = _parse_dsml_response(text)
        if dsml is not None:
            return dsml
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass
    first = _first_json_object(text)
    if first is not None:
        return first
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


# ── lote de leituras e compactação (build) ─────────────────────────────────────

BATCH_SAFE_TOOLS = frozenset({
    "read_file", "list_directory", "search_files",
    "list_sources", "search_knowledge", "read_source",
    "list_skills", "get_local_datetime", "calculator",
})
MAX_BATCH_ACTIONS = 4
MAX_BATCH_RESULT_CHARS = 12_000

HISTORY_MAX_CHARS = 30_000
HISTORY_KEEP_LAST = 6


def _extract_actions(parsed: dict) -> list[dict]:
    """Normaliza `{"actions": [...]}`; devolve [] se não houver lote."""
    raw = parsed.get("actions")
    if not isinstance(raw, list):
        return []
    actions = []
    for item in raw[:MAX_BATCH_ACTIONS]:
        if not isinstance(item, dict):
            continue
        name = item.get("tool") or item.get("name")
        args = item.get("args")
        if isinstance(name, str) and isinstance(args, dict):
            actions.append({"tool": name, "args": args})
    return actions


def _batch_allowed(actions: list[dict], tools: dict) -> bool:
    """Só ferramentas de leitura, existentes no schema da task."""
    return bool(actions) and all(
        action["tool"] in BATCH_SAFE_TOOLS and action["tool"] in tools
        for action in actions
    )


def _compact_arg(value):
    """Encolhe strings grandes de um args de tool para o histórico."""
    if isinstance(value, str):
        if len(value) > 150:
            return value[:100] + f"... [omitido {len(value)} chars]"
        return value
    if isinstance(value, dict):
        return {k: _compact_arg(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_compact_arg(v) for v in value]
    return value


def _compact_message_content(content: str) -> str:
    """Compacta uma mensagem antiga, preservando tool/path."""
    if not isinstance(content, str):
        content = str(content)
    if content.startswith(("Resultado da tool:", "Resultado do lote:")):
        return content[:400] + "\n[... resultado antigo compactado ...]"
    try:
        obj = json.loads(content)
    except (ValueError, TypeError):
        return content[:400] + ("\n[... compactado ...]" if len(content) > 400 else "")
    if not isinstance(obj, dict):
        return content[:400]
    if "tool" in obj:
        obj = {"tool": obj["tool"], "args": _compact_arg(obj.get("args") or {})}
    elif "actions" in obj and isinstance(obj["actions"], list):
        obj = {
            "actions": [
                {
                    "tool": item.get("tool", ""),
                    "args": _compact_arg(item.get("args") or {}),
                }
                for item in obj["actions"]
                if isinstance(item, dict)
            ]
        }
    else:
        return content[:600]
    return json.dumps(obj, ensure_ascii=False)


def _compact_history(
    messages: list[dict],
    *,
    max_chars: int = HISTORY_MAX_CHARS,
    keep_last: int = HISTORY_KEEP_LAST,
) -> bool:
    """
    Resume resultados/chamadas antigas quando o histórico fica grande.

    Mantém o system prompt (0), o prompt inicial da task (1) e as últimas
    `keep_last` mensagens. O resto vira um resumo compacto — o conteúdo
    completo dos arquivos continua no disco.

    Retorna True se compactou.
    """
    if len(messages) <= keep_last + 2:
        return False
    total = sum(len(str(m.get("content", ""))) for m in messages)
    if total <= max_chars:
        return False

    end = len(messages) - keep_last
    for index in range(2, end):
        msg = messages[index]
        msg["content"] = _compact_message_content(msg.get("content", ""))
    return True


def _execute_read_batch(
    actions: list[dict],
    tools: dict,
    step: int,
    on_step,
    on_confirm_path,
    return_parts: bool = False,
) -> str | list[str]:
    """
    Executa um lote de leituras independentes e devolve um único resultado.

    Só é chamado quando todas as tools são de leitura; qualquer escrita
    continua uma por step.
    """
    from tool_dispatch import get_path_checks
    from workspace import get_workspace

    _call(on_step, step, "lote", f"{len(actions)} leituras independentes", "tool")
    parts: list[str] = []

    for index, action in enumerate(actions, start=1):
        name = action["tool"]
        args = dict(action["args"])
        blocked = False

        for arg_name, need_write in get_path_checks(name, tools):
            raw_path = args.get(arg_name)
            if not raw_path:
                continue
            _, err = get_workspace().check(raw_path, need_write)
            if err:
                allowed = on_confirm_path(raw_path, need_write) if on_confirm_path else False
                if not allowed:
                    parts.append(
                        f"## {index}. {name}\nAcesso a '{raw_path}' negado."
                    )
                    blocked = True
                    break
        if blocked:
            continue

        try:
            result = tools[name]["fn"](**args)
            text = str(result)
            if len(text) > MAX_BATCH_RESULT_CHARS:
                text = (
                    text[:MAX_BATCH_RESULT_CHARS]
                    + f"\n[... truncado em {MAX_BATCH_RESULT_CHARS} caracteres ...]"
                )
            parts.append(f"## {index}. {name}\n{text}")
            _call(on_step, step, "resultado", f"{name}: {text[:100]}", "done")
        except TypeError as exc:
            sig = inspect.signature(tools[name]["fn"])
            parts.append(
                f"## {index}. {name}\nArgs inválidos: {exc}. "
                f"Assinatura correta: {name}{sig}"
            )
        except Exception as exc:
            parts.append(f"## {index}. {name}\nErro: {exc}")

    if return_parts:
        return parts
    return "\n\n".join(parts)


def _call_model(messages: list, model: str, ollama_url: str) -> tuple[str, int, int]:
    """
    Caminho padrão: Ollama (`/api/chat`), sem streaming.

    A implementação HTTP vive em `llm/client.py` (fonte única); esta função
    mantém a assinatura antiga porque `task_runner`, testes e chamadores
    externos ainda a usam diretamente.
    """
    result = OllamaClient(ollama_url, timeout=120).chat(messages, model=model)
    return result.as_tuple()


def _chat_completion_result(
    client,
    messages: list,
    model: str,
    ollama_url: str,
    tools: list[dict] | None = None,
) -> ChatResult:
    """Chamada com suporte opcional a tools nativas; normaliza dublês."""
    if client is None:
        raw, t_in, t_out = _call_model(messages, model, ollama_url)
        return ChatResult(raw, t_in, t_out)
    result = client.chat(messages, model=model or None, tools=tools)
    if isinstance(result, ChatResult):
        return result
    if hasattr(result, "as_tuple"):
        raw, t_in, t_out = result.as_tuple()
        return ChatResult(raw, t_in, t_out)
    raw, t_in, t_out = result
    return ChatResult(raw, t_in, t_out)


def _chat_completion(
    client,
    messages: list,
    model: str,
    ollama_url: str,
) -> tuple[str, int, int]:
    """Uma chamada ao modelo, pelo cliente injetado ou pelo Ollama padrão."""
    return _chat_completion_result(client, messages, model, ollama_url).as_tuple()


def _build_system_prompt(
    agent_info: dict,
    schema: list,
    web_base_url: str | None = None,
    session_id: str | None = None,
    profile: str = "local",
) -> str:
    core_prompt = ""
    core_name = "core_build.md" if profile == PERFIL_NUVEM else "core_prompt.md"
    core_path = Path("system") / core_name
    if not core_path.exists():          # fallback: instalação sem o arquivo
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
        f"\nperfil: {profile}"
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
    messages: list, model: str, ollama_url: str, model_client=None
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
        raw, _, _ = _chat_completion(model_client, probe, model, ollama_url)
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
        parse_errors: int = 0,
        compactions: int = 0,
        context_peak_chars: int = 0,
        tool_calls: int = 0,
        batch_calls: int = 0,
        system_chars: int = 0,
        schema_chars: int = 0,
        task_context_chars: int = 0,
        history_chars: int = 0,
        prompt_chars: int = 0,
    ):
        self.status   = status
        self.message  = message
        self.proposal = proposal
        self.tokens_in  = tokens_in
        self.tokens_out = tokens_out
        self.steps    = steps
        self.parse_errors = parse_errors
        self.compactions = compactions
        self.context_peak_chars = context_peak_chars
        self.tool_calls = tool_calls
        self.batch_calls = batch_calls
        self.system_chars = system_chars
        self.schema_chars = schema_chars
        self.task_context_chars = task_context_chars
        self.history_chars = history_chars
        self.prompt_chars = prompt_chars

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
    mcp_manager=None,
    # callbacks
    on_step: OnStep | None = None,
    on_model_start: OnModelStart | None = None,
    on_model_end: OnModelEnd | None = None,
    on_done: OnDone | None = None,
    on_limit: OnLimit | None = None,
    on_error: OnError | None = None,
    # callbacks de segurança — implementados pela CLI via Prompt.ask e pela
    # TUI via modal bloqueante (threading.Event). on_confirm_tool=None NÃO
    # significa "sem confirmação": se needs_confirmation() marcar a tool
    # como sensível, a chamada é bloqueada por padrão (nega, não assume
    # permissão). Pra rodar headless permitindo essas tools, passe um
    # callback que sempre retorna True — a decisão fica explícita no
    # chamador, não implícita no loop.
    on_confirm_tool: Callable[[str, str], bool] | None = None,
    on_confirm_path: Callable[[str, bool], bool] | None = None,
    # callback pra tools INTERACTIVE (ex: entrevista_interativa) perguntarem
    # algo ao usuário em vez de usar input()/print() direto — quebraria a
    # TUI, que já controla o terminal. None = tool roda sem essa injeção
    # (ela mesma decide o que fazer, ex: erro dizendo que precisa do harness).
    on_ask_user: Callable[[str, list[str] | None], str] | None = None,
    # cliente de modelo opcional (llm.client.BaseClient). None = caminho
    # histórico (Ollama via ollama_url), preservando 100% o comportamento
    # atual. O runner do modo build injeta um cliente cloud aqui.
    model_client=None,
    # perfil define o core prompt: "local" (orquestrador + secondary_model)
    # ou "nuvem" (o próprio modelo é o principal).
    profile: str = "local",
    # Em multitask, steps esgotados não devem pedir proposta de nova tool:
    # quem decide é a checagem da task. Evita uma chamada extra e o status
    # "needs_tool" sem handler.
    allow_tool_proposal: bool = True,
    # Orçamento de tokens desta task (0 = sem limite). Se estourar, o loop
    # devolve status "limit"; o runner decide pela checagem.
    budget_tokens: int = 0,
    deadline: float | None = None,
    cancel_event=None,
) -> AgentResult:
    """
    Executa o loop agêntico e retorna um AgentResult.

    Não imprime nada — todo feedback vai pelos callbacks.
    Compatível com execução em thread (Textual @work).
    """
    profile = normalize_perfil(profile)
    total_in  = 0
    total_out = 0
    parse_errors = 0
    compactions = 0
    context_peak_chars = 0
    tool_calls = 0
    batch_calls = 0

    def _mk(status: str, message: str = "", proposal=None, steps: int = 0) -> AgentResult:
        return AgentResult(
            status, message, proposal,
            tokens_in=total_in, tokens_out=total_out, steps=steps,
            parse_errors=parse_errors, compactions=compactions,
            context_peak_chars=context_peak_chars,
            tool_calls=tool_calls, batch_calls=batch_calls,
            system_chars=system_chars, schema_chars=schema_chars,
            task_context_chars=task_context_chars,
            history_chars=history_chars, prompt_chars=prompt_chars,
        )

    def _system_prompt() -> str:
        """System prompt atual; reaplicado quando o registry recarrega."""
        prompt = _build_system_prompt(
            agent_info, schema,
            web_base_url=web_base_url,
            session_id=session_id,
            profile=profile,
        )
        if context_injection:
            prompt = f"{prompt}\n\n{context_injection}"
        return prompt

    system_prompt = _system_prompt()

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

    system_chars = len(system_prompt)
    schema_chars = len(json.dumps(schema, ensure_ascii=False))
    task_context_chars = len(user_input or "") + len(context_injection or "")
    history_chars = sum(len(str(m.get("content", ""))) for m in context)
    prompt_chars = sum(len(str(m.get("content", ""))) for m in messages)

    nudge_sent = False
    native_tools_enabled = bool(
        model_client is not None
        and getattr(model_client, "native_tools", False)
    )
    for step in range(1, max_steps + 1):
        if cancel_event is not None and cancel_event.is_set():
            _call(on_step, step, "cancelado", "subagente cancelado", "error")
            return _mk(
                "cancelled",
                "Subagente cancelado.",
                steps=max(0, step - 1),
            )
        if deadline is not None and time.monotonic() >= deadline:
            _call(on_limit, step, total_in, total_out)
            return _mk(
                "timeout",
                "⚠ Tempo máximo do subagente atingido.",
                steps=max(0, step - 1),
            )
        if (
            profile == PERFIL_NUVEM
            and not nudge_sent
            and max_steps >= 5
            and step == max_steps - 2
        ):
            messages.append({
                "role": "user",
                "content": (
                    "[sistema] Restam poucos steps. Finalize a task agora: "
                    "responda com done e um resumo curto do que já foi feito. "
                    "Não inicie novas correções longas nem crie scripts."
                ),
            })
            nudge_sent = True
        if profile == PERFIL_NUVEM:
            if _compact_history(messages):
                compactions += 1
        context_peak_chars = max(
            context_peak_chars,
            sum(len(str(m.get("content", ""))) for m in messages),
        )
        _call(on_model_start, step)
        _call(on_step, step, "modelo", "aguardando…", "model")

        try:
            native_schema = (
                to_openai_tools(schema)
                if native_tools_enabled and schema else None
            )
            completion = _chat_completion_result(
                model_client, messages, model, ollama_url,
                tools=native_schema,
            )
            raw, t_in, t_out = completion.as_tuple()
            total_in  += t_in
            total_out += t_out
            if budget_tokens and total_in + total_out >= budget_tokens:
                _call(on_limit, step, total_in, total_out)
                return _mk(
                    "limit",
                    f"⚠ Orçamento de tokens da task atingido ({budget_tokens}).",
                    steps=step,
                )
        except LLMError as e:
            msg = f"Erro no cliente de modelo: {e}"
            _call(on_error, "connection", str(e))
            return _mk("error", msg, steps=step)
        except requests.RequestException as e:
            target = "o cliente de modelo" if model_client is not None else "Ollama"
            msg = f"Erro de conexão com {target}: {e}"
            _call(on_error, "connection", str(e))
            return _mk("error", msg, steps=step)
        finally:
            _call(on_model_end, step)

        # ── tool calls nativos (somente leituras em lote por enquanto) ───────
        if completion.tool_calls:
            actions = [
                {"tool": call["name"], "args": call.get("arguments") or {}}
                for call in completion.tool_calls
            ]
            if len(actions) <= MAX_BATCH_ACTIONS and _batch_allowed(actions, tools):
                tool_calls += len(actions)
                batch_calls += 1
                parts = _execute_read_batch(
                    actions, tools, step, on_step, on_confirm_path,
                    return_parts=True,
                )
                messages.append({
                    "role": "assistant",
                    "content": raw or "",
                    "tool_calls": [
                        {
                            "id": call["id"],
                            "type": "function",
                            "function": {
                                "name": call["name"],
                                "arguments": call.get("arguments_raw", "{}"),
                            },
                        }
                        for call in completion.tool_calls
                    ],
                })
                for call, part in zip(completion.tool_calls, parts):
                    messages.append({
                        "role": "tool",
                        "tool_call_id": call["id"],
                        "content": str(part),
                    })
                continue

            native_tools_enabled = False
            feedback = (
                "Tool calls nativos só são aceitos para leituras independentes "
                f"({', '.join(sorted(BATCH_SAFE_TOOLS))}). Para escrita, use o "
                "formato JSON normal."
            )
            _call(on_step, step, "nativo", feedback, "error")
            messages.append({"role": "assistant", "content": raw or ""})
            messages.append({"role": "user", "content": feedback})
            continue

        parsed = _parse_response(raw)

        # ── done ──────────────────────────────────────────────────────────────
        if parsed.get("done"):
            msg = parsed.get("message", "Concluído.")
            _call(on_step, step, "done", msg, "done")
            _call(on_done, msg, step, total_in, total_out)
            return _mk("done", msg, steps=step)

        # ── parse error ───────────────────────────────────────────────────────
        if "error" in parsed:
            parse_errors += 1
            _call(on_step, step, "parse error", parsed["error"], "parse_error")
            messages.append({"role": "assistant", "content": raw})
            messages.append({
                "role": "user",
                "content": (
                    "[SISTEMA] Formato inválido detectado. "
                    "Continue respondendo APENAS em JSON puro, sem texto adicional, "
                    "sem markdown. O usuário não viu sua resposta anterior."
                ),
            })
            continue

        # ── lote de leituras independentes ────────────────────────────────────
        if "actions" in parsed:
            actions = _extract_actions(parsed)
            if not actions:
                feedback = (
                    "Lote inválido: use {\"actions\": [{\"tool\": ..., "
                    "\"args\": {...}}, ...]}."
                )
                _call(on_step, step, "lote", feedback, "error")
                messages.append({"role": "assistant", "content": raw})
                messages.append({"role": "user", "content": feedback})
                continue

            if not _batch_allowed(actions, tools):
                feedback = (
                    "Lote recusado: `actions` é só para leituras independentes "
                    f"({', '.join(sorted(BATCH_SAFE_TOOLS))}). "
                    "Escritas e ações dependentes continuam uma por step."
                )
                _call(on_step, step, "lote", feedback, "error")
                messages.append({"role": "assistant", "content": raw})
                messages.append({"role": "user", "content": feedback})
                continue

            tool_calls += len(actions)
            batch_calls += 1
            batch_feedback = _execute_read_batch(
                actions, tools, step, on_step, on_confirm_path
            )
            messages.append({"role": "assistant", "content": raw})
            messages.append({
                "role": "user",
                "content": f"Resultado do lote:\n{batch_feedback}",
            })
            continue

        # ── tool call ─────────────────────────────────────────────────────────
        tool_name = parsed.get("tool", "")
        if not tool_name:
            parse_errors += 1
            feedback = (
                "Resposta sem tool, actions ou done. Responda em JSON puro: "
                '{"tool": "...", "args": {...}} ou {"done": true, ...}.'
            )
            _call(on_step, step, "parse error", feedback, "parse_error")
            messages.append({"role": "assistant", "content": raw})
            messages.append({"role": "user", "content": feedback})
            continue
        tool_calls += 1
        args      = parsed.get("args", {})

        _call(on_step, step, f"tool › {tool_name}", json.dumps(args, ensure_ascii=False)[:80], "tool")

        if tool_name not in tools:
            feedback = f"Tool '{tool_name}' não existe. Disponíveis: {list(tools.keys())}"
            _call(on_step, step, "erro", feedback, "error")
        else:
            try:
                # ── workspace guard ───────────────────────────────────────────
                # Verifica paths declarados em PERMISSIONS antes de invocar.
                # on_confirm_path é injetado pela CLI/TUI; None = sem checagem
                # (headless ou chamador que cuida disso por conta própria).
                if on_confirm_path is not None:
                    from tool_dispatch import get_path_checks
                    from workspace import get_workspace
                    _blocked = False
                    for arg_name, need_write in get_path_checks(tool_name, tools):
                        raw_path = args.get(arg_name)
                        if not raw_path:
                            continue
                        _resolved, _err = get_workspace().check(raw_path, need_write)
                        if _err:
                            allowed = on_confirm_path(raw_path, need_write)
                            if not allowed:
                                feedback = f"Acesso a '{raw_path}' negado pelo usuário."
                                _call(on_step, step, "bloqueado", feedback, "error")
                                _blocked = True
                                break
                    if _blocked:
                        messages.append({"role": "assistant", "content": raw})
                        messages.append({"role": "user", "content": f"Resultado da tool: {feedback}"})
                        continue

                # ── confirmação de tool sensível ──────────────────────────────
                # Centralizado: needs_confirmation() decide se a tool é sensível
                # (mesma função que a cli.py já usa hoje via tool_dispatch —
                # antes, só create_tool/create_temp_tool eram checadas aqui).
                #
                # Chamamos sempre com trusted=False: "confiar pro resto da
                # sessão" passa a ser responsabilidade do callback
                # (on_confirm_tool), que pode devolver True sem perguntar de
                # novo — igual _modal_confirm_tool da TUI já faz hoje via
                # self._trust_tool_creation. Isso mantém o estado de trust
                # fora do loop (decisão da Fase 0 do mapa de migração).
                
                from tool_dispatch import needs_confirmation
                if needs_confirmation(tool_name, False):
                    if on_confirm_tool is None:
                        # nega por padrão: sem callback não dá pra confirmar
                        # com o usuário, então não assume permissão (antes,
                        # on_confirm_tool=None deixava a tool passar direto).
                        feedback = (
                            f"Tool '{tool_name}' bloqueada: precisa de "
                            f"confirmação e nenhum on_confirm_tool foi passado "
                            f"a run_agent()."
                        )
                        _call(on_step, step, "bloqueado", feedback, "error")
                        messages.append({"role": "assistant", "content": raw})
                        messages.append({"role": "user", "content": f"Resultado da tool: {feedback}"})
                        continue

                    tool_code = args.get("tool_code", "")
                    allowed = on_confirm_tool(tool_name, tool_code)
                    if not allowed:
                        feedback = f"Execução de '{tool_name}' recusada pelo usuário."
                        _call(on_step, step, "recusado", feedback, "error")
                        messages.append({"role": "assistant", "content": raw})
                        messages.append({"role": "user", "content": f"Resultado da tool: {feedback}"})
                        continue

                if tool_name == "run_script":
                    from workspace import get_workspace as _gws
                    args.setdefault("cwd", str(_gws().default_root))

                if tool_name in ("list_sources", "search_knowledge"):
                    args.setdefault("agent_id", agent_info.get("id", "general"))
                    args.setdefault("session_id", str(session_id) if session_id else "")
                if tool_name == "secondary_model":
                    args.setdefault("session_id", str(session_id) if session_id else "_nosession")
                if tools.get(tool_name, {}).get("interactive") and on_ask_user is not None:
                    args.setdefault("perguntar", on_ask_user)

                feedback = tools[tool_name]["fn"](**args)
                _call(on_step, step, "resultado", str(feedback)[:100], "done")

                # reload automático após criação de tool
                if tool_name in ("create_tool", "create_temp_tool") and "Erro" not in str(feedback):
                    from tools_registry import load_tools, tools_schema
                    from agent_loader import filter_tools, filter_mcp_tools
                    all_updated = load_tools()
                    tools.clear()
                    tools.update(filter_tools(all_updated, agent_info.get("allowed_tools")))
                    if mcp_manager is not None:
                        tools.update(filter_mcp_tools(
                            mcp_manager.all_tools(),
                            agent_info.get("allowed_mcp_servers"),
                        ))
                    if profile == PERFIL_NUVEM:
                        tools.pop("secondary_model", None)
                    schema.clear()
                    schema.extend(tools_schema(tools))
                    messages[0]["content"] = _system_prompt()
                    _call(on_step, step, "registry", f"{len(tools)} tools carregadas", "done")

                # reload automático após adicionar servidor MCP
                if tool_name == "mcp_add_server" and mcp_manager is not None and "conectado" in str(feedback):
                    from agent_loader import filter_mcp_tools
                    tools.update(filter_mcp_tools(
                        mcp_manager.all_tools(),
                        agent_info.get("allowed_mcp_servers"),
                    ))
                    if profile == PERFIL_NUVEM:
                        tools.pop("secondary_model", None)
                    schema.clear()
                    schema.extend(tools_schema(tools))
                    messages[0]["content"] = _system_prompt()
                    _call(on_step, step, "registry", f"{len(tools)} tools carregadas", "done")

                # reload automático após remover servidor MCP
                if tool_name == "mcp_remove_server" and mcp_manager is not None and "removido" in str(feedback):
                    removed_name = feedback.split("'")[1] if "'" in str(feedback) else ""
                    if removed_name:
                        mcp_manager.remove_server_tools(removed_name, tools)
                    if profile == PERFIL_NUVEM:
                        tools.pop("secondary_model", None)
                    schema.clear()
                    schema.extend(tools_schema(tools))
                    messages[0]["content"] = _system_prompt()
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
        tool_content = InputVerifier.wrap_tool_output(tool_name, str(feedback), tools)
        messages.append({"role": "user", "content": f"Resultado da tool: {tool_content}"})

    # ── steps esgotados ───────────────────────────────────────────────────────
    proposal = None
    if allow_tool_proposal:
        proposal = _ask_model_for_tool_proposal(
            messages, model, ollama_url, model_client=model_client
        )

    if proposal:
        _call(on_limit, max_steps, total_in, total_out)
        return _mk("needs_tool", proposal=proposal, steps=max_steps)

    _call(on_limit, max_steps, total_in, total_out)
    return _mk("limit", "⚠ Limite de steps atingido sem conclusão.", steps=max_steps)