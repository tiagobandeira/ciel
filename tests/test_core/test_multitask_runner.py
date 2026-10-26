"""
tests/test_core/test_multitask_runner.py

Cobre `multitask/runner.py` com `run_agent` mockado:
  - ordem, status, dependências e contexto por task
  - falha, pausa, orçamento, interrupção
  - artefatos automáticos, persona por task, model_client
  - trava por execução e eventos
"""

import json
import os
import socket
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from agent_loop import AgentResult
from agent_loader import load_agent
from llm.client import ChatResult
from board import (
    RUN_CONCLUIDA,
    RUN_FALHOU,
    RUN_PAUSADA,
    TASK_CONCLUIDA,
    TASK_FALHOU,
    TASK_PENDENTE,
    Board,
    BoardLocked,
    BoardStore,
)
from multitask.runner import collect_artifacts, run_board


AGENT = {
    "id": "general",
    "name": "General",
    "description": "teste",
    "system_prompt": "teste",
    "allowed_tools": None,
    "allowed_mcp_servers": [],
}


def make_board(*, three_tasks: bool = False) -> Board:
    board = Board.new("objetivo de teste", run_id="run-1", fluxo="teste")
    board.add_task(
        "fase-1", "primeira",
        objetivo="fazer a primeira", acoes=["passo 1"],
        resultado_esperado="r1", task_id="t1",
    )
    board.add_task(
        "fase-2", "segunda",
        objetivo="fazer a segunda", acoes=["passo 2"],
        resultado_esperado="r2", task_id="t2", depende_de=["t1"],
    )
    if three_tasks:
        board.add_task(
            "fase-3", "terceira",
            objetivo="fazer a terceira", acoes=["passo 3"],
            resultado_esperado="r3", task_id="t3", depende_de=["t2"],
        )
    return board


def done(message: str, tokens_in: int = 10, tokens_out: int = 5) -> AgentResult:
    return AgentResult(
        "done", message, tokens_in=tokens_in, tokens_out=tokens_out, steps=1
    )


def error(message: str) -> AgentResult:
    return AgentResult("error", message, tokens_in=1, tokens_out=1, steps=1)


def make_fake(responses, calls=None, on_call=None):
    queue = list(responses)
    counter = {"n": 0}

    def fake(prompt, tools, schema, model, agent_info, **kwargs):
        counter["n"] += 1
        if calls is not None:
            calls.append({
                "prompt": prompt, "model": model,
                "tools": tools, "schema": schema,
                "agent_info": agent_info, "kwargs": kwargs,
            })
        if on_call is not None:
            on_call(counter["n"])
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, BaseException):
            raise item
        return item

    return fake


@pytest.fixture
def store(tmp_path):
    return BoardStore(tmp_path / "runs")


@pytest.fixture
def workspace(tmp_path):
    path = tmp_path / "ws"
    path.mkdir()
    return path


