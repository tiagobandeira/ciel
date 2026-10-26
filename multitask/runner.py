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
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Any, Callable

from agent_loader import load_agent
from agent_loop import BATCH_SAFE_TOOLS, OLLAMA_URL, run_agent
from llm.roles import PERFIL_NUVEM, normalize_perfil
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
from multitask.reviewer import review_phase

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

def build_task_context(board: Board, task, phase: str, profile: str = "local") -> str:
    """
    Contexto mínimo de uma task: objetivo geral, a própria task, as
    dependências que ela declarou e o que já foi concluído na fase.
    """
    profile = normalize_perfil(profile)
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
        "- Use APENAS as tools disponíveis neste schema; ignore menções a tools "
        "ausentes no prompt.",
        "- Use as tools disponíveis para inspecionar e alterar o workspace real.",
        "- Não invente caminhos de arquivo: confirme o que existe antes de agir.",
        "- Para criar pastas use create_directory; não use write_file com .keep "
        "nem run_script para isso.",
    ]
    if profile == PERFIL_NUVEM:
        lines.append(
            "- A tool secondary_model não existe nesta sessão; crie e edite "
            "arquivos diretamente com write_file/edit_file."
        )
    else:
        lines.append(
            "- Se usar secondary_model com mode=\"code\", passe output_dir com o "
            "caminho exato pedido; sem output_dir a tool cria "
            "data/user/<folder>_<timestamp>."
        )
    lines += [
        "- Arquivos grandes: escreva cada arquivo em UMA chamada quando couber "
        "em ~8.000 caracteres; divida só se passar. Não faça chunks de 2.000 "
        "por padrão.",
        "- Para ler/editar arquivo grande use read_file com offset/limit ou "
        "start_line/end_line e edit_file/apply_patch; não crie scripts de "
        "leitura ou correção.",
        "- Não releia o arquivo inteiro depois de escrever; finalize a task. "
        "Só leia de novo se a checagem falhar.",
        "- Leituras independentes podem ir em um único actions (até 4); "
        "não agrupe escritas nem ações dependentes.",
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
    profile: str = "local",
    revisar_fases: bool = False,
    max_parallel: int = 2,
    cancel_event=None,
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
            profile=profile,
            revisar_fases=revisar_fases,
            max_parallel=max_parallel,
            cancel_event=cancel_event,
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
    profile: str = "local",
    revisar_fases: bool = False,
    max_parallel: int = 2,
    cancel_event=None,
) -> RunResult:
    started = time.monotonic()
    tokens_in = 0
    tokens_out = 0
    tasks_ok: list[str] = []
    tasks_fail: list[str] = []
    stopped_at = ""
    motivo = ""
    current_phase: str | None = None
    reviewed_phases: set[str] = set()
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
        resumed_ids = _apply_subagent_checkpoints(board, store, on_event)
        for tid in resumed_ids:
            task_done = board.task(tid)
            if task_done is not None:
                tasks_ok.append(tid)
                tokens_in += task_done.tokens_in
                tokens_out += task_done.tokens_out

        while True:
            task = board.next_pending()
            if task is None:
                break

            if cancel_event is not None and cancel_event.is_set():
                board.set_status(RUN_PAUSADA)
                store.save(board)
                _emit(store, board, on_event, "run_pausada",
                      motivo="cancelado pelo usuário")
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

            if max_parallel and max_parallel > 1 and getattr(task, "parallel", False):
                batch = _parallel_candidates(board, task, max_parallel)
                if len(batch) > 1:
                    total_tasks = len(board.tasks())
                    for item in batch:
                        _emit(
                            store, board, on_event, "task_iniciada",
                            task=item.id, titulo=item.titulo, fase=phase,
                            indice=_task_index(board, item), total=total_tasks,
                        )
                    results = _parallel_execute(
                        batch, board, phase, tools, schema, agent_info,
                        store=store,
                        model=model,
                        model_client=model_client,
                        session_id=session_id,
                        max_steps_per_task=max_steps_per_task,
                        ollama_url=ollama_url,
                        mcp_manager=mcp_manager,
                        callbacks=callbacks,
                        root=root,
                        profile=profile,
                        cancel_event=cancel_event,
                    )
                    phase_state = board.phase(phase)
                    batch_failed = False
                    batch_cancelled = False
                    for original, branch, branch_task, outcome in results:
                        if phase_state is not None:
                            for index, current in enumerate(phase_state.tasks):
                                if current.id == original.id:
                                    phase_state.tasks[index] = branch_task
                                    break
                        metric = branch.meta.get("metricas", {}).get(original.id)
                        if metric:
                            board.meta.setdefault("metricas", {})[original.id] = metric
                        tokens_in += outcome.tokens_in
                        tokens_out += outcome.tokens_out
                        _record_subagent(
                            store, board, branch_task, phase, parallel=True,
                            metricas=branch.meta.get("metricas", {}).get(
                                original.id
                            ),
                        )
                        stopped_at = original.id
                        current_task_id = original.id
                        if outcome.status == "done":
                            tasks_ok.append(original.id)
                            _emit(
                                store, board, on_event, "task_concluida",
                                task=original.id, titulo=branch_task.titulo,
                                fase=phase, resumo=branch_task.resumo,
                                tokens_in=outcome.tokens_in,
                                tokens_out=outcome.tokens_out,
                                duracao_s=branch_task.duracao_s,
                                artefatos=[
                                    a.get("path") for a in branch_task.artefatos
                                ],
                                correcoes=branch_task.correcoes,
                                checagem=branch_task.checagem_resumo,
                                checagem_ok=branch_task.checagem_ok,
                                paralelo=True,
                            )
                        elif outcome.status == "cancelled":
                            batch_cancelled = True
                            branch_task.status = TASK_PENDENTE
                            branch_task.resumo = "cancelado pelo usuário"
                            branch_task.erro = ""
                        else:
                            batch_failed = True
                            tasks_fail.append(original.id)
                            _emit(
                                store, board, on_event, "task_falhou",
                                task=original.id, titulo=branch_task.titulo,
                                fase=phase, erro=outcome.erro or outcome.motivo,
                                tokens_in=outcome.tokens_in,
                                tokens_out=outcome.tokens_out,
                                paralelo=True,
                            )
                    store.save(board)
                    if _phase_finished(board, phase):
                        _emit(store, board, on_event, "fase_concluida", fase=phase)
                        if (
                            revisar_fases
                            and profile == PERFIL_NUVEM
                            and model_client is not None
                            and phase not in reviewed_phases
                        ):
                            reviewed_phases.add(phase)
                            review = review_phase(
                                board, phase, model_client, model=model,
                                available_tools=set(tools),
                            )
                            tokens_in += review.tokens_in
                            tokens_out += review.tokens_out
                            store.save(board)
                            if review.errors:
                                _emit(
                                    store, board, on_event, "fase_revisao_falhou",
                                    fase=phase, erros=review.errors,
                                    mudancas=review.applied,
                                    tokens_in=review.tokens_in,
                                    tokens_out=review.tokens_out,
                                )
                            else:
                                _emit(
                                    store, board, on_event, "fase_revisada",
                                    fase=phase, resumo=review.resumo,
                                    mudancas=review.applied,
                                    tokens_in=review.tokens_in,
                                    tokens_out=review.tokens_out,
                                )
                    if batch_cancelled:
                        board.set_status(RUN_PAUSADA)
                        store.save(board)
                        _emit(store, board, on_event, "run_pausada",
                              motivo="cancelado pelo usuário")
                        break
                    if batch_failed:
                        board.set_status(RUN_FALHOU)
                        store.save(board)
                        motivo = "task paralela falhou"
                        break
                    continue

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
                profile=profile,
                cancel_event=cancel_event,
            )

            tokens_in += outcome.tokens_in
            tokens_out += outcome.tokens_out
            _record_subagent(store, board, task, phase)

            if outcome.status == "cancelled":
                board.set_status(RUN_PAUSADA)
                store.save(board)
                _emit(store, board, on_event, "run_pausada",
                      motivo="cancelado pelo usuário")
                break

            if outcome.status == "done":
                tasks_ok.append(task.id)
                if _phase_finished(board, phase):
                    _emit(store, board, on_event, "fase_concluida", fase=phase)
                    if (
                        revisar_fases
                        and profile == PERFIL_NUVEM
                        and model_client is not None
                        and phase not in reviewed_phases
                    ):
                        reviewed_phases.add(phase)
                        review = review_phase(
                            board, phase, model_client, model=model,
                            available_tools=set(tools),
                        )
                        tokens_in += review.tokens_in
                        tokens_out += review.tokens_out
                        if review.errors:
                            store.save(board)
                            _emit(
                                store, board, on_event, "fase_revisao_falhou",
                                fase=phase, erros=review.errors,
                                mudancas=review.applied,
                                tokens_in=review.tokens_in,
                                tokens_out=review.tokens_out,
                            )
                        else:
                            store.save(board)
                            _emit(
                                store, board, on_event, "fase_revisada",
                                fase=phase, resumo=review.resumo,
                                mudancas=review.applied,
                                tokens_in=review.tokens_in,
                                tokens_out=review.tokens_out,
                            )
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


