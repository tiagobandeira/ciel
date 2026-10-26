"""Testes da análise de quadro do multitask."""

from board import TASK_CONCLUIDA, TASK_FALHOU, Board, TASK_PENDENTE
from llm.client import ChatResult
from multitask.analisar import analyze_board


class FakeAnalyst:
    def __init__(self, text="## O que funcionou\nok", fail=False):
        self.text = text
        self.fail = fail

    def chat(self, messages, **kwargs):
        if self.fail:
            raise RuntimeError("falhou")
        return ChatResult(self.text, tokens_in=11, tokens_out=5)


def _board():
    board = Board.new("app de notas")
    board.add_task("Fase", "spec", status=TASK_CONCLUIDA)
    board.task("t1").resumo = "spec pronta"
    board.add_task("Fase", "editor", status=TASK_FALHOU)
    board.task("t2").erro = "sem tools"
    board.add_task("Fase", "preview", status=TASK_PENDENTE)
    board.meta["tokens_in"] = 100
    board.meta["tokens_out"] = 20
    return board


def test_fallback_deterministico_sem_modelo():
    result = analyze_board(_board(), None)
    assert not result.usou_modelo
    assert "O que funcionou" in result.texto
    assert "sem tools" in result.texto
    assert "Próximo passo" in result.texto


def test_usa_modelo_quando_cliente_existe():
    result = analyze_board(_board(), FakeAnalyst("## análise do modelo"))
    assert result.usou_modelo
    assert result.texto == "## análise do modelo"
    assert (result.tokens_in, result.tokens_out) == (11, 5)


def test_falha_do_modelo_cai_no_fallback():
    result = analyze_board(_board(), FakeAnalyst(fail=True))
    assert not result.usou_modelo
    assert "O que funcionou" in result.texto