class TestExecucaoFeliz:
    def test_ordem_status_e_contexto(self, store, workspace):
        calls = []
        board = make_board()

        with patch(
            "multitask.runner.run_agent",
            side_effect=make_fake([done("ok1"), done("ok2")], calls=calls),
        ):
            result = run_board(
                board, {}, [], AGENT,
                store=store, workspace_root=workspace,
            )

        assert result.status == RUN_CONCLUIDA
        assert result.tasks_ok == ["t1", "t2"]
        assert result.tokens_in == 20
        assert result.tokens_out == 10

        saved = store.load(board.id)
        assert saved.status == RUN_CONCLUIDA
        assert saved.task("t1").status == TASK_CONCLUIDA
        assert saved.task("t2").status == TASK_CONCLUIDA
        assert saved.task("t1").resumo == "ok1"

        # contexto da primeira task
        assert "fazer a primeira" in calls[0]["prompt"]
        assert "passo 1" in calls[0]["prompt"]
        assert calls[0]["kwargs"]["history"] == []
        assert calls[0]["kwargs"]["max_steps"] == 8

        # a segunda vê o resumo da dependência, não o histórico bruto
        assert "ok1" in calls[1]["prompt"]
        assert "## Dependências concluídas" in calls[1]["prompt"]

    def test_eventos_gravados(self, store, workspace):
        board = make_board()
        with patch("multitask.runner.run_agent", side_effect=make_fake([done("ok")])):
            run_board(board, {}, [], AGENT, store=store, workspace_root=workspace)

        eventos = [e["tipo"] for e in store.read_events(board.id)]
        assert "run_iniciada" in eventos
        assert "fase_iniciada" in eventos
        assert "task_iniciada" in eventos
        assert "task_concluida" in eventos
        assert "fase_concluida" in eventos
        assert "run_encerrada" in eventos

    def test_meta_de_tokens_e_duracao(self, store, workspace):
        board = make_board()
        with patch("multitask.runner.run_agent", side_effect=make_fake([done("ok")])):
            run_board(board, {}, [], AGENT, store=store, workspace_root=workspace)

        assert board.meta["tokens_in"] == 20
        assert board.meta["tokens_out"] == 10
        assert board.meta["duracao_s"] >= 0

    def test_tokens_do_planejador_somam_no_relatorio(self, store, workspace):
        board = make_board()
        board.meta["planner_tokens_in"] = 100
        board.meta["planner_tokens_out"] = 50

        with patch("multitask.runner.run_agent", side_effect=make_fake([done("ok")])):
            result = run_board(board, {}, [], AGENT, store=store, workspace_root=workspace)

        # RunResult devolve a execução; o relatório soma planejamento
        assert result.tokens_in == 20
        assert result.tokens_out == 10
        assert board.meta["tokens_in"] == 120
        assert board.meta["tokens_out"] == 60

    def test_model_client_repassado(self, store, workspace):
        sentinel = object()
        calls = []
        board = make_board()
        with patch(
            "multitask.runner.run_agent",
            side_effect=make_fake([done("ok")], calls=calls),
        ):
            run_board(
                board, {}, [], AGENT,
                store=store, model_client=sentinel, workspace_root=workspace,
            )
        assert all(c["kwargs"]["model_client"] is sentinel for c in calls)

    def test_max_steps_e_budget_da_task(self, store, workspace):
        board = Board.new("x", run_id="run-budget")
        board.add_task("f", "t", acoes=["a"], max_steps=5)
        calls = []
        with patch(
            "multitask.runner.run_agent",
            side_effect=make_fake([done("ok")], calls=calls),
        ):
            run_board(board, {}, [], AGENT, store=store, workspace_root=workspace)

        assert calls[0]["kwargs"]["max_steps"] == 5
        assert calls[0]["kwargs"]["budget_tokens"] == 100000

    def test_metricas_por_task(self, store, workspace):
        board = make_board()
        with patch(
            "multitask.runner.run_agent",
            side_effect=make_fake([done("ok")]),
        ):
            run_board(board, {}, [], AGENT, store=store, workspace_root=workspace)

        metricas = board.meta.get("metricas", {}).get("t1")
        assert metricas is not None
        assert metricas["steps"] == 1
        assert metricas["tokens_in"] == 10
        assert metricas["tokens_out"] == 5
        assert "context_peak_chars" in metricas
        assert "prompt_chars" in metricas

    def test_parallel_readonly_roda_em_threads(self, store, workspace):
        import threading
        from agent_loop import AgentResult

        barrier = threading.Barrier(2)

        def fake_agent(*args, **kwargs):
            barrier.wait(timeout=5)
            return AgentResult("done", "ok", tokens_in=1, tokens_out=1)

        board = Board.new("x", run_id="run-parallel")
        board.add_task(
            "f", "a", acoes=["a"], tools=["calculator"], parallel=True,
        )
        board.add_task(
            "f", "b", acoes=["b"], tools=["calculator"], parallel=True,
        )
        with patch("multitask.runner.run_agent", side_effect=fake_agent):
            result = run_board(
                board, {}, [], AGENT,
                store=store, workspace_root=workspace, max_parallel=2,
            )

        assert result.status == RUN_CONCLUIDA
        assert len(result.tasks_ok) == 2
        assert board.task("t1").status == TASK_CONCLUIDA
        assert board.task("t2").status == TASK_CONCLUIDA
        sub = store.run_dir(board.id) / "subagents" / "t1.json"
        assert sub.exists()
        assert '"parallel": true' in sub.read_text(encoding="utf-8")

    def test_modelo_por_task(self, store, workspace):
        board = Board.new("x", run_id="run-modelo")
        board.add_task("f", "t", acoes=["a"], modelo="meu-modelo")
        calls = []
        with patch(
            "multitask.runner.run_agent",
            side_effect=make_fake([done("ok")], calls=calls),
        ):
            run_board(board, {}, [], AGENT, store=store, workspace_root=workspace)

        assert calls[0]["model"] == "meu-modelo"

    def test_perfil_por_task_cria_cliente(self, store, workspace):
        sentinel = object()
        spec = type("Spec", (), {
            "is_local": False,
            "model": "modelo-nuvem",
            "client": lambda self: sentinel,
        })()
        roles = type("Roles", (), {"orchestrator": spec})()
        board = Board.new("x", run_id="run-perfil")
        board.add_task("f", "t", acoes=["a"], perfil="nuvem")
        calls = []
        with patch("llm.roles.load_roles", return_value=roles), patch(
            "multitask.runner.run_agent",
            side_effect=make_fake([done("ok")], calls=calls),
        ):
            run_board(board, {}, [], AGENT, store=store, workspace_root=workspace)

        assert calls[0]["kwargs"]["model_client"] is sentinel
        assert calls[0]["kwargs"]["profile"] == "nuvem"

    def test_pular_se_ok_nao_chama_modelo(self, store, workspace):
        (workspace / "pronto.txt").write_text("ok", encoding="utf-8")
        board = Board.new("x", run_id="run-pular")
        board.add_task(
            "f", "t", acoes=["a"],
            checagem={"tipo": "arquivo", "path": "pronto.txt"},
            pular_se_ok=True,
        )

        with patch("multitask.runner.run_agent") as fake:
            result = run_board(
                board, {}, [], AGENT,
                store=store, workspace_root=workspace,
            )

        fake.assert_not_called()
        assert result.status == RUN_CONCLUIDA
        task = board.task("t1")
        assert task.status == TASK_CONCLUIDA
        assert "pulada" in task.resumo
        assert board.meta["metricas"]["t1"]["pulada"] is True

    def test_revisao_de_fase_no_nuvem(self, store, workspace):
        from multitask.reviewer import ReviewResult

        board = Board.new("x", run_id="run-review")
        board.add_task("f", "t", acoes=["a"])
        calls = []
        with patch(
            "multitask.runner.run_agent",
            side_effect=make_fake([done("ok")], calls=calls),
        ), patch(
            "multitask.runner.review_phase",
            return_value=ReviewResult(
                resumo="ok", applied=["adicionada: testes"],
                tokens_in=7, tokens_out=3,
            ),
        ) as review:
            result = run_board(
                board, {}, [], AGENT,
                store=store, workspace_root=workspace,
                model_client=object(), profile="nuvem",
                revisar_fases=True,
            )

        review.assert_called_once()
        assert result.tokens_in >= 7
        assert result.tokens_out >= 3

    def test_persona_por_task(self, store, workspace):
        board = Board.new("x", run_id="run-persona")
        board.add_task("f", "t", agente="frontend", acoes=["a"])
        persona = {**AGENT, "id": "frontend"}
        calls = []

        with patch("multitask.runner.load_agent", return_value=persona) as load, \
             patch(
                 "multitask.runner.run_agent",
                 side_effect=make_fake([done("ok")], calls=calls),
             ):
            run_board(board, {}, [], AGENT, store=store, workspace_root=workspace)

        load.assert_called_once_with("frontend", profile="local")
        assert calls[0]["agent_info"] is persona

    def test_tools_da_task_filtram_schema(self, store, workspace):
        board = Board.new("x", run_id="run-tools")
        board.add_task(
            "f", "t", acoes=["a"],
            tools=["read_file"],
        )
        tools = {
            "read_file": {"fn": lambda: "", "description": "lê"},
            "write_file": {"fn": lambda: "", "description": "escreve"},
        }
        schema = [{"name": "read_file"}, {"name": "write_file"}]
        calls = []

        with patch(
            "multitask.runner.run_agent",
            side_effect=make_fake([done("ok")], calls=calls),
        ):
            run_board(
                board, tools, schema, AGENT,
                store=store, workspace_root=workspace,
            )

        assert set(calls[0]["tools"]) == {"read_file"}
        assert [item["name"] for item in calls[0]["schema"]] == ["read_file"]

    def test_contexto_build_nao_manda_usar_secondary(self):
        from multitask.runner import build_task_context

        board = Board.new("x", run_id="run-contexto")
        task = board.add_task("f", "t", acoes=["a"])

        local = build_task_context(board, task, "f", profile="local")
        build = build_task_context(board, task, "f", profile="build")

        assert "Se usar secondary_model" in local
        assert "secondary_model não existe" in build
        assert "Se usar secondary_model" not in build


