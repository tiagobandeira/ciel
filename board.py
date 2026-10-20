"""
board.py — quadro de estado de uma execução multitask.

O princípio do roadmap: **estado em disco, não no contexto**. Cada execução
tem um `data/runs/<id>/board.json` com objetivo, fases, tasks, status,
resumos, artefatos e decisões. O runner lê o quadro, monta o contexto de
uma task, executa, grava o resultado — e o modelo nunca vê o quadro inteiro.

Este módulo é puro (stdlib), sem UI e sem modelo. Só define:
  - o formato (`Board`, `PhaseState`, `TaskState`)
  - a persistência (`BoardStore`: escrita atômica, listagem, eventos)
  - a trava por execução (`RunLock`)

`data/` é gitignored, então boards de experimento não sujam o repositório.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import tempfile
import unicodedata
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

BOARD_VERSION = 1
BOARD_FILENAME = "board.json"
EVENTS_FILENAME = "eventos.jsonl"
LOCK_FILENAME = ".lock"
DEFAULT_RUNS_DIR = Path("data") / "runs"

# ── status ────────────────────────────────────────────────────────────────

RUN_CRIADA      = "criada"
RUN_EM_ANDAMENTO = "em_andamento"
RUN_PAUSADA     = "pausada"
RUN_CONCLUIDA   = "concluida"
RUN_FALHOU      = "falhou"
RUN_CANCELADA   = "cancelada"

TASK_PENDENTE    = "pendente"
TASK_EM_ANDAMENTO = "em_andamento"
TASK_CONCLUIDA   = "concluida"
TASK_FALHOU      = "falhou"
TASK_BLOQUEADA   = "bloqueada"
TASK_PULADA      = "pulada"

RUN_STATUSES = frozenset({
    RUN_CRIADA, RUN_EM_ANDAMENTO, RUN_PAUSADA,
    RUN_CONCLUIDA, RUN_FALHOU, RUN_CANCELADA,
})
TASK_STATUSES = frozenset({
    TASK_PENDENTE, TASK_EM_ANDAMENTO, TASK_CONCLUIDA,
    TASK_FALHOU, TASK_BLOQUEADA, TASK_PULADA,
})
TASK_TERMINAIS = frozenset({TASK_CONCLUIDA, TASK_PULADA})

# eventos que o runner emite (seção 9 do roadmap)
EVENT_TYPES = frozenset({
    "run_criada", "run_iniciada", "run_pausada", "run_retomada",
    "run_encerrada",
    "fase_iniciada", "fase_concluida",
    "task_iniciada", "task_concluida", "task_falhou", "task_pulada",
    "checagem_ok", "checagem_falhou", "correcao_iniciada", "task_corrigida",
    "checkpoint", "replanejado",
})

_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class BoardError(Exception):
    """Erro genérico de quadro."""


class BoardNotFound(BoardError):
    """Execução não encontrada em data/runs/."""


class BoardLocked(BoardError):
    """Já existe outra instância rodando esta execução."""

    def __init__(self, run_id: str, info: dict | None = None):
        self.run_id = run_id
        self.info = info or {}
        pid = self.info.get("pid", "?")
        host = self.info.get("host", "?")
        super().__init__(
            f"execução '{run_id}' já está em uso (pid={pid} host={host}). "
            f"Se for uma trava órfã, use force=True."
        )


# ── utilidades ────────────────────────────────────────────────────────────

def now_iso() -> str:
    """Data/hora local com offset, resolução de segundos."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def slugify(text: str, max_len: int = 40) -> str:
    """`Site de portfólio!` → `site-de-portfolio`."""
    normalized = unicodedata.normalize("NFKD", text or "")
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    ascii_text = re.sub(r"[^A-Za-z0-9]+", "-", ascii_text).strip("-").lower()
    return ascii_text[:max_len].strip("-") or "run"


