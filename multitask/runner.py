"""
multitask/runner.py — loop externo do modo multitask.

O harness decide (ordem, status, limites, eventos); o modelo só executa uma
task por vez. Cada task roda no `run_agent` existente, com:

  - `history=[]` (o contexto vem do quadro, não da conversa)
  - `context_injection=` com objetivo, fase, ações, dependências e resumos
  - `max_steps` próprio
  - persona opcional por task (`agente:` no fluxo)

O estado é gravado em `data/runs/<id>/board.json` a cada mudança, com trava
por execução. Nada aqui imprime: a UI recebe `on_event` e os callbacks do
`run_agent`.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from agent_loader import load_agent
from agent_loop import OLLAMA_URL, run_agent
from board import (
    RUN_CONCLUIDA,
    RUN_EM_ANDAMENTO,
    RUN_FALHOU,
    RUN_PAUSADA,
    TASK_CONCLUIDA,
    TASK_EM_ANDAMENTO,
    TASK_FALHOU,
    TASK_PENDENTE,
    TASK_PULADA,
    Board,
    BoardStore,
    now_iso,
)
from multitask.checks import build_correction_context, run_checks
from multitask.report import build_report

# callbacks aceitos por run_agent (mantém a assinatura explícita)
_RUN_CALLBACKS = (
    "on_step",
    "on_model_start",
    "on_model_end",
    "on_done",
    "on_limit",
    "on_error",
    "on_confirm_tool",
    "on_confirm_path",
    "on_ask_user",
)

# diretórios que nunca entram na detecção automática de artefatos
_IGNORE_DIR_NAMES = {
    ".git", ".hg", ".svn",
    "venv", ".venv", "env", "node_modules",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "htmlcov", ".idea", ".vscode",
}
_IGNORE_DIR_PREFIXES = {("data", "runs"), ("data", "models")}
_IGNORE_FILE_NAMES = {
    "agent_history.db", ".coverage", "board.json", "eventos.jsonl",
    ".ciel_workspace.json",
}
_IGNORE_SUFFIXES = {".pyc", ".pyo", ".lock", ".tmp"}


@dataclass
class RunResult:
    """Resultado de uma execução multitask."""

    status: str
    board: Board
    message: str
    tokens_in: int = 0
    tokens_out: int = 0
    tasks_ok: list[str] = field(default_factory=list)
    tasks_fail: list[str] = field(default_factory=list)
    stopped_at: str = ""
    motivo: str = ""
    duracao_s: float = 0.0
    erro: str = ""

    @property
    def ok(self) -> bool:
        return self.status == RUN_CONCLUIDA

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "run_id": self.board.id,
            "objetivo": self.board.objetivo,
            "tasks_ok": list(self.tasks_ok),
            "tasks_fail": list(self.tasks_fail),
            "stopped_at": self.stopped_at,
            "motivo": self.motivo,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "duracao_s": self.duracao_s,
            "erro": self.erro,
        }


# ── utilidades públicas ───────────────────────────────────────────────────

def build_task_context(board: Board, task, phase: str) -> str:
    """
    Contexto mínimo de uma task: objetivo geral, a própria task, as
    dependências que ela declarou e o que já foi concluído na fase.
    """
    lines = [
        "## Execução multitask",
        f"Objetivo geral: {board.objetivo}",
        f"Fase atual: {phase}",
        f"Task {task.id}: {task.titulo}",
    ]

    if task.objetivo:
        lines.append(f"Objetivo desta task: {task.objetivo}")
    if task.acoes:
        lines.append("Ações previstas:")
        lines.extend(f"- {acao}" for acao in task.acoes)
    if task.resultado_esperado:
        lines.append(f"Resultado esperado: {task.resultado_esperado}")
    if task.checagem:
        check = task.checagem
        if isinstance(check, (dict, list)):
            check = json.dumps(check, ensure_ascii=False)
        lines.append(f"Critério de aceite: {check}")

    deps = [board.task(dep) for dep in task.depende_de]
    deps = [dep for dep in deps if dep is not None]
    if deps:
        lines += ["", "## Dependências concluídas"]
        for dep in deps:
            lines.append(f"### {dep.id} — {dep.titulo}")
            lines.append(f"Resumo: {dep.resumo or '(sem resumo)'}")
            if dep.artefatos:
                paths = ", ".join(
                    str(item.get("path", "")) for item in dep.artefatos
                )
                lines.append(f"Artefatos: {paths}")
            if dep.decisoes:
                lines.append("Decisões: " + "; ".join(dep.decisoes))

    phase_obj = board.phase(phase)
    done_in_phase = [
        t for t in (phase_obj.tasks if phase_obj else [])
        if t.status == TASK_CONCLUIDA and t.id != task.id
    ]
    if done_in_phase:
        lines += ["", "## Já concluído nesta fase"]
        for done in done_in_phase:
            resumo = (done.resumo or "").strip().replace("\n", " ")[:300]
            lines.append(f"- {done.titulo}: {resumo}")

    lines += [
        "",
        "## Instruções",
        "- Execute SOMENTE esta task. Não antecipe as tasks seguintes.",
        "- Use as tools disponíveis para inspecionar e alterar o workspace real.",
        "- Não invente caminhos de arquivo: confirme o que existe antes de agir.",
        "- Ao terminar, responda com done e uma message curta contendo: "
        "o que foi feito, arquivos criados/alterados e decisões tomadas.",
    ]
    return "\n".join(lines)


def collect_artifacts(
    root: str | Path,
    since_ts: float,
    *,
    max_files: int = 200,
    extra_ignore_dirs: set[str] | None = None,
) -> list[dict]:
    """
    Arquivos modificados/criados desde `since_ts` (epoch), relativos a `root`.

    Usado para preencher `artefatos` do quadro sem depender de o modelo
    listar o que criou. Ignora VCS, venvs, caches, o próprio `data/runs` e
    o banco de histórico.
    """
    root = Path(root).resolve()
    if not root.exists():
        return []

    ignore_dirs = set(_IGNORE_DIR_NAMES)
    if extra_ignore_dirs:
        ignore_dirs |= set(extra_ignore_dirs)

    found: list[dict] = []
    cutoff = float(since_ts) - 1.0

    for dirpath, dirnames, filenames in os.walk(root):
        current = Path(dirpath)
        try:
            rel_dir = current.relative_to(root)
        except ValueError:
            continue

        pruned: list[str] = []
        for name in dirnames:
            candidate = rel_dir / name
            if name in ignore_dirs:
                continue
            if candidate.parts[:2] in _IGNORE_DIR_PREFIXES:
                continue
            pruned.append(name)
        dirnames[:] = pruned

        for filename in filenames:
            if filename in _IGNORE_FILE_NAMES:
                continue
            if Path(filename).suffix.lower() in _IGNORE_SUFFIXES:
                continue

            path = current / filename
            try:
                stat = path.stat()
            except OSError:
                continue
            if stat.st_mtime < cutoff:
                continue

            try:
                rel = path.relative_to(root).as_posix()
            except ValueError:
                continue

            found.append({"path": rel, "mtime": stat.st_mtime})
            if len(found) >= max_files:
                return sorted(found, key=lambda item: item["path"])

    return sorted(found, key=lambda item: item["path"])


# ── helpers internos ──────────────────────────────────────────────────────

def _filter_callbacks(callbacks: dict | None) -> dict:
    callbacks = callbacks or {}
    return {key: callbacks[key] for key in _RUN_CALLBACKS if key in callbacks}


def _emit(store: BoardStore, board: Board, on_event, evento: str, **data) -> None:
    # "tipo" é reservado para o tipo do evento — dados não podem sobrescrever.
    event = {"ts": now_iso(), "run": board.id, **data, "tipo": evento}
    try:
        store.append_event(board.id, evento, run=board.id, **data)
    except Exception:
        pass
    if on_event is not None:
        try:
            on_event(event)
        except Exception:
            pass


def _phase_of(board: Board, task) -> str:
    for phase in board.fases:
        if any(t.id == task.id for t in phase.tasks):
            return phase.nome
    return ""


def _task_index(board: Board, task) -> int:
    for index, item in enumerate(board.tasks(), 1):
        if item.id == task.id:
            return index
    return 0


def _phase_finished(board: Board, phase_name: str) -> bool:
    phase = board.phase(phase_name)
    if phase is None:
        return False
    return all(t.status in (TASK_CONCLUIDA, TASK_PULADA) for t in phase.tasks)


def _reset_running_tasks(board: Board) -> None:
    """Task interrompida volta para pendente (recomeça do zero ao retomar)."""
    for task in board.tasks():
        if task.status == TASK_EM_ANDAMENTO:
            task.status = TASK_PENDENTE
            task.iniciada_em = ""
            task.erro = "interrompida"
    board.touch()


def reset_interrupted_tasks(board: Board) -> None:
    """
    API pública para o harness antes de retomar uma execução: tasks que
    ficaram em `em_andamento` (processo morto/Ctrl+C) voltam a `pendente`.
    """
    _reset_running_tasks(board)


def _budget_exceeded(board: Board, tokens_in: int, tokens_out: int) -> bool:
    try:
        max_tokens = int(board.orcamento.get("max_tokens") or 0)
    except (TypeError, ValueError):
        max_tokens = 0
    return max_tokens > 0 and (tokens_in + tokens_out) >= max_tokens


# ── execução ──────────────────────────────────────────────────────────────

def run_board(
    board: Board,
    tools: dict,
    schema: list,
    agent_info: dict,
    *,
    store: BoardStore | None = None,
    model: str = "",
    model_client=None,
    session_id: str | None = None,
    max_steps_per_task: int = 8,
    ollama_url: str = OLLAMA_URL,
    mcp_manager=None,
    callbacks: dict | None = None,
    on_event: Callable[[dict], None] | None = None,
    should_pause: Callable[[], bool] | None = None,
    workspace_root: str | Path | None = None,
) -> RunResult:
    """
    Executa as tasks pendentes do quadro, em ordem, até concluir, falhar,
    pausar ou esgotar o orçamento.

    `on_event` recebe dicts com `tipo` (ver `board.EVENT_TYPES`). O retorno
    inclui a mensagem final pronta para a UI (`RunResult.message`).
    """
    store = store or BoardStore()
    if not store.exists(board.id):
        store.create(board)

    lock = store.lock(board.id)
    info = lock.info()
    if info and info.get("stale"):
        # processo anterior morreu e deixou a trava — retoma com segurança
        lock = store.lock(board.id, force=True)

    with lock:
        return _execute(
            board, tools, schema, agent_info,
            store=store,
            model=model,
            model_client=model_client,
            session_id=session_id,
            max_steps_per_task=max_steps_per_task,
            ollama_url=ollama_url,
            mcp_manager=mcp_manager,
            callbacks=_filter_callbacks(callbacks),
            on_event=on_event,
            should_pause=should_pause,
            workspace_root=workspace_root,
        )


def _execute(
    board: Board,
    tools: dict,
    schema: list,
    agent_info: dict,
    *,
    store: BoardStore,
    model: str,
    model_client,
    session_id: str | None,
    max_steps_per_task: int,
    ollama_url: str,
    mcp_manager,
    callbacks: dict,
    on_event,
    should_pause,
    workspace_root: str | Path | None,
) -> RunResult:
    started = time.monotonic()
    tokens_in = 0
    tokens_out = 0
    tasks_ok: list[str] = []
    tasks_fail: list[str] = []
    stopped_at = ""
    motivo = ""
    current_phase: str | None = None
    current_task_id = ""
    root = Path(workspace_root) if workspace_root else Path.cwd()

    try:
        resuming = board.status in (RUN_PAUSADA, RUN_FALHOU)
        board.set_status(RUN_EM_ANDAMENTO)
        store.save(board)
        _emit(
            store, board, on_event,
            "run_retomada" if resuming else "run_iniciada",
            objetivo=board.objetivo,
            perfil=board.perfil,
            fluxo=board.fluxo,
            total=len(board.tasks()),
        )

        while True:
            task = board.next_pending()
            if task is None:
                break

            if should_pause is not None and should_pause():
                motivo = "pausa pedida pelo usuário"
                board.set_status(RUN_PAUSADA)
                store.save(board)
                _emit(store, board, on_event, "run_pausada", motivo=motivo)
                break

            if _budget_exceeded(board, tokens_in, tokens_out):
                motivo = "orçamento de tokens esgotado"
                board.set_status(RUN_PAUSADA)
                store.save(board)
                _emit(store, board, on_event, "run_pausada", motivo=motivo)
                break

            phase = _phase_of(board, task)
            if phase != current_phase:
                current_phase = phase
                _emit(store, board, on_event, "fase_iniciada", fase=phase)

            stopped_at = task.id
            current_task_id = task.id

            outcome = _execute_task(
                board, task, phase, tools, schema, agent_info,
                store=store,
                model=model,
                model_client=model_client,
                session_id=session_id,
                max_steps=max_steps_per_task,
                ollama_url=ollama_url,
                mcp_manager=mcp_manager,
                callbacks=callbacks,
                on_event=on_event,
                root=root,
                tokens_before=(tokens_in, tokens_out),
            )

            tokens_in += outcome.tokens_in
            tokens_out += outcome.tokens_out

            if outcome.status == "done":
                tasks_ok.append(task.id)
                if _phase_finished(board, phase):
                    _emit(store, board, on_event, "fase_concluida", fase=phase)
                continue

            tasks_fail.append(task.id)
            motivo = outcome.motivo
            board.set_status(RUN_FALHOU)
            store.save(board)
            break

        if board.status == RUN_EM_ANDAMENTO:
            board.set_status(
                RUN_CONCLUIDA if board.is_complete() else RUN_FALHOU
            )
            store.save(board)

    except KeyboardInterrupt:
        motivo = "interrompido pelo usuário"
        board.set_status(RUN_PAUSADA)
        _reset_running_tasks(board)
        try:
            store.save(board)
        except Exception:
            pass
        _emit(store, board, on_event, "run_pausada", motivo=motivo)

    except Exception as exc:  # erro interno do runner
        motivo = f"erro interno: {exc}"
        current = board.task(current_task_id) if current_task_id else None
        if current is not None and current.status == TASK_EM_ANDAMENTO:
            board.record_task_result(
                current.id, TASK_FALHOU,
                resumo=f"erro interno: {exc}",
                erro=str(exc),
            )
            tasks_fail.append(current.id)
        board.set_status(RUN_FALHOU)
        board.meta["erro"] = str(exc)
        try:
            store.save(board)
        except Exception:
            pass

    finally:
        duration = time.monotonic() - started
        try:
            planner_in = int(board.meta.get("planner_tokens_in") or 0)
            planner_out = int(board.meta.get("planner_tokens_out") or 0)
        except (TypeError, ValueError):
            planner_in = planner_out = 0
        board.meta["duracao_s"] = round(duration, 2)
        # total do relatório inclui planejamento + execução; RunResult
        # devolve só a execução (o CLI soma o planejador à parte).
        board.meta["tokens_in"] = planner_in + tokens_in
        board.meta["tokens_out"] = planner_out + tokens_out
        try:
            store.save(board)
        except Exception:
            pass

    message = build_report(board)
    _emit(
        store, board, on_event, "run_encerrada",
        status=board.status,
        motivo=motivo,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        duracao_s=round(time.monotonic() - started, 2),
    )

    return RunResult(
        status=board.status,
        board=board,
        message=message,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        tasks_ok=tasks_ok,
        tasks_fail=tasks_fail,
        stopped_at=stopped_at,
        motivo=motivo,
        duracao_s=round(time.monotonic() - started, 2),
        erro=str(board.meta.get("erro", "")),
    )


@dataclass
class _TaskOutcome:
    status: str
    tokens_in: int = 0
    tokens_out: int = 0
    erro: str = ""
    motivo: str = ""


def _max_corrections(board: Board) -> int:
    try:
        return max(0, int(board.orcamento.get("max_correcoes_por_task", 3)))
    except (TypeError, ValueError):
        return 3


def _execute_task(
    board: Board,
    task,
    phase: str,
    tools: dict,
    schema: list,
    agent_info: dict,
    *,
    store: BoardStore,
    model: str,
    model_client,
    session_id: str | None,
    max_steps: int,
    ollama_url: str,
    mcp_manager,
    callbacks: dict,
    on_event,
    root: Path,
    tokens_before: tuple[int, int] = (0, 0),
) -> _TaskOutcome:
    """
    Executa UMA task até concluir, esgotar as correções ou falhar.

    Ciclo: run_agent → checagem por código → (se falhar) correção com o erro
    e os arquivos envolvidos, até `max_correcoes_por_task`.
    """
    total = len(board.tasks())
    index = _task_index(board, task)
    task_started = time.time()
    task_clock = time.monotonic()
    tokens_in = 0
    tokens_out = 0
    corrections = 0
    max_corrections = _max_corrections(board)

    base_context = build_task_context(board, task, phase)
    context = base_context

    task_agent = agent_info
    if task.agente:
        try:
            task_agent = load_agent(task.agente)
        except Exception as exc:
            erro = f"persona '{task.agente}' não encontrada: {exc}"
            _finish_failed(
                board, store, task, on_event,
                erro=erro, tokens_in=0, tokens_out=0,
                duracao_s=time.monotonic() - task_clock,
                correcoes=0,
            )
            return _TaskOutcome(
                "failed", erro=erro,
                motivo=f"task {task.id}: persona inválida",
            )

    attempts = 0
    while True:
        attempts += 1
        board.mark_task(task.id, TASK_EM_ANDAMENTO, tentativas=attempts)
        store.save(board)

        if attempts == 1:
            _emit(
                store, board, on_event, "task_iniciada",
                task=task.id, titulo=task.titulo, fase=phase,
                indice=index, total=total,
            )

        result = run_agent(
            context,
            tools,
            schema,
            model,
            task_agent,
            history=[],
            session_id=session_id,
            max_steps=max_steps,
            ollama_url=ollama_url,
            mcp_manager=mcp_manager,
            model_client=model_client,
            **callbacks,
        )

        tokens_in += result.tokens_in
        tokens_out += result.tokens_out

        if result.status != "done":
            duration = time.monotonic() - task_clock
            erro = result.message or f"status {result.status}"
            _finish_failed(
                board, store, task, on_event,
                erro=erro, tokens_in=tokens_in, tokens_out=tokens_out,
                duracao_s=duration, status_original=result.status,
                correcoes=corrections,
            )
            return _TaskOutcome(
                "failed", tokens_in=tokens_in, tokens_out=tokens_out,
                erro=erro,
                motivo=f"task {task.id} terminou com status '{result.status}'",
            )

        check = run_checks(task.checagem, workspace_root=root)
        task.checagem_ok = check.ok if check.verificado else None
        task.checagem_resumo = check.mensagem
        board.touch()
        store.save(board)

        if check.ok:
            duration = time.monotonic() - task_clock
            artifacts = collect_artifacts(root, task_started)
            board.record_task_result(
                task.id, TASK_CONCLUIDA,
                resumo=result.message,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                duracao_s=duration,
                correcoes=corrections,
                checagem_ok=task.checagem_ok,
                checagem_resumo=check.mensagem,
            )
            for artifact in artifacts:
                board.add_artifact(
                    task.id, artifact["path"], mtime=artifact["mtime"]
                )
            store.save(board)

            if corrections:
                _emit(
                    store, board, on_event, "task_corrigida",
                    task=task.id, titulo=task.titulo,
                    correcoes=corrections,
                )

            _emit(
                store, board, on_event, "task_concluida",
                task=task.id, titulo=task.titulo, fase=phase,
                resumo=(result.message or "")[:500],
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                duracao_s=round(duration, 2),
                artefatos=[a["path"] for a in artifacts],
                correcoes=corrections,
                checagem=check.mensagem,
                checagem_ok=task.checagem_ok,
            )
            return _TaskOutcome(
                "done", tokens_in=tokens_in, tokens_out=tokens_out,
            )

        # ── checagem falhou ──────────────────────────────────────────────
        _emit(
            store, board, on_event, "checagem_falhou",
            task=task.id, titulo=task.titulo,
            checagem_tipo=check.tipo, erro=check.mensagem,
            correcoes=corrections,
        )

        if corrections >= max_corrections:
            duration = time.monotonic() - task_clock
            erro = f"checagem falhou: {check.mensagem}"
            _finish_failed(
                board, store, task, on_event,
                erro=erro, tokens_in=tokens_in, tokens_out=tokens_out,
                duracao_s=duration, correcoes=corrections,
                checagem_ok=False, checagem_resumo=check.mensagem,
            )
            return _TaskOutcome(
                "failed", tokens_in=tokens_in, tokens_out=tokens_out,
                erro=erro, motivo=f"task {task.id}: checagem falhou",
            )

        if _budget_exceeded(
            board,
            tokens_before[0] + tokens_in,
            tokens_before[1] + tokens_out,
        ):
            duration = time.monotonic() - task_clock
            erro = "orçamento de tokens esgotado durante a correção"
            _finish_failed(
                board, store, task, on_event,
                erro=erro, tokens_in=tokens_in, tokens_out=tokens_out,
                duracao_s=duration, correcoes=corrections,
                checagem_ok=False, checagem_resumo=check.mensagem,
            )
            return _TaskOutcome(
                "failed", tokens_in=tokens_in, tokens_out=tokens_out,
                erro=erro, motivo=erro,
            )

        corrections += 1
        task.correcoes = corrections
        board.touch()
        store.save(board)
        _emit(
            store, board, on_event, "correcao_iniciada",
            task=task.id, titulo=task.titulo,
            tentativa=corrections, max=max_corrections,
            erro=check.mensagem,
        )

        context = base_context + "\n\n" + build_correction_context(
            check, task=task, workspace_root=root
        )


def _finish_failed(
    board: Board,
    store: BoardStore,
    task,
    on_event,
    *,
    erro: str,
    tokens_in: int,
    tokens_out: int,
    duracao_s: float,
    status_original: str = "",
    correcoes: int | None = None,
    checagem_ok: bool | None = None,
    checagem_resumo: str | None = None,
) -> None:
    board.record_task_result(
        task.id, TASK_FALHOU,
        resumo=erro,
        erro=erro,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        duracao_s=duracao_s,
        correcoes=correcoes,
        checagem_ok=checagem_ok,
        checagem_resumo=checagem_resumo,
    )
    store.save(board)
    _emit(
        store, board, on_event, "task_falhou",
        task=task.id, titulo=task.titulo,
        erro=erro[:500],
        status=status_original or "falhou",
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        duracao_s=round(duracao_s, 2),
        correcoes=correcoes if correcoes is not None else 0,
    )


__all__ = [
    "RunResult",
    "run_board",
    "build_task_context",
    "collect_artifacts",
    "reset_interrupted_tasks",
]