class TestFalhaEPausa:
    def test_falha_interrompe_e_preserva_pendentes(self, store, workspace):
        board = make_board(three_tasks=True)
        with patch(
            "multitask.runner.run_agent",
            side_effect=make_fake([done("ok1"), error("quebrou")]),
        ):
            result = run_board(
                board, {}, [], AGENT,
                store=store, workspace_root=workspace,
            )

        assert result.status == RUN_FALHOU
        assert result.tasks_ok == ["t1"]
        assert result.tasks_fail == ["t2"]
        assert result.stopped_at == "t2"

        saved = store.load(board.id)
        assert saved.task("t1").status == TASK_CONCLUIDA
        assert saved.task("t2").status == TASK_FALHOU
        assert saved.task("t3").status == TASK_PENDENTE
        assert "Falhas" in result.message
        assert "Pendências" in result.message

    def test_pausa_pedida_entre_tasks(self, store, workspace):
        board = make_board()
        chamadas = {"n": 0}

        def should_pause():
            chamadas["n"] += 1
            return chamadas["n"] > 1

        with patch("multitask.runner.run_agent", side_effect=make_fake([done("ok")])):
            result = run_board(
                board, {}, [], AGENT,
                store=store, should_pause=should_pause,
                workspace_root=workspace,
            )

        assert result.status == RUN_PAUSADA
        saved = store.load(board.id)
        assert saved.task("t1").status == TASK_CONCLUIDA
        assert saved.task("t2").status == TASK_PENDENTE
        assert "pausa" in result.motivo

    def test_orcamento_de_tokens_pausa(self, store, workspace):
        board = make_board()
        board.orcamento["max_tokens"] = 10

        with patch(
            "multitask.runner.run_agent",
            side_effect=make_fake([done("ok", tokens_in=10, tokens_out=5)]),
        ):
            result = run_board(board, {}, [], AGENT, store=store, workspace_root=workspace)

        assert result.status == RUN_PAUSADA
        assert "orçamento" in result.motivo
        assert store.load(board.id).task("t2").status == TASK_PENDENTE

    def test_keyboard_interrupt_pausa_e_reseta_task(self, store, workspace):
        board = make_board()
        with patch(
            "multitask.runner.run_agent",
            side_effect=make_fake([KeyboardInterrupt()]),
        ):
            result = run_board(board, {}, [], AGENT, store=store, workspace_root=workspace)

        assert result.status == RUN_PAUSADA
        saved = store.load(board.id)
        assert saved.task("t1").status == TASK_PENDENTE
        assert saved.task("t1").erro == "interrompida"
        assert not store.lock_path(board.id).exists()

    def test_erro_interno_marca_falha(self, store, workspace):
        board = make_board()
        with patch(
            "multitask.runner.run_agent",
            side_effect=RuntimeError("boom"),
        ):
            result = run_board(board, {}, [], AGENT, store=store, workspace_root=workspace)

        assert result.status == RUN_FALHOU
        assert "boom" in board.meta.get("erro", "")