def make_run_id(objetivo: str, *, now: datetime | None = None) -> str:
    stamp = (now or datetime.now()).strftime("%Y%m%d_%H%M%S")
    return f"{stamp}_{slugify(objetivo)}"


def default_orcamento() -> dict:
    """Limites duros propostos na seção 10 (0 = sem limite explícito)."""
    return {
        "max_tasks": 20,
        "max_replans": 2,
        "max_correcoes_por_task": 3,
        "max_falhas_iguais": 2,
        "max_tokens": 0,
    }


def _coerce_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _pid_alive(pid: int) -> bool | None:
    """
    True/False quando dá para verificar, None quando não dá.

    No Windows, `os.kill(pid, 0)` NÃO é seguro (mata o processo); usamos
    OpenProcess. Qualquer falha retorna None ("não sei"), e quem chama
    decide não roubar a trava.
    """
    if not pid or pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes

            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(
                PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid)
            )
            if handle:
                kernel32.CloseHandle(handle)
                return True
            return False
        except Exception:
            return None
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return None


# ── task ──────────────────────────────────────────────────────────────────

@dataclass
class TaskState:
    """Uma unidade de trabalho do quadro."""

    id: str
    titulo: str
    status: str = TASK_PENDENTE
    objetivo: str = ""
    acoes: list[str] = field(default_factory=list)
    resultado_esperado: str = ""
    checagem: Any = None
    checagem_ok: bool | None = None
    checagem_resumo: str = ""
    resumo: str = ""
    artefatos: list[dict] = field(default_factory=list)
    decisoes: list[str] = field(default_factory=list)
    agente: str = ""
    tools: list[str] | None = None
    depende_de: list[str] = field(default_factory=list)
    tentativas: int = 0
    correcoes: int = 0
    erro: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    duracao_s: float = 0.0
    iniciada_em: str = ""
    concluida_em: str = ""

    def __post_init__(self):
        self.status = str(self.status or TASK_PENDENTE)
        self.depende_de = [str(d) for d in (self.depende_de or [])]
        self.decisoes = [str(d) for d in (self.decisoes or [])]
        self.acoes = [str(a) for a in (self.acoes or [])]
        if self.tools is not None:
            self.tools = [str(t) for t in self.tools]

        normalized: list[dict] = []
        for item in self.artefatos or []:
            if isinstance(item, dict):
                normalized.append(dict(item))
            else:
                normalized.append({"path": str(item), "mtime": None})
        self.artefatos = normalized
        self.tokens_in = _coerce_int(self.tokens_in)
        self.tokens_out = _coerce_int(self.tokens_out)
        self.tentativas = _coerce_int(self.tentativas)
        self.correcoes = _coerce_int(self.correcoes)
        try:
            self.duracao_s = float(self.duracao_s or 0.0)
        except (TypeError, ValueError):
            self.duracao_s = 0.0

    @property
    def terminal(self) -> bool:
        return self.status in TASK_TERMINAIS

    @property
    def total_tokens(self) -> int:
        return self.tokens_in + self.tokens_out

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "TaskState":
        allowed = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in (data or {}).items() if k in allowed})


# ── fase ──────────────────────────────────────────────────────────────────

@dataclass
class PhaseState:
    nome: str
    tasks: list[TaskState] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "nome": self.nome,
            "tasks": [t.to_dict() for t in self.tasks],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PhaseState":
        return cls(
            nome=str((data or {}).get("nome", "")),
            tasks=[
                TaskState.from_dict(t)
                for t in ((data or {}).get("tasks") or [])
            ],
        )


# ── quadro ────────────────────────────────────────────────────────────────