def _max_same_check_failures(board: Board) -> int:
    try:
        return max(1, int(board.orcamento.get("max_falhas_iguais", 2)))
    except (TypeError, ValueError):
        return 2


def _record_task_metrics(board: Board, task, metrics: dict) -> None:
    """Guarda métricas por task em board.meta (não em TaskState)."""
    board.meta.setdefault("metricas", {})[task.id] = dict(metrics)


def _tools_for_task(task, tools: dict, schema: list) -> tuple[dict, list]:
    """
    Restringe o schema às tools declaradas na task (`tools:` no fluxo).

    Menos tools = menos tokens por step e menos distração. Sem `tools:`,
    mantém o conjunto global (comportamento histórico).
    """
    allowed = getattr(task, "tools", None)
    if not allowed:
        return tools, schema

    selected = {name: spec for name, spec in tools.items() if name in allowed}
    selected_schema = [
        item for item in schema
        if isinstance(item, dict) and item.get("name") in selected
    ]
    return selected, selected_schema


def _record_subagent(
    store: BoardStore,
    board: Board,
    task,
    phase: str,
    *,
    parallel: bool = False,
    metricas: dict | None = None,
) -> None:
    """Persiste o resultado do subagente em data/runs/<id>/subagents/."""
    try:
        target = store.run_dir(board.id) / "subagents"
        target.mkdir(parents=True, exist_ok=True)
        data = {
            "id": task.id,
            "titulo": task.titulo,
            "fase": phase,
            "agente": task.agente or "general",
            "modelo": task.modelo or "",
            "perfil": task.perfil or "",
            "timeout_s": task.timeout_s,
            "tools": list(task.tools or []),
            "read_only": bool(task.read_only),
            "status": task.status,
            "resumo": task.resumo,
            "erro": task.erro,
            "tokens_in": task.tokens_in,
            "tokens_out": task.tokens_out,
            "duracao_s": task.duracao_s,
            "correcoes": task.correcoes,
            "checagem_ok": task.checagem_ok,
            "checagem": task.checagem_resumo,
            "artefatos": list(task.artefatos),
            "parallel": parallel,
            "metricas": dict(metricas or {}),
            "atualizado_em": now_iso(),
        }
        path = target / f"{task.id}.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
    except Exception:
        pass