class TestArtefatos:
    def test_arquivo_criado_durante_a_task_entra_no_quadro(self, store, workspace):
        board = make_board()
        target = workspace / "novo.txt"

        def create_file(_n):
            target.write_text("conteúdo", encoding="utf-8")

        with patch(
            "multitask.runner.run_agent",
            side_effect=make_fake([done("ok")], on_call=create_file),
        ):
            run_board(board, {}, [], AGENT, store=store, workspace_root=workspace)

        artifacts = board.task("t1").artefatos
        assert any(item["path"] == "novo.txt" for item in artifacts)
        assert "novo.txt" in store.load(board.id).task("t1").artefatos[0]["path"]

    def test_ignora_lixo(self, workspace):
        (workspace / ".git").mkdir()
        (workspace / ".git" / "config").write_text("x", encoding="utf-8")
        (workspace / "data" / "runs").mkdir(parents=True)
        (workspace / "data" / "runs" / "board.json").write_text("{}", encoding="utf-8")
        (workspace / "__pycache__").mkdir()
        (workspace / "__pycache__" / "x.pyc").write_text("x", encoding="utf-8")

        inicio = time.time()
        (workspace / "real.txt").write_text("ok", encoding="utf-8")

        found = collect_artifacts(workspace, inicio)
        assert [item["path"] for item in found] == ["real.txt"]

    def test_arquivo_antigo_nao_entra(self, workspace):
        antigo = workspace / "antigo.txt"
        antigo.write_text("x", encoding="utf-8")
        old = time.time() - 100
        os.utime(antigo, (old, old))

        found = collect_artifacts(workspace, time.time())
        assert found == []


