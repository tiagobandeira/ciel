"""
tests/test_core/test_multitask_planner.py

Cobre `multitask/planner.py`: validação do JSON do plano, montagem do
Board, retry com os erros, tokens e indisponibilidade do planejador.
"""

import json
from types import SimpleNamespace

import pytest

from llm.client import ChatResult
from multitask.planner import (
    PlannerUnavailable,
    generate_board,
    parse_plan,
)


def valid_plan() -> dict:
    return {
        "objetivo": "criar um site de teste",
        "entrega": {
            "formato": "bullets",
            "como_testar": "abra index.html",
        },
        "fases": [
            {
                "nome": "Estrutura",
                "tasks": [
                    {
                        "id": "t1",
                        "titulo": "criar arquivos base",
                        "objetivo": "criar index.html",
                        "acoes": ["criar index.html"],
                        "resultado_esperado": "index.html existe",
                        "checagem": {
                            "tipo": "arquivo",
                            "path": "index.html",
                        },
                        "agente": "dev_helper",
                        "depende_de": [],
                    },
                    {
                        "id": "t2",
                        "titulo": "conferir",
                        "objetivo": "conferir a página",
                        "acoes": ["listar a pasta"],
                        "resultado_esperado": "index.html tem <html>",
                        "checagem": {
                            "tipo": "arquivo",
                            "path": "index.html",
                            "contem": "<html",
                        },
                        "agente": "",
                        "depende_de": ["t1"],
                    },
                ],
            }
        ],
    }


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def chat(self, messages, **kwargs):
        self.calls.append([dict(m) for m in messages])
        item = (
            self.responses.pop(0)
            if len(self.responses) > 1
            else self.responses[0]
        )
        if isinstance(item, BaseException):
            raise item
        return ChatResult(item, tokens_in=10, tokens_out=5)


# ── parse_plan ────────────────────────────────────────────────────────────

class TestParsePlan:
    def test_plano_valido(self):
        board, errors = parse_plan(
            valid_plan(), objetivo_usuario="um site",
        )
        assert errors == []
        assert board is not None
        assert board.fluxo == "plano"
        assert board.perfil == ""
        assert board.entrega["formato"] == "bullets"
        assert board.entrega["como_testar"] == "abra index.html"
        assert board.meta["planner"] is True

        tasks = board.tasks()
        assert [t.id for t in tasks] == ["t1", "t2"]
        assert tasks[0].agente == "dev_helper"
        assert tasks[0].checagem == {
            "tipo": "arquivo", "path": "index.html",
        }
        assert tasks[1].depende_de == ["t1"]
        assert board.validate() == []

    def test_tools_e_max_steps_da_task(self):
        plan = valid_plan()
        plan["fases"][0]["tasks"][0]["tools"] = ["read_file", "write_file"]
        plan["fases"][0]["tasks"][0]["max_steps"] = 7
        board, errors = parse_plan(plan, objetivo_usuario="x")
        assert errors == []
        task = board.task("t1")
        assert task.tools == ["read_file", "write_file"]
        assert task.max_steps == 7

    def test_tools_default_por_tipo(self):
        plan = valid_plan()
        board, errors = parse_plan(plan, objetivo_usuario="x")
        assert errors == []
        # t1 cria arquivo => preset de escrita; t2 só lê => leitura
        assert "write_file" in board.task("t1").tools
        assert "read_file" in board.task("t2").tools

    def test_max_steps_invalido(self):
        plan = valid_plan()
        plan["fases"][0]["tasks"][0]["max_steps"] = 99
        _, errors = parse_plan(plan, objetivo_usuario="x")
        assert any("max_steps" in e for e in errors)

    def test_sem_resultado_esperado(self):
        plan = valid_plan()
        del plan["fases"][0]["tasks"][0]["resultado_esperado"]
        board, errors = parse_plan(plan, objetivo_usuario="x")
        assert board is None
        assert any("resultado_esperado" in e for e in errors)

    def test_id_duplicado(self):
        plan = valid_plan()
        plan["fases"][0]["tasks"][1]["id"] = "t1"
        _, errors = parse_plan(plan, objetivo_usuario="x")
        assert any("duplicado" in e for e in errors)

    def test_dependencia_futura(self):
        plan = valid_plan()
        plan["fases"][0]["tasks"][0]["depende_de"] = ["t2"]
        _, errors = parse_plan(plan, objetivo_usuario="x")
        assert any("inválida" in e for e in errors)

    def test_dependencia_por_titulo(self):
        plan = valid_plan()
        plan["fases"][0]["tasks"][1]["depende_de"] = ["criar arquivos base"]
        board, errors = parse_plan(plan, objetivo_usuario="x")
        assert errors == []
        assert board.task("t2").depende_de == ["t1"]

    def test_agente_invalido(self):
        plan = valid_plan()
        plan["fases"][0]["tasks"][0]["agente"] = "nao-existe"
        _, errors = parse_plan(plan, objetivo_usuario="x")
        assert any("agente" in e for e in errors)

    def test_checagem_invalida(self):
        plan = valid_plan()
        plan["fases"][0]["tasks"][0]["checagem"] = {"tipo": "magia"}
        _, errors = parse_plan(plan, objetivo_usuario="x")
        assert any("checagem" in e for e in errors)

    def test_pasta_com_checagem_de_arquivo(self):
        plan = valid_plan()
        task = plan["fases"][0]["tasks"][0]
        task["titulo"] = "criar pasta do projeto"
        task["acoes"] = ["criar pasta data/user/calculadora"]
        task["checagem"] = {
            "tipo": "arquivo", "path": "data/user/calculadora",
        }
        _, errors = parse_plan(plan, objetivo_usuario="x")
        assert any("diretorio" in e for e in errors)

    def test_pasta_com_checagem_de_diretorio(self):
        plan = valid_plan()
        task = plan["fases"][0]["tasks"][0]
        task["titulo"] = "criar pasta do projeto"
        task["acoes"] = ["criar pasta data/user/calculadora"]
        task["checagem"] = {
            "tipo": "diretorio", "path": "data/user/calculadora",
        }
        board, errors = parse_plan(plan, objetivo_usuario="x")
        assert errors == []
        assert board.task("t1").checagem["tipo"] == "diretorio"

    def test_acoes_demais(self):
        plan = valid_plan()
        plan["fases"][0]["tasks"][0]["acoes"] = [f"a{i}" for i in range(7)]
        _, errors = parse_plan(plan, objetivo_usuario="x")
        assert any("máximo" in e for e in errors)

    def test_sem_fases(self):
        _, errors = parse_plan({"objetivo": "x"}, objetivo_usuario="x")
        assert any("fases" in e for e in errors)

    def test_fase_sem_tasks(self):
        plan = valid_plan()
        plan["fases"][0]["tasks"] = []
        _, errors = parse_plan(plan, objetivo_usuario="x")
        assert any("sem tasks" in e for e in errors)

    def test_formato_invalido_cai_em_markdown(self):
        plan = valid_plan()
        plan["entrega"]["formato"] = "pdf"
        board, errors = parse_plan(plan, objetivo_usuario="x")
        assert errors == []
        assert board.entrega["formato"] == "markdown"

    def test_max_tasks_do_orcamento(self):
        plan = valid_plan()
        board, errors = parse_plan(
            plan,
            objetivo_usuario="x",
            orcamento={"max_tasks": 1},
        )
        assert board is None
        assert any("orçamento" in e for e in errors)

    def test_ids_gerados_quando_ausentes(self):
        plan = valid_plan()
        for task in plan["fases"][0]["tasks"]:
            task.pop("id")
        plan["fases"][0]["tasks"][1]["depende_de"] = []
        board, errors = parse_plan(plan, objetivo_usuario="x")
        assert errors == []
        assert [t.id for t in board.tasks()] == ["t1", "t2"]


