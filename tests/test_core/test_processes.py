"""Testes do registry de processos nativos."""

from llm.roles import normalize_perfil
from multitask.flow import build_board, load_flow
from multitask.runner import RunResult
from processes import detect_process, get_process, list_processes


def test_normaliza_aliases_de_perfil():
    assert normalize_perfil("build") == "nuvem"
    assert normalize_perfil("cloud") == "nuvem"
    assert normalize_perfil("nuvem") == "nuvem"
    assert normalize_perfil("local") == "local"
    assert normalize_perfil("qualquer") == "local"


def test_lista_processos():
    ids = {p.id for p in list_processes()}
    assert {"app_web", "landing_page", "jogo_web", "corrigir_bug"} <= ids


def test_get_process_por_id_ou_titulo():
    assert get_process("app_web").id == "app_web"
    assert get_process("App web").id == "app_web"
    assert get_process("nao_existe") is None


def test_detect_process_por_intencao():
    assert detect_process("quero um app de notas em markdown").id == "app_web"
    assert detect_process("crie uma landing page para o produto").id == "landing_page"
    assert detect_process("faça um jogo da cobrinha").id == "jogo_web"
    assert detect_process("escreva um artigo sobre grupos").id == "artigo_matematica"
    assert detect_process("monte um notebook jupyter sobre o tema").id == "notebook_matematica"
    assert detect_process("corrija o bug do demo").id == "corrigir_bug"


def test_app_web_e_um_fluxo_valido():
    flow = load_flow("app_web")
    board = build_board(flow)
    assert len(board.tasks()) == 6
    assert not board.validate()
    assert board.task("t1").titulo == "spec"


def test_corrigir_bug_e_um_fluxo_valido():
    flow = load_flow("corrigir_bug")
    board = build_board(flow)
    assert len(board.tasks()) == 3
    assert not board.validate()
    assert board.task("t2").titulo == "corrigir"


def test_resumo_curto_do_processo():
    from board import Board
    from cli import _process_summary

    board = Board.new("app", run_id="run-resumo")
    task = board.add_task("f", "implementar")
    task.status = "concluida"
    task.resumo = "implementei a persistência"
    task.artefatos = [{"path": "data/user/app_web/app.js", "mtime": None}]
    task.checagem_ok = True
    task.checagem = {"tipo": "arquivo", "path": "data/user/app_web/app.js"}
    board.meta["como_testar"] = "abra index.html"

    result = RunResult("concluida", board, "relatório grande")
    summary = _process_summary(result, "app_web")

    assert "App web" in summary
    assert "1/1" in summary
    assert "implementei a persistência" in summary
    assert "data/user/app_web/app.js" in summary
    assert "abra index.html" in summary
    assert "relatório grande" not in summary
