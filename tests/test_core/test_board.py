"""
tests/test_core/test_board.py

Cobre `board.py` sem modelo/UI:
  - formato (fases, tasks, dependências, progresso, validação)
  - roundtrip JSON
  - persistência atômica e listagem
  - trava por execução
  - eventos JSONL
"""

import json
from pathlib import Path

import pytest

from board import (
    Board,
    BoardError,
    BoardLocked,
    BoardNotFound,
    BoardStore,
    PhaseState,
    RunLock,
    TaskState,
    TASK_CONCLUIDA,
    TASK_EM_ANDAMENTO,
    TASK_FALHOU,
    TASK_PENDENTE,
    TASK_PULADA,
    default_orcamento,
    make_run_id,
    slugify,
)


# ── formato e construção ──────────────────────────────────────────────────

class TestBoardFormato:
    def test_new_defaults(self):
        board = Board.new("Site de portfólio!")
        assert board.status == "criada"
        assert board.id.startswith("20")
        assert board.id.endswith("_site-de-portfolio")
        assert board.orcamento == default_orcamento()
        assert board.criado_em and board.atualizado_em

    def test_slugify(self):
        assert slugify("Site de Portfólio com Ação") == "site-de-portfolio-com-acao"
        assert slugify("!!!") == "run"
        assert len(slugify("x" * 100)) <= 40

    def test_make_run_id(self):
        from datetime import datetime
        run_id = make_run_id("Meu Projeto", now=datetime(2026, 1, 2, 3, 4, 5))
        assert run_id == "20260102_030405_meu-projeto"

    def test_add_phase_e_task(self):
        board = Board.new("x")
        board.add_phase("estrutura")
        t1 = board.add_task("estrutura", "criar pastas")
        t2 = board.add_task("estrutura", "criar index")
        t3 = board.add_task("backend", "criar API")

        assert [t.id for t in (t1, t2, t3)] == ["t1", "t2", "t3"]
        assert t3.status == TASK_PENDENTE
        assert board.phase("backend") is not None
        assert len(board.tasks()) == 3

    def test_fase_duplicada(self):
        board = Board.new("x")
        board.add_phase("a")
        with pytest.raises(BoardError):
            board.add_phase("a")

    def test_task_id_duplicado(self):
        board = Board.new("x")
        board.add_task("a", "t", task_id="t1")
        with pytest.raises(BoardError):
            board.add_task("a", "outra", task_id="t1")

    def test_status_invalido(self):
        board = Board.new("x")
        with pytest.raises(BoardError):
            board.add_task("a", "t", status="voando")


# ── dependências e próximo passo ──────────────────────────────────────────

class TestDependencias:
    def test_next_pending_respeita_dependencia(self):
        board = Board.new("x")
        t1 = board.add_task("a", "primeira", task_id="t1")
        t2 = board.add_task("a", "segunda", task_id="t2", depende_de=["t1"])

        assert board.next_pending().id == "t1"
        board.mark_task("t1", TASK_CONCLUIDA)
        assert board.next_pending().id == "t2"

    def test_dependencia_nao_concluida_bloqueia(self):
        board = Board.new("x")
        board.add_task("a", "primeira", task_id="t1")
        board.add_task("a", "segunda", task_id="t2", depende_de=["t1"])

        board.mark_task("t1", TASK_FALHOU)
        assert board.next_pending() is None

    def test_dependencia_de_task_inexistente(self):
        board = Board.new("x")
        board.add_task("a", "t", depende_de=["t99"])
        assert board.next_pending() is None
        assert any("não existe" in e for e in board.validate())


# ── mutação e resultado ───────────────────────────────────────────────────