@dataclass
class Board:
    """Estado completo de uma execução."""

    id: str = ""
    objetivo: str = ""
    fluxo: str = ""
    perfil: str = "local"
    status: str = RUN_CRIADA
    versao: int = BOARD_VERSION
    criado_em: str = ""
    atualizado_em: str = ""
    sessao_id: int | str | None = None
    entrega: dict = field(default_factory=dict)
    orcamento: dict = field(default_factory=dict)
    fases: list[PhaseState] = field(default_factory=list)
    meta: dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.id:
            self.id = make_run_id(self.objetivo)
        if not self.criado_em:
            self.criado_em = now_iso()
        if not self.atualizado_em:
            self.atualizado_em = self.criado_em
        if not self.orcamento:
            self.orcamento = default_orcamento()
        if self.status not in RUN_STATUSES:
            self.status = RUN_CRIADA
        self.entrega = dict(self.entrega or {})
        self.orcamento = dict(self.orcamento or {})
        self.meta = dict(self.meta or {})

    # ── construção ────────────────────────────────────────────────────────
    @classmethod
    def new(
        cls,
        objetivo: str,
        *,
        fluxo: str = "",
        perfil: str = "local",
        entrega: dict | None = None,
        orcamento: dict | None = None,
        run_id: str | None = None,
        sessao_id: int | str | None = None,
        meta: dict | None = None,
    ) -> "Board":
        return cls(
            id=run_id or make_run_id(objetivo),
            objetivo=objetivo,
            fluxo=fluxo,
            perfil=perfil,
            status=RUN_CRIADA,
            entrega=dict(entrega or {}),
            orcamento=dict(orcamento or default_orcamento()),
            sessao_id=sessao_id,
            meta=dict(meta or {}),
        )

    # ── acesso ────────────────────────────────────────────────────────────
    def tasks(self) -> list[TaskState]:
        return [task for phase in self.fases for task in phase.tasks]

    def __iter__(self) -> Iterator[TaskState]:
        return iter(self.tasks())

    def phase(self, nome: str) -> PhaseState | None:
        for phase in self.fases:
            if phase.nome == nome:
                return phase
        return None

    def task(self, task_id: str) -> TaskState | None:
        for task in self.tasks():
            if task.id == task_id:
                return task
        return None

    def add_phase(self, nome: str) -> PhaseState:
        nome = (nome or "").strip()
        if not nome:
            raise BoardError("nome de fase vazio")
        if self.phase(nome) is not None:
            raise BoardError(f"fase '{nome}' já existe")
        phase = PhaseState(nome=nome)
        self.fases.append(phase)
        return phase

    def _next_task_id(self) -> str:
        biggest = 0
        for task in self.tasks():
            match = re.fullmatch(r"t(\d+)", task.id or "")
            if match:
                biggest = max(biggest, int(match.group(1)))
        return f"t{biggest + 1}"

    def add_task(
        self,
        fase: str,
        titulo: str,
        *,
        objetivo: str = "",
        acoes: list[str] | None = None,
        resultado_esperado: str = "",
        checagem: Any = None,
        agente: str = "",
        tools: list[str] | None = None,
        depende_de: list[str] | None = None,
        status: str = TASK_PENDENTE,
        task_id: str | None = None,
    ) -> TaskState:
        phase = self.phase(fase)
        if phase is None:
            phase = self.add_phase(fase)

        if task_id is None:
            task_id = self._next_task_id()
        if self.task(task_id) is not None:
            raise BoardError(f"task id '{task_id}' duplicado")

        if status not in TASK_STATUSES:
            raise BoardError(f"status de task inválido: {status}")

        task = TaskState(
            id=task_id,
            titulo=titulo,
            status=status,
            objetivo=objetivo,
            acoes=list(acoes or []),
            resultado_esperado=resultado_esperado,
            checagem=checagem,
            agente=agente,
            tools=list(tools) if tools is not None else None,
            depende_de=list(depende_de or []),
        )
        phase.tasks.append(task)
        return task

    def dependencies_met(self, task: TaskState) -> bool:
        for dep in task.depende_de:
            other = self.task(dep)
            if other is None or other.status not in TASK_TERMINAIS:
                return False
        return True

    def next_pending(self) -> TaskState | None:
        for task in self.tasks():
            if task.status == TASK_PENDENTE and self.dependencies_met(task):
                return task
        return None

    # ── mutação ───────────────────────────────────────────────────────────
    def mark_task(self, task_id: str, status: str, **fields) -> TaskState:
        task = self.task(task_id)
        if task is None:
            raise BoardError(f"task '{task_id}' não existe")
        if status not in TASK_STATUSES:
            raise BoardError(f"status de task inválido: {status}")

        if status == TASK_EM_ANDAMENTO and not task.iniciada_em:
            task.iniciada_em = now_iso()
        if status in TASK_TERMINAIS or status == TASK_FALHOU:
            task.concluida_em = now_iso()

        task.status = status
        for key, value in fields.items():
            if hasattr(task, key):
                setattr(task, key, value)
        self.touch()
        return task

    def add_artifact(
        self,
        task_id: str,
        path: str,
        *,
        mtime: float | None = None,
    ) -> dict:
        task = self.task(task_id)
        if task is None:
            raise BoardError(f"task '{task_id}' não existe")

        if mtime is None:
            try:
                mtime = Path(path).stat().st_mtime
            except OSError:
                mtime = None

        entry = {"path": str(path), "mtime": mtime}
        for existing in task.artefatos:
            if existing.get("path") == entry["path"]:
                existing.update(entry)
                return existing
        task.artefatos.append(entry)
        self.touch()
        return entry

    def add_decision(self, task_id: str, decision: str) -> None:
        task = self.task(task_id)
        if task is None:
            raise BoardError(f"task '{task_id}' não existe")
        decision = (decision or "").strip()
        if decision and decision not in task.decisoes:
            task.decisoes.append(decision)
            self.touch()

    def record_task_result(
        self,
        task_id: str,
        status: str,
        *,
        resumo: str = "",
        erro: str = "",
        tokens_in: int = 0,
        tokens_out: int = 0,
        duracao_s: float = 0.0,
        artefatos: list[str] | None = None,
        decisoes: list[str] | None = None,
        correcoes: int | None = None,
        checagem_ok: bool | None = None,
        checagem_resumo: str | None = None,
    ) -> TaskState:
        fields = {
            "resumo": resumo,
            "erro": erro,
            "tokens_in": _coerce_int(tokens_in),
            "tokens_out": _coerce_int(tokens_out),
            "duracao_s": float(duracao_s or 0.0),
        }
        if correcoes is not None:
            fields["correcoes"] = _coerce_int(correcoes)
        if checagem_ok is not None:
            fields["checagem_ok"] = bool(checagem_ok)
        if checagem_resumo is not None:
            fields["checagem_resumo"] = str(checagem_resumo)

        task = self.mark_task(task_id, status, **fields)
        for path in artefatos or []:
            self.add_artifact(task_id, path)
        for decision in decisoes or []:
            self.add_decision(task_id, decision)
        return task

    def set_status(self, status: str) -> None:
        if status not in RUN_STATUSES:
            raise BoardError(f"status de execução inválido: {status}")
        self.status = status
        self.touch()

    def touch(self) -> None:
        self.atualizado_em = now_iso()

    # ── consultas ─────────────────────────────────────────────────────────
    def progress(self) -> dict:
        tasks = self.tasks()
        counts = {
            "total": len(tasks),
            "pendentes": 0,
            "em_andamento": 0,
            "concluidas": 0,
            "falhas": 0,
            "puladas": 0,
            "bloqueadas": 0,
        }
        for task in tasks:
            if task.status == TASK_PENDENTE:
                counts["pendentes"] += 1
            elif task.status == TASK_EM_ANDAMENTO:
                counts["em_andamento"] += 1
            elif task.status == TASK_CONCLUIDA:
                counts["concluidas"] += 1
            elif task.status == TASK_FALHOU:
                counts["falhas"] += 1
            elif task.status == TASK_PULADA:
                counts["puladas"] += 1
            elif task.status == TASK_BLOQUEADA:
                counts["bloqueadas"] += 1
        return counts

    def is_complete(self) -> bool:
        tasks = self.tasks()
        return bool(tasks) and all(t.status in TASK_TERMINAIS for t in tasks)

    def total_tokens(self) -> tuple[int, int]:
        tokens_in = sum(t.tokens_in for t in self.tasks())
        tokens_out = sum(t.tokens_out for t in self.tasks())
        return tokens_in, tokens_out

    def validate(self) -> list[str]:
        """Erros estruturais do quadro (regras de negócio ficam no planner)."""
        errors: list[str] = []

        if not (self.objetivo or "").strip():
            errors.append("objetivo vazio")

        if not self.fases:
            errors.append("quadro sem fases")

        seen_phases: set[str] = set()
        seen_ids: set[str] = set()
        all_ids = {t.id for t in self.tasks()}

        for phase in self.fases:
            if not (phase.nome or "").strip():
                errors.append("fase com nome vazio")
            if phase.nome in seen_phases:
                errors.append(f"fase duplicada: {phase.nome}")
            seen_phases.add(phase.nome)

            for task in phase.tasks:
                if not (task.id or "").strip():
                    errors.append(f"task sem id na fase '{phase.nome}'")
                elif task.id in seen_ids:
                    errors.append(f"task id duplicado: {task.id}")
                seen_ids.add(task.id)

                if not (task.titulo or "").strip():
                    errors.append(f"task {task.id} sem título")
                if task.status not in TASK_STATUSES:
                    errors.append(f"task {task.id} com status inválido: {task.status}")
                for dep in task.depende_de:
                    if dep not in all_ids:
                        errors.append(
                            f"task {task.id} depende de '{dep}', que não existe"
                        )
                    if dep == task.id:
                        errors.append(f"task {task.id} depende de si mesma")

        max_tasks = self.orcamento.get("max_tasks")
        if max_tasks is not None and _coerce_int(max_tasks, -1) >= 0:
            if len(all_ids) > _coerce_int(max_tasks):
                errors.append(
                    f"{len(all_ids)} tasks excedem max_tasks={max_tasks}"
                )

        for key in ("max_replans", "max_correcoes_por_task", "max_tokens"):
            value = self.orcamento.get(key)
            if value is not None and _coerce_int(value, -1) < 0:
                errors.append(f"orçamento inválido: {key}={value}")

        return errors

    # ── serialização ──────────────────────────────────────────────────────
    def to_dict(self) -> dict:
        return {
            "versao": self.versao,
            "id": self.id,
            "objetivo": self.objetivo,
            "fluxo": self.fluxo,
            "perfil": self.perfil,
            "status": self.status,
            "criado_em": self.criado_em,
            "atualizado_em": self.atualizado_em,
            "sessao_id": self.sessao_id,
            "entrega": dict(self.entrega),
            "orcamento": dict(self.orcamento),
            "fases": [phase.to_dict() for phase in self.fases],
            "meta": dict(self.meta),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Board":
        if not isinstance(data, dict):
            raise BoardError("board.json inválido: esperado um objeto JSON")
        return cls(
            id=str(data.get("id", "")),
            objetivo=str(data.get("objetivo", "")),
            fluxo=str(data.get("fluxo", "")),
            perfil=str(data.get("perfil", "local")),
            status=str(data.get("status", RUN_CRIADA)),
            versao=_coerce_int(data.get("versao", BOARD_VERSION), BOARD_VERSION),
            criado_em=str(data.get("criado_em", "")),
            atualizado_em=str(data.get("atualizado_em", "")),
            sessao_id=data.get("sessao_id"),
            entrega=dict(data.get("entrega") or {}),
            orcamento=dict(data.get("orcamento") or {}),
            fases=[
                PhaseState.from_dict(item)
                for item in (data.get("fases") or [])
            ],
            meta=dict(data.get("meta") or {}),
        )


# ── trava por execução ────────────────────────────────────────────────────

class RunLock:
    """
    Trava simples baseada em arquivo (`.lock` na pasta da execução).

    - `acquire()` falha com BoardLocked se já existir uma trava viva;
    - `force=True` sobrescreve (uso explícito para trava órfã);
    - `release()` só remove a trava se ela for deste processo.
    """

    def __init__(self, path: Path, *, run_id: str = "", force: bool = False):
        self.path = Path(path)
        self.run_id = run_id
        self.force = force
        self._acquired = False

    def _payload(self) -> dict:
        return {
            "run_id": self.run_id,
            "pid": os.getpid(),
            "host": socket.gethostname(),
            "criado_em": now_iso(),
        }

    def _write_new(self, payload: dict) -> None:
        fd = os.open(
            self.path,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            0o600,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False)
                handle.flush()
                os.fsync(handle.fileno())
        except Exception:
            try:
                os.unlink(self.path)
            except OSError:
                pass
            raise

    def acquire(self) -> "RunLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = self._payload()
        try:
            self._write_new(payload)
        except FileExistsError:
            info = self.info() or {}
            if not self.force:
                raise BoardLocked(self.run_id or self.path.parent.name, info)
            tmp = self.path.parent / (self.path.name + ".tmp")
            tmp.write_text(json.dumps(payload), encoding="utf-8")
            os.replace(tmp, self.path)
        self._acquired = True
        return self

    def release(self) -> bool:
        if not self._acquired:
            return False
        info = self.info() or {}
        if (
            info.get("pid") == os.getpid()
            and info.get("host") == socket.gethostname()
        ):
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass
            self._acquired = False
            return True
        return False

    def info(self) -> dict | None:
        if not self.path.exists():
            return None
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return None
        if not isinstance(data, dict):
            return None

        data = dict(data)
        same_host = data.get("host") == socket.gethostname()
        alive = _pid_alive(_coerce_int(data.get("pid"), 0)) if same_host else None
        data["ativo"] = alive
        data["stale"] = (alive is False)
        return data

    def __enter__(self) -> "RunLock":
        return self.acquire()

    def __exit__(self, *exc) -> None:
        self.release()


# ── persistência ──────────────────────────────────────────────────────────

class BoardStore:
    """Lê/grava quadros em `data/runs/<id>/`."""

    def __init__(self, runs_dir: str | Path | None = None):
        self.runs_dir = Path(runs_dir) if runs_dir else DEFAULT_RUNS_DIR

    # paths ───────────────────────────────────────────────────────────────
    def run_dir(self, run_id: str) -> Path:
        run_id = str(run_id or "")
        if not _RUN_ID_RE.match(run_id) or ".." in run_id:
            raise BoardError(f"run_id inválido: {run_id!r}")
        return self.runs_dir / run_id

    def board_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / BOARD_FILENAME

    def events_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / EVENTS_FILENAME

    def lock_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / LOCK_FILENAME

    # leitura ─────────────────────────────────────────────────────────────
    def exists(self, run_id: str) -> bool:
        try:
            return self.board_path(run_id).exists()
        except BoardError:
            return False

    def load(self, run_id: str) -> Board:
        path = self.board_path(run_id)
        if not path.exists():
            raise BoardNotFound(f"execução '{run_id}' não encontrada")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise BoardError(f"não foi possível ler {path}: {exc}") from exc
        return Board.from_dict(data)

    def list_runs(self) -> list[dict]:
        if not self.runs_dir.exists():
            return []

        summaries: list[dict] = []
        for entry in self.runs_dir.iterdir():
            if not entry.is_dir():
                continue
            board_path = entry / BOARD_FILENAME
            if not board_path.exists():
                continue
            try:
                board = self.load(entry.name)
            except BoardError:
                continue
            progress = board.progress()
            summaries.append({
                "id": board.id,
                "objetivo": board.objetivo,
                "fluxo": board.fluxo,
                "perfil": board.perfil,
                "status": board.status,
                "criado_em": board.criado_em,
                "atualizado_em": board.atualizado_em,
                **progress,
            })

        summaries.sort(
            key=lambda item: (item.get("criado_em") or "", item.get("id") or ""),
            reverse=True,
        )
        return summaries

    def latest(self) -> Board | None:
        runs = self.list_runs()
        return self.load(runs[0]["id"]) if runs else None

    # escrita ─────────────────────────────────────────────────────────────
    def _atomic_write(self, path: Path, data: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            prefix=".board.", suffix=".tmp", dir=str(path.parent)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, path)
        except Exception:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise

    def save(self, board: Board) -> Path:
        board.touch()
        path = self.board_path(board.id)
        self._atomic_write(path, board.to_dict())
        return path

    def create(self, board: Board, *, overwrite: bool = False) -> Path:
        run_dir = self.run_dir(board.id)

        if run_dir.exists() and not overwrite:
            # colisão de id (dois runs no mesmo segundo): sufixa
            if (run_dir / BOARD_FILENAME).exists():
                base = board.id
                suffix = 2
                while self.run_dir(f"{base}_{suffix}").exists():
                    suffix += 1
                board.id = f"{base}_{suffix}"
                run_dir = self.run_dir(board.id)

        run_dir.mkdir(parents=True, exist_ok=True)
        path = self.save(board)
        self.append_event(
            board.id, "run_criada",
            objetivo=board.objetivo,
            fluxo=board.fluxo,
            perfil=board.perfil,
        )
        return path

    def delete(self, run_id: str, *, require_no_lock: bool = True) -> None:
        run_dir = self.run_dir(run_id)
        if not run_dir.exists():
            raise BoardNotFound(f"execução '{run_id}' não encontrada")
        if require_no_lock and (run_dir / LOCK_FILENAME).exists():
            lock = RunLock(self.lock_path(run_id), run_id=run_id)
            info = lock.info() or {}
            if info.get("ativo") is not False:
                raise BoardLocked(run_id, info)
        resolved = run_dir.resolve()
        base = self.runs_dir.resolve()
        if base not in resolved.parents:
            raise BoardError(f"recusando remover fora de {base}: {resolved}")
        shutil.rmtree(resolved)

    # trava ───────────────────────────────────────────────────────────────
    def lock(self, run_id: str, *, force: bool = False) -> RunLock:
        return RunLock(
            self.lock_path(run_id), run_id=run_id, force=force
        )

    # eventos ─────────────────────────────────────────────────────────────
    def append_event(self, run_id: str, tipo: str, **dados) -> dict:
        run_dir = self.run_dir(run_id)
        if not run_dir.exists():
            raise BoardNotFound(f"execução '{run_id}' não encontrada")

        event = {"ts": now_iso(), "tipo": tipo, **dados}
        path = self.events_path(run_id)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return event

    def read_events(self, run_id: str) -> list[dict]:
        path = self.events_path(run_id)
        if not path.exists():
            return []
        events: list[dict] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict):
                events.append(event)
        return events


__all__ = [
    "BOARD_VERSION",
    "BOARD_FILENAME",
    "EVENTS_FILENAME",
    "LOCK_FILENAME",
    "DEFAULT_RUNS_DIR",
    "RUN_CRIADA", "RUN_EM_ANDAMENTO", "RUN_PAUSADA", "RUN_CONCLUIDA",
    "RUN_FALHOU", "RUN_CANCELADA",
    "TASK_PENDENTE", "TASK_EM_ANDAMENTO", "TASK_CONCLUIDA",
    "TASK_FALHOU", "TASK_BLOQUEADA", "TASK_PULADA",
    "RUN_STATUSES", "TASK_STATUSES", "TASK_TERMINAIS", "EVENT_TYPES",
    "BoardError", "BoardNotFound", "BoardLocked",
    "TaskState", "PhaseState", "Board", "BoardStore", "RunLock",
    "now_iso", "slugify", "make_run_id", "default_orcamento",
]