class _NullStore:
    """Store no-op para execuções paralelas em boards isolados."""

    def save(self, board) -> None:
        pass

    def append_event(self, *args, **kwargs) -> None:
        pass


def _apply_subagent_checkpoints(
    board: Board,
    store: BoardStore,
    on_event=None,
) -> list[str]:
    """Aplica estados concluídos gravados por um lote paralelo interrompido."""
    sub_dir = store.run_dir(board.id) / "subagents"
    if not sub_dir.is_dir():
        return []
    applied: list[str] = []
    for path in sorted(sub_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if str(data.get("status", "")) != TASK_CONCLUIDA:
            continue
        task = board.task(str(data.get("id", "")))
        if task is None or task.status != TASK_PENDENTE:
            continue
        task.status = TASK_CONCLUIDA
        task.resumo = str(data.get("resumo", ""))
        task.erro = ""
        task.tokens_in = int(data.get("tokens_in", 0) or 0)
        task.tokens_out = int(data.get("tokens_out", 0) or 0)
        task.duracao_s = float(data.get("duracao_s", 0) or 0)
        task.correcoes = int(data.get("correcoes", 0) or 0)
        task.checagem_ok = data.get("checagem_ok")
        task.checagem_resumo = str(data.get("checagem", "") or "")
        task.artefatos = list(data.get("artefatos", []) or [])
        metricas = data.get("metricas")
        if isinstance(metricas, dict):
            board.meta.setdefault("metricas", {})[task.id] = metricas
        applied.append(task.id)
        _emit(
            store, board, on_event, "task_concluida",
            task=task.id, titulo=task.titulo,
            fase=str(data.get("fase", "") or ""),
            resumo=task.resumo[:500],
            tokens_in=task.tokens_in, tokens_out=task.tokens_out,
            duracao_s=task.duracao_s, artefatos=task.artefatos,
            correcoes=task.correcoes, checagem=task.checagem_resumo,
            checagem_ok=task.checagem_ok, retomado=True,
        )
    if applied:
        board.touch()
        store.save(board)
    return applied



PARALLEL_WRITE_TOOLS = {
    "write_file", "write_files", "edit_file", "apply_patch",
    "create_directory", "copy_template", "prepare_kernel",
}


def _norm_write(path: str) -> str:
    return Path(str(path)).expanduser().resolve().as_posix().lower()


def _writes_overlap(a: set[str], b: set[str]) -> bool:
    for left in a:
        for right in b:
            if left == right:
                return True
            if left.startswith(right.rstrip("/") + "/"):
                return True
            if right.startswith(left.rstrip("/") + "/"):
                return True
    return False


def _parallel_mode(task):
    tools = set(task.tools or [])
    writes = list(getattr(task, "writes", []) or [])
    if not tools or getattr(task, "read_only", False) and writes:
        return None, set()
    if not writes and tools <= BATCH_SAFE_TOOLS:
        return "read", set()
    if writes and tools <= (BATCH_SAFE_TOOLS | PARALLEL_WRITE_TOOLS):
        return "write", {_norm_write(p) for p in writes}
    return None, set()


def _parallel_candidates(board: Board, first, max_parallel: int = 2) -> list:
    """Tasks irmãs seguras: read-only ou escrita com paths disjuntos."""
    if getattr(first, "parallel", False) is not True:
        return []
    mode, first_writes = _parallel_mode(first)
    if mode is None:
        return []

    phase_name = _phase_of(board, first)
    phase = board.phase(phase_name)
    if phase is None:
        return []
    batch = [first]
    batch_writes = set(first_writes)
    for task in phase.tasks:
        if len(batch) >= max(2, int(max_parallel or 2)):
            break
        if task.id == first.id or task.status != TASK_PENDENTE:
            continue
        if getattr(task, "parallel", False) is not True:
            continue
        task_mode, task_writes = _parallel_mode(task)
        if task_mode != mode:
            continue
        if mode == "write" and _writes_overlap(batch_writes, task_writes):
            continue
        if any(
            (board.task(dep) is None or not board.task(dep).is_terminal())
            for dep in task.depende_de
        ):
            continue
        batch.append(task)
        batch_writes |= task_writes
    return batch


def _parallel_execute(
    batch: list,
    board: Board,
    phase: str,
    tools: dict,
    schema: list,
    agent_info: dict,
    *,
    store: BoardStore,
    model: str,
    model_client,
    session_id,
    max_steps_per_task: int,
    ollama_url: str,
    mcp_manager,
    callbacks: dict,
    root: Path,
    profile: str,
    cancel_event=None,
):
    """Executa um lote em boards isolados e devolve (task_original, board, outcome)."""
    jobs = []
    for task in batch:
        branch = deepcopy(board)
        branch_task = branch.task(task.id)
        jobs.append((task, branch, branch_task))

    def run_one(job):
        original, branch, branch_task = job
        try:
            outcome = _execute_task(
                branch, branch_task, phase, tools, schema, agent_info,
                store=_NullStore(),
                model=model,
                model_client=model_client,
                session_id=session_id,
                max_steps=max_steps_per_task,
                ollama_url=ollama_url,
                mcp_manager=mcp_manager,
                callbacks=callbacks,
                on_event=None,
                root=root,
                tokens_before=(0, 0),
                profile=profile,
                cancel_event=cancel_event,
            )
            metricas = branch.meta.get("metricas", {}).get(branch_task.id)
            _record_subagent(
                store, branch, branch_task, phase,
                parallel=True, metricas=metricas,
            )
            return original, branch, branch_task, outcome
        except Exception as exc:
            return original, branch, branch_task, _TaskOutcome(
                "failed", erro=str(exc), motivo=str(exc),
            )
    results = []
    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        futures = [pool.submit(run_one, job) for job in jobs]
        for future in futures:
            results.append(future.result())
    return results



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
    profile: str = "local",
    cancel_event=None,
) -> _TaskOutcome:
    """
    Executa UMA task até concluir, esgotar as correções ou falhar.

    Ciclo: run_agent → checagem por código → (se falhar) correção com o erro
    e os arquivos envolvidos, até `max_correcoes_por_task`.
    """
    task_model = str(getattr(task, "modelo", "") or "").strip()
    if task_model:
        model = task_model
    task_perfil = normalize_perfil(getattr(task, "perfil", "") or profile)
    if task_perfil != normalize_perfil(profile):
        try:
            from llm.roles import load_roles

            task_roles = load_roles(
                model or "gemma4:cloud", perfil=task_perfil,
            )
            spec = task_roles.orchestrator
            if spec is not None:
                if spec.is_local:
                    model_client = None
                    model = task_model or spec.model or model
                else:
                    model_client = spec.client()
                    model = ""
                profile = task_perfil
        except Exception:
            pass
    total = len(board.tasks())
    index = _task_index(board, task)
    task_started = time.time()
    task_clock = time.monotonic()
    try:
        task_timeout = float(getattr(task, "timeout_s", 0) or 0)
    except (TypeError, ValueError):
        task_timeout = 0.0
    deadline = task_clock + task_timeout if task_timeout > 0 else None
    tokens_in = 0
    tokens_out = 0
    corrections = 0
    max_corrections = _max_corrections(board)
    max_same = _max_same_check_failures(board)
    last_check_message = ""
    same_check_failures = 0
    metrics = {
        "steps": 0,
        "tokens_in": 0,
        "tokens_out": 0,
        "parse_errors": 0,
        "compactions": 0,
        "context_peak_chars": 0,
        "tool_calls": 0,
        "batch_calls": 0,
        "system_chars": 0,
        "schema_chars": 0,
        "task_context_chars": 0,
        "history_chars": 0,
        "prompt_chars": 0,
    }
    max_steps = int(getattr(task, "max_steps", 0) or 0) or max_steps

    base_context = build_task_context(board, task, phase, profile=profile)
    context = base_context
    task_tools, task_schema = _tools_for_task(task, tools, schema)

    task_agent = agent_info
    if task.agente:
        try:
            task_agent = load_agent(task.agente, profile=profile)
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

    # Task idempotente: se o critério já está satisfeito, não gasta steps.
    if getattr(task, "pular_se_ok", False) and task.checagem is not None:
        pre = run_checks(task.checagem, workspace_root=root)
        if pre.ok and pre.verificado:
            duration = time.monotonic() - task_clock
            resumo = "já satisfazia a checagem; execução pulada"
            artifacts = collect_artifacts(root, task_started)
            board.record_task_result(
                task.id, TASK_CONCLUIDA,
                resumo=resumo,
                tokens_in=0,
                tokens_out=0,
                duracao_s=duration,
                correcoes=0,
                checagem_ok=True,
                checagem_resumo=pre.mensagem,
            )
            for artifact in artifacts:
                board.add_artifact(
                    task.id, artifact["path"], mtime=artifact["mtime"]
                )
            metrics["pulada"] = True
            _record_task_metrics(board, task, metrics)
            store.save(board)
            _emit(
                store, board, on_event, "task_concluida",
                task=task.id, titulo=task.titulo, fase=phase,
                resumo=resumo,
                tokens_in=0, tokens_out=0,
                duracao_s=round(duration, 2),
                artefatos=[a["path"] for a in artifacts],
                correcoes=0,
                checagem=pre.mensagem,
                checagem_ok=True,
                pulada=True,
            )
            return _TaskOutcome("done", tokens_in=0, tokens_out=0)

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

        task_budget = int(board.orcamento.get("max_tokens_por_task") or 0)
        budget_left = (
            max(1, task_budget - tokens_in - tokens_out) if task_budget else 0
        )
        result = run_agent(
            context,
            task_tools,
            task_schema,
            model,
            task_agent,
            history=[],
            session_id=session_id,
            max_steps=max_steps,
            ollama_url=ollama_url,
            mcp_manager=mcp_manager,
            model_client=model_client,
            profile=profile,
            allow_tool_proposal=False,
            budget_tokens=budget_left,
            deadline=deadline,
            cancel_event=cancel_event,
            **callbacks,
        )

        tokens_in += result.tokens_in
        tokens_out += result.tokens_out
        metrics["steps"] += int(getattr(result, "steps", 0) or 0)
        metrics["tokens_in"] += int(getattr(result, "tokens_in", 0) or 0)
        metrics["tokens_out"] += int(getattr(result, "tokens_out", 0) or 0)
        metrics["parse_errors"] += int(getattr(result, "parse_errors", 0) or 0)
        metrics["compactions"] += int(getattr(result, "compactions", 0) or 0)
        metrics["context_peak_chars"] = max(
            metrics["context_peak_chars"],
            int(getattr(result, "context_peak_chars", 0) or 0),
        )
        metrics["tool_calls"] += int(getattr(result, "tool_calls", 0) or 0)
        metrics["batch_calls"] += int(getattr(result, "batch_calls", 0) or 0)
        metrics["system_chars"] = max(
            metrics["system_chars"], int(getattr(result, "system_chars", 0) or 0)
        )
        metrics["schema_chars"] = max(
            metrics["schema_chars"], int(getattr(result, "schema_chars", 0) or 0)
        )
        metrics["task_context_chars"] = max(
            metrics["task_context_chars"],
            int(getattr(result, "task_context_chars", 0) or 0),
        )
        metrics["history_chars"] += int(getattr(result, "history_chars", 0) or 0)
        metrics["prompt_chars"] += int(getattr(result, "prompt_chars", 0) or 0)

        if result.status == "cancelled":
            task.status = TASK_PENDENTE
            task.resumo = "cancelado pelo usuário"
            task.erro = ""
            board.touch()
            store.save(board)
            _record_task_metrics(board, task, metrics)
            return _TaskOutcome(
                "cancelled",
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                motivo="cancelado pelo usuário",
            )

        if result.status != "done":
            # Steps esgotados não significam necessariamente trabalho
            # incompleto: se a checagem por código passar, aceita a task.
            if result.status in ("limit", "needs_tool", "timeout") and task.checagem is not None:
                limit_check = run_checks(task.checagem, workspace_root=root)
                if limit_check.ok and limit_check.verificado:
                    duration = time.monotonic() - task_clock
                    resumo = (
                        f"{result.message or 'steps esgotados'} "
                        f"— aceita pela checagem: {limit_check.mensagem}"
                    )
                    artifacts = collect_artifacts(root, task_started)
                    board.record_task_result(
                        task.id, TASK_CONCLUIDA,
                        resumo=resumo,
                        tokens_in=tokens_in,
                        tokens_out=tokens_out,
                        duracao_s=duration,
                        correcoes=corrections,
                        checagem_ok=True,
                        checagem_resumo=limit_check.mensagem,
                    )
                    for artifact in artifacts:
                        board.add_artifact(
                            task.id, artifact["path"],
                            mtime=artifact["mtime"],
                        )
                    _record_task_metrics(board, task, metrics)
                    store.save(board)
                    _emit(
                        store, board, on_event, "task_concluida",
                        task=task.id, titulo=task.titulo, fase=phase,
                        resumo=resumo[:500],
                        tokens_in=tokens_in,
                        tokens_out=tokens_out,
                        duracao_s=round(duration, 2),
                        artefatos=[a["path"] for a in artifacts],
                        correcoes=corrections,
                        checagem=limit_check.mensagem,
                        checagem_ok=True,
                        limite=True,
                    )
                    return _TaskOutcome(
                        "done",
                        tokens_in=tokens_in,
                        tokens_out=tokens_out,
                    )

            duration = time.monotonic() - task_clock
            erro = result.message or f"status {result.status}"
            _record_task_metrics(board, task, metrics)
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
            _record_task_metrics(board, task, metrics)
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
        if check.mensagem == last_check_message:
            same_check_failures += 1
        else:
            same_check_failures = 1
            last_check_message = check.mensagem

        _emit(
            store, board, on_event, "checagem_falhou",
            task=task.id, titulo=task.titulo,
            checagem_tipo=check.tipo, erro=check.mensagem,
            correcoes=corrections,
            falhas_iguais=same_check_failures,
        )

        if same_check_failures >= max_same:
            duration = time.monotonic() - task_clock
            erro = (
                f"checagem falhou {same_check_failures} vezes com o mesmo "
                f"erro — verifique se o critério de aceite está correto: "
                f"{check.mensagem}"
            )
            _record_task_metrics(board, task, metrics)
            _finish_failed(
                board, store, task, on_event,
                erro=erro, tokens_in=tokens_in, tokens_out=tokens_out,
                duracao_s=duration, correcoes=corrections,
                checagem_ok=False, checagem_resumo=check.mensagem,
            )
            return _TaskOutcome(
                "failed", tokens_in=tokens_in, tokens_out=tokens_out,
                erro=erro, motivo=f"task {task.id}: checagem repetiu o mesmo erro",
            )

        if corrections >= max_corrections:
            duration = time.monotonic() - task_clock
            erro = f"checagem falhou: {check.mensagem}"
            _record_task_metrics(board, task, metrics)
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
            _record_task_metrics(board, task, metrics)
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