class TestMutacao:
    def test_timestamps(self):
        board = Board.new("x")
        task = board.add_task("a", "t")
        board.mark_task(task.id, TASK_EM_ANDAMENTO)
        assert board.task(task.id).iniciada_em
        board.mark_task(task.id, TASK_CONCLUIDA)
        assert board.task(task.id).concluida_em

    def test_record_task_result(self, tmp_path):
        board = Board.new("x")
        task = board.add_task("a", "t")
        arquivo = tmp_path / "saida.txt"
        arquivo.write_text("ok", encoding="utf-8")

        board.record_task_result(
            task.id, TASK_CONCLUIDA,
            resumo="feito",
            tokens_in=10, tokens_out=5, duracao_s=1.5,
            artefatos=[str(arquivo)],
            decisoes=["usei X"],
        )
        saved = board.task(task.id)
        assert saved.status == TASK_CONCLUIDA
        assert saved.resumo == "feito"
        assert saved.tokens_in == 10
        assert saved.total_tokens == 15
        assert saved.artefatos[0]["path"] == str(arquivo)
        assert saved.artefatos[0]["mtime"] is not None
        assert saved.decisoes == ["usei X"]

    def test_artefato_duplicado_atualiza(self):
        board = Board.new("x")
        task = board.add_task("a", "t")
        board.add_artifact(task.id, "a.txt", mtime=1.0)
        board.add_artifact(task.id, "a.txt", mtime=2.0)
        assert len(board.task(task.id).artefatos) == 1
        assert board.task(task.id).artefatos[0]["mtime"] == 2.0

    def test_progresso(self):
        board = Board.new("x")
        t1 = board.add_task("a", "1")
        t2 = board.add_task("a", "2")
        board.add_task("a", "3")
        board.mark_task(t1.id, TASK_CONCLUIDA)
        board.mark_task(t2.id, TASK_FALHOU)

        progress = board.progress()
        assert progress == {
            "total": 3, "pendentes": 1, "em_andamento": 0,
            "concluidas": 1, "falhas": 1, "puladas": 0, "bloqueadas": 0,
        }
        assert board.is_complete() is False

    def test_complete(self):
        board = Board.new("x")
        t1 = board.add_task("a", "1")
        t2 = board.add_task("a", "2")
        board.mark_task(t1.id, TASK_CONCLUIDA)
        board.mark_task(t2.id, TASK_PULADA)
        assert board.is_complete() is True

    def test_set_status(self):
        board = Board.new("x")
        board.set_status("em_andamento")
        assert board.status == "em_andamento"
        with pytest.raises(BoardError):
            board.set_status("dormindo")


# ── validação ─────────────────────────────────────────────────────────────

class TestValidate:
    def test_board_vazio(self):
        errors = Board.new("").validate()
        assert "objetivo vazio" in errors
        assert "quadro sem fases" in errors

    def test_board_valido(self):
        board = Board.new("x")
        board.add_task("a", "t", resultado_esperado="ok")
        assert board.validate() == []

    def test_task_sem_titulo(self):
        board = Board.new("x")
        board.add_task("a", "t")
        board.task("t1").titulo = ""
        assert any("sem título" in e for e in board.validate())

    def test_id_duplicado_manual(self):
        board = Board.new("x")
        board.fases.append(PhaseState("a", [
            TaskState("t1", "um"), TaskState("t1", "dois"),
        ]))
        assert any("id duplicado" in e for e in board.validate())

    def test_auto_dependencia(self):
        board = Board.new("x")
        board.add_task("a", "t", task_id="t1", depende_de=["t1"])
        assert any("depende de si mesma" in e for e in board.validate())

    def test_max_tasks(self):
        board = Board.new("x", orcamento={"max_tasks": 1})
        board.add_task("a", "1")
        board.add_task("a", "2")
        assert any("max_tasks" in e for e in board.validate())

    def test_orcamento_negativo(self):
        board = Board.new("x", orcamento={"max_replans": -1})
        board.add_task("a", "t")
        assert any("max_replans" in e for e in board.validate())

    def test_status_invalido_no_dict(self):
        board = Board.new("x")
        board.add_task("a", "t")
        board.task("t1").status = "explodindo"
        assert any("status inválido" in e for e in board.validate())


# ── serialização ──────────────────────────────────────────────────────────

class TestSerializacao:
    def test_roundtrip(self):
        board = Board.new(
            "objetivo", fluxo="web", perfil="build",
            entrega={"formato": "markdown"}, sessao_id=7,
            meta={"modelos": {"worker": "x"}},
        )
        task = board.add_task(
            "fase", "título", resultado_esperado="ok",
            checagem={"tipo": "http"}, agente="dev_helper",
            depende_de=[],
        )
        board.record_task_result(
            task.id, TASK_CONCLUIDA, resumo="r",
            artefatos=["a.py"], decisoes=["d"],
        )

        data = board.to_dict()
        restored = Board.from_dict(data)

        assert restored.to_dict() == data
        assert restored.task("t1").checagem == {"tipo": "http"}
        assert restored.task("t1").agente == "dev_helper"
        assert restored.task("t1").artefatos[0]["path"] == "a.py"
        assert restored.entrega == {"formato": "markdown"}
        assert restored.sessao_id == 7

    def test_from_dict_tolerante(self):
        board = Board.from_dict({"objetivo": "x"})
        assert board.id
        assert board.fases == []
        assert board.status == "criada"

    def test_from_dict_invalido(self):
        with pytest.raises(BoardError):
            Board.from_dict(["não é dict"])

    def test_artefatos_string_normalizados(self):
        task = TaskState("t1", "t", artefatos=["a.txt", {"path": "b.txt"}])
        assert task.artefatos == [
            {"path": "a.txt", "mtime": None},
            {"path": "b.txt"},
        ]


# ── store ─────────────────────────────────────────────────────────────────

@pytest.fixture
def store(tmp_path):
    return BoardStore(tmp_path / "runs")