# ── generate_board ────────────────────────────────────────────────────────

class TestGenerateBoard:
    def _roles(self):
        return SimpleNamespace(planner=None)

    def test_plano_valido(self):
        client = FakeClient([json.dumps(valid_plan())])
        result = generate_board(
            "criar um site", roles=self._roles(), client=client,
        )
        assert result.ok is True
        assert result.attempts == 1
        assert (result.tokens_in, result.tokens_out) == (10, 5)
        assert result.board.task("t1") is not None
        assert "criar um site" in client.calls[0][1]["content"]

    def test_retry_devolve_erros_ao_modelo(self):
        invalido = valid_plan()
        del invalido["fases"][0]["tasks"][0]["resultado_esperado"]

        client = FakeClient([
            json.dumps(invalido),
            json.dumps(valid_plan()),
        ])
        result = generate_board(
            "criar um site", roles=self._roles(), client=client,
            max_attempts=2,
        )

        assert result.ok is True
        assert result.attempts == 2
        assert (result.tokens_in, result.tokens_out) == (20, 10)
        # a segunda chamada contém o erro apontado pela validação
        segunda = client.calls[1]
        assert any(
            "resultado_esperado" in m.get("content", "")
            for m in segunda
        )

    def test_json_invalido_esgota_tentativas(self):
        client = FakeClient(["isso não é json"])
        result = generate_board(
            "x", roles=self._roles(), client=client, max_attempts=2,
        )
        assert result.ok is False
        assert result.attempts == 2
        assert any("JSON" in e for e in result.errors)

    def test_erro_de_rede(self):
        client = FakeClient([RuntimeError("caiu")])
        result = generate_board(
            "x", roles=self._roles(), client=client,
        )
        assert result.ok is False
        assert "caiu" in result.errors[0]

    def test_sem_planner(self):
        with pytest.raises(PlannerUnavailable):
            generate_board("x", roles=self._roles())

    def test_to_dict(self):
        client = FakeClient([json.dumps(valid_plan())])
        result = generate_board(
            "x", roles=self._roles(), client=client,
        )
        data = result.to_dict()
        assert data["ok"] is True
        assert data["attempts"] == 1
        assert "board" not in data