class TestTrava:
    def test_trava_ativa_bloqueia(self, store, workspace):
        board = make_board()
        store.create(board)
        lock = store.lock(board.id).acquire()
        try:
            with pytest.raises(BoardLocked):
                run_board(board, {}, [], AGENT, store=store, workspace_root=workspace)
        finally:
            lock.release()

    def test_trava_orfa_e_recuperada(self, store, workspace):
        board = make_board()
        store.create(board)
        store.lock_path(board.id).write_text(json.dumps({
            "run_id": board.id,
            "pid": 0,
            "host": socket.gethostname(),
        }), encoding="utf-8")

        with patch("multitask.runner.run_agent", side_effect=make_fake([done("ok")])):
            result = run_board(board, {}, [], AGENT, store=store, workspace_root=workspace)

        assert result.status == RUN_CONCLUIDA
        assert not store.lock_path(board.id).exists()


class TestIntegracaoComRunAgentReal:
    """
    Sem patch de run_agent: valida a assinatura, o system prompt, a persona
    por task e o parse de `done` com um cliente de modelo falso.
    """

    def test_persona_por_task_com_run_agent_real(self, store, workspace):
        class FakeClient:
            def chat(self, messages, *, model=None, **kwargs):
                return ChatResult(
                    '{"done": true, "message": "feito de verdade"}', 4, 2
                )

        board = Board.new("integração", run_id="run-real")
        board.add_task(
            "f", "tarefa", objetivo="fazer", acoes=["executar"],
            agente="dev_helper",
        )

        result = run_board(
            board, {}, [], load_agent("general"),
            store=store,
            model="",
            model_client=FakeClient(),
            workspace_root=workspace,
        )

        assert result.status == RUN_CONCLUIDA
        assert result.tasks_ok == ["t1"]
        assert (result.tokens_in, result.tokens_out) == (4, 2)
        assert "feito de verdade" in result.message
        assert store.load(board.id).task("t1").status == TASK_CONCLUIDA