class TestBoardStore:
    def test_create_e_load(self, store):
        board = Board.new("meu objetivo")
        path = store.create(board)

        assert path.exists()
        loaded = store.load(board.id)
        assert loaded.objetivo == "meu objetivo"
        assert loaded.id == board.id

    def test_criacao_e_atomica(self, store):
        board = Board.new("x")
        store.create(board)
        run_dir = store.run_dir(board.id)
        assert list(run_dir.glob(".board.*.tmp")) == []

    def test_save_preserva_e_atualiza(self, store):
        board = Board.new("x")
        store.create(board)
        board.add_task("a", "t")
        store.save(board)
        assert len(store.load(board.id).tasks()) == 1

    def test_colisao_de_id_recebe_sufixo(self, store):
        b1 = Board.new("x", run_id="run-fixo")
        store.create(b1)
        b2 = Board.new("x", run_id="run-fixo")
        store.create(b2)
        assert b2.id == "run-fixo_2"
        assert store.load("run-fixo_2").id == "run-fixo_2"
        assert len(store.list_runs()) == 2

    def test_list_runs(self, store):
        b1 = Board.new("um", run_id="a")
        b2 = Board.new("dois", run_id="b")
        store.create(b1)
        store.create(b2)
        b1.add_task("f", "t")
        store.save(b1)

        runs = store.list_runs()
        assert {r["id"] for r in runs} == {"a", "b"}
        summary_a = next(r for r in runs if r["id"] == "a")
        assert summary_a["total"] == 1

    def test_latest(self, store):
        store.create(Board.new("um", run_id="a"))
        store.create(Board.new("dois", run_id="b"))
        assert store.latest().id == "b"

    def test_load_inexistente(self, store):
        with pytest.raises(BoardNotFound):
            store.load("nao-existe")

    def test_run_id_invalido(self, store):
        with pytest.raises(BoardError):
            store.run_dir("../fora")
        with pytest.raises(BoardError):
            store.run_dir("a/b")

    def test_delete(self, store):
        board = Board.new("x", run_id="a")
        store.create(board)
        store.delete("a")
        assert not store.run_dir("a").exists()
        with pytest.raises(BoardNotFound):
            store.delete("a")

    def test_delete_bloqueado_por_lock(self, store):
        board = Board.new("x", run_id="a")
        store.create(board)
        lock = store.lock("a")
        lock.acquire()
        try:
            with pytest.raises(BoardLocked):
                store.delete("a")
        finally:
            lock.release()
        store.delete("a")

    def test_eventos(self, store):
        board = Board.new("x", run_id="a")
        store.create(board)
        store.append_event("a", "task_iniciada", task="t1")
        events = store.read_events("a")
        assert events[0]["tipo"] == "run_criada"
        assert events[1] == {
            "ts": events[1]["ts"], "tipo": "task_iniciada", "task": "t1",
        }

    def test_eventos_ignoram_linha_invalida(self, store):
        board = Board.new("x", run_id="a")
        store.create(board)
        with store.events_path("a").open("a", encoding="utf-8") as f:
            f.write("{quebrado\n")
        assert len(store.read_events("a")) == 1

    def test_evento_sem_run(self, store):
        with pytest.raises(BoardNotFound):
            store.append_event("nao", "x")


# ── trava ─────────────────────────────────────────────────────────────────

class TestRunLock:
    def test_acquire_e_release(self, store):
        board = Board.new("x", run_id="a")
        store.create(board)

        lock = store.lock("a")
        lock.acquire()
        info = lock.info()
        assert info["pid"] > 0
        assert info["ativo"] is True
        assert lock.release() is True
        assert lock.info() is None

    def test_segunda_instancia_bloqueia(self, store):
        board = Board.new("x", run_id="a")
        store.create(board)

        first = store.lock("a").acquire()
        try:
            with pytest.raises(BoardLocked):
                store.lock("a").acquire()
        finally:
            first.release()

        # liberou → pode pegar de novo
        second = store.lock("a").acquire()
        second.release()

    def test_force_sobrescreve(self, store):
        board = Board.new("x", run_id="a")
        store.create(board)
        store.lock("a").acquire()

        forced = store.lock("a", force=True).acquire()
        assert forced.info()["ativo"] is True
        forced.release()

    def test_release_sem_acquire(self, store):
        board = Board.new("x", run_id="a")
        store.create(board)
        assert store.lock("a").release() is False

    def test_lock_orfao_marcado_stale(self, store):
        board = Board.new("x", run_id="a")
        store.create(board)
        path = store.lock_path("a")
        path.write_text(json.dumps({
            "run_id": "a", "pid": 0, "host": __import__("socket").gethostname(),
        }), encoding="utf-8")

        info = store.lock("a").info()
        assert info["stale"] is True
        assert info["ativo"] is False

    def test_context_manager(self, store):
        board = Board.new("x", run_id="a")
        store.create(board)
        with store.lock("a"):
            assert store.lock_path("a").exists()
        assert not store.lock_path("a").exists()
