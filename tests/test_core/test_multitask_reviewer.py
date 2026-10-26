"""Testes do revisor de fase do multitask."""

import json

from board import TASK_CONCLUIDA, TASK_PENDENTE, TASK_PULADA, Board
from llm.client import ChatResult
from multitask.reviewer import review_phase


class FakeReviewer:
    def __init__(self, payload=None, text=None):
        self.payload = payload
        self.text = text
        self.chamadas = []

    def chat(self, messages, **kwargs):
        self.chamadas.append(messages)
        text = self.text if self.text is not None else json.dumps(self.payload)
        return ChatResult(text, tokens_in=7, tokens_out=3)


def _board():
    board = Board.new("objetivo")
    board.add_task(
        "Estrutura", "base", acoes=["criar"],
        checagem={"tipo": "arquivo", "path": "a.txt"},
        status=TASK_CONCLUIDA,
    )
    board.add_task(
        "Estrutura", "features", acoes=["implementar"],
        checagem={"tipo": "arquivo", "path": "b.txt"},
    )
    return board


def test_revisor_adiciona_atualiza_pula_e_reordena():
    board = _board()
    client = FakeReviewer({
        "resumo": "fase ok",
        "changes": [
            {"tipo": "adicionar", "titulo": "testes",
             "objetivo": "testar", "acoes": ["rodar"],
             "checagem": [{"tipo": "arquivo", "path": "c.txt"}],
             "max_steps": 4},
            {"tipo": "atualizar", "task_id": "t2",
             "campos": {"objetivo": "implementar melhor"}},
            {"tipo": "pular", "task_id": "t2", "motivo": "coberta"},
            {"tipo": "reordenar", "ordem": ["t2", "t3"]},
        ],
    })

    result = review_phase(board, "Estrutura", client)

    assert result.ok
    assert len(result.applied) == 4
    assert board.task("t2").status == TASK_PULADA
    assert board.task("t2").objetivo == "implementar melhor"
    assert board.task("t3").titulo == "testes"
    assert board.task("t1").status == TASK_CONCLUIDA
    assert (result.tokens_in, result.tokens_out) == (7, 3)


def test_revisor_nao_altera_task_concluida():
    board = _board()
    client = FakeReviewer({
        "changes": [
            {"tipo": "atualizar", "task_id": "t1",
             "campos": {"objetivo": "não pode"}},
        ],
    })

    result = review_phase(board, "Estrutura", client)

    assert not result.ok
    assert board.task("t1").objetivo == ""


def test_revisor_json_invalido():
    board = _board()
    result = review_phase(board, "Estrutura", FakeReviewer(text="não é json"))
    assert not result.ok
    assert "JSON" in result.errors[0]


def test_tools_inventadas_nao_quebram_a_task():
    board = _board()
    client = FakeReviewer({
        "changes": [{
            "tipo": "adicionar", "titulo": "task nova",
            "acoes": ["fazer"], "tools": ["shell", "editor"],
        }],
    })

    result = review_phase(
        board, "Estrutura", client, available_tools={"read_file", "write_file"},
    )

    assert result.ok
    nova = next(t for t in board.tasks() if t.titulo == "task nova")
    assert nova.tools is None


def test_revisor_sem_cliente():
    result = review_phase(_board(), "Estrutura", None)
    assert not result.ok