class TestChecagensECorrecao:
    def _board(self, checagem, *, max_corrections: int = 3) -> Board:
        board = Board.new("checagem", run_id="run-check")
        board.add_task("f", "tarefa", acoes=["a"], checagem=checagem)
        board.orcamento["max_correcoes_por_task"] = max_corrections
        return board

    def test_checagem_ok_na_primeira(self, store, workspace):
        (workspace / "ok.txt").write_text("ok", encoding="utf-8")
        board = self._board({"tipo": "arquivo", "path": "ok.txt"})

        with patch("multitask.runner.run_agent", side_effect=make_fake([done("feito")])):
            result = run_board(board, {}, [], AGENT, store=store, workspace_root=workspace)

        assert result.status == RUN_CONCLUIDA
        task = board.task("t1")
        assert task.checagem_ok is True
        assert "existe" in task.checagem_resumo
        assert task.correcoes == 0
        assert task.tentativas == 1

    def test_falha_abre_correcao_e_depois_conclui(self, store, workspace):
        board = self._board({"tipo": "arquivo", "path": "novo.txt"})
        calls = []

        def criar_na_segunda(n):
            calls.append(n)
            if n >= 2:
                (workspace / "novo.txt").write_text("ok", encoding="utf-8")

        with patch(
            "multitask.runner.run_agent",
            side_effect=make_fake([done("tentativa 1"), done("tentativa 2")],
                                  on_call=criar_na_segunda),
        ):
            result = run_board(board, {}, [], AGENT, store=store, workspace_root=workspace)

        assert result.status == RUN_CONCLUIDA
        task = board.task("t1")
        assert task.checagem_ok is True
        assert task.correcoes == 1
        assert task.tentativas == 2
        assert task.resumo == "tentativa 2"

        eventos = [e["tipo"] for e in store.read_events(board.id)]
        assert "checagem_falhou" in eventos
        assert "correcao_iniciada" in eventos
        assert "task_corrigida" in eventos
        assert "task_concluida" in eventos

    def test_correcao_recebe_erro_e_arquivos(self, store, workspace):
        (workspace / "index.html").write_text("conteúdo atual", encoding="utf-8")
        board = self._board(
            {"tipo": "arquivo", "path": "index.html", "contem": "esperado"}
        )
        prompts = []

        def fake(prompt, tools, schema, model, agent_info, **kwargs):
            prompts.append(prompt)
            if len(prompts) == 2:
                (workspace / "index.html").write_text(
                    "conteúdo esperado", encoding="utf-8"
                )
            return done(f"tentativa {len(prompts)}")

        with patch("multitask.runner.run_agent", side_effect=fake):
            result = run_board(board, {}, [], AGENT, store=store, workspace_root=workspace)

        assert result.status == RUN_CONCLUIDA
        assert "Correção automática" in prompts[1]
        assert "não contém" in prompts[1]
        assert "conteúdo atual" in prompts[1]

    def test_correcoes_esgotadas_falham(self, store, workspace):
        board = self._board(
            {"tipo": "arquivo", "path": "nunca.txt"}, max_corrections=1,
        )
        with patch("multitask.runner.run_agent", side_effect=make_fake([done("ok")])):
            result = run_board(board, {}, [], AGENT, store=store, workspace_root=workspace)

        assert result.status == RUN_FALHOU
        task = board.task("t1")
        assert task.status == TASK_FALHOU
        assert task.checagem_ok is False
        assert task.correcoes == 1
        assert task.tentativas == 2
        assert "checagem falhou" in task.erro
        assert "Falhas" in result.message

    def test_erro_identico_para_antes_do_limite(self, store, workspace):
        board = self._board(
            {"tipo": "arquivo", "path": "nunca.txt"}, max_corrections=5,
        )
        with patch("multitask.runner.run_agent", side_effect=make_fake([done("ok")])):
            result = run_board(board, {}, [], AGENT, store=store, workspace_root=workspace)

        task = board.task("t1")
        assert result.status == RUN_FALHOU
        assert task.correcoes == 1
        assert task.tentativas == 2
        assert "mesmo erro" in task.erro
        assert "mesmo erro" in result.message or "mesmo erro" in task.erro

    def test_sem_checagem_nao_marca_verificado(self, store, workspace):
        board = Board.new("sem check", run_id="run-sem-check")
        board.add_task("f", "tarefa", acoes=["a"])

        with patch("multitask.runner.run_agent", side_effect=make_fake([done("ok")])):
            run_board(board, {}, [], AGENT, store=store, workspace_root=workspace)

        task = board.task("t1")
        assert task.checagem_ok is None
        assert task.checagem_resumo == "sem checagem automática"

    def test_orcamento_esgotado_impede_correcao(self, store, workspace):
        board = self._board({"tipo": "arquivo", "path": "nunca.txt"})
        board.orcamento["max_tokens"] = 5

        with patch(
            "multitask.runner.run_agent",
            side_effect=make_fake([done("ok", tokens_in=10, tokens_out=5)]),
        ):
            result = run_board(board, {}, [], AGENT, store=store, workspace_root=workspace)

        task = board.task("t1")
        assert result.status == RUN_FALHOU
        assert task.correcoes == 0
        assert task.tentativas == 1
        assert "orçamento" in task.erro

    def test_limit_com_checagem_ok_aceita_task(self, store, workspace):
        (workspace / "pronto.txt").write_text("ok", encoding="utf-8")
        board = self._board({"tipo": "arquivo", "path": "pronto.txt"})
        limite = AgentResult(
            "limit", "Limite de steps", tokens_in=10, tokens_out=5, steps=9,
        )

        with patch("multitask.runner.run_agent", side_effect=make_fake([limite])):
            result = run_board(board, {}, [], AGENT, store=store, workspace_root=workspace)

        task = board.task("t1")
        assert result.status == RUN_CONCLUIDA
        assert task.status == TASK_CONCLUIDA
        assert task.checagem_ok is True
        assert "aceita pela checagem" in task.resumo
        eventos = [
            e for e in store.read_events(board.id)
            if e["tipo"] == "task_concluida"
        ]
        assert eventos and eventos[0].get("limite") is True

    def test_limit_com_checagem_falha_falha_task(self, store, workspace):
        board = self._board({"tipo": "arquivo", "path": "nunca.txt"})
        limite = AgentResult(
            "limit", "Limite de steps", tokens_in=10, tokens_out=5, steps=9,
        )

        with patch("multitask.runner.run_agent", side_effect=make_fake([limite])):
            result = run_board(board, {}, [], AGENT, store=store, workspace_root=workspace)

        assert result.status == RUN_FALHOU
        assert board.task("t1").status == TASK_FALHOU
