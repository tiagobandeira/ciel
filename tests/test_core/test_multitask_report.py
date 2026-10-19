"""
tests/test_core/test_multitask_report.py

Cobre `multitask/report.py`: markdown, resumo, whatsapp, bullets,
artefatos, decisões, falhas, pendências e duração.
"""

from board import (
    TASK_CONCLUIDA,
    TASK_FALHOU,
    Board,
)
from multitask.report import build_report


def make_board(formato: str = "markdown") -> Board:
    board = Board.new(
        "Site de portfólio com formulário",
        run_id="run-1",
        fluxo="web",
        entrega={
            "formato": formato,
            "como_testar": "python -m http.server 8000",
        },
    )
    t1 = board.add_task(
        "estrutura", "criar pastas",
        objetivo="criar a estrutura", acoes=["mkdir"],
        resultado_esperado="pastas existem", task_id="t1",
    )
    t2 = board.add_task(
        "frontend", "criar index.html",
        objetivo="criar a página", acoes=["write_file"],
        resultado_esperado="index existe", task_id="t2",
        depende_de=["t1"],
    )
    t3 = board.add_task(
        "testes", "validar página",
        objetivo="validar", acoes=["read_file"],
        resultado_esperado="ok", task_id="t3",
        depende_de=["t2"],
    )

    board.record_task_result(
        t1.id, TASK_CONCLUIDA,
        resumo="pastas criadas",
        tokens_in=10, tokens_out=5, duracao_s=2.0,
    )
    board.add_artifact(t1.id, "site/index.html", mtime=1.0)
    board.add_decision(t1.id, "usar HTML puro")

    board.record_task_result(
        t2.id, TASK_CONCLUIDA,
        resumo="página criada com sucesso",
        tokens_in=20, tokens_out=10, duracao_s=3.0,
    )
    board.add_artifact(t2.id, "site/style.css", mtime=1.0)

    board.status = "concluida"
    board.meta["duracao_s"] = 125
    board.meta["tokens_in"] = 30
    board.meta["tokens_out"] = 15
    return board


class TestMarkdown:
    def test_inclui_objetivo_status_tasks_artefatos_decisoes(self):
        report = build_report(make_board())
        assert "## Multitask — Site de portfólio com formulário" in report
        assert "concluída" in report
        assert "2/3 tasks" in report
        assert "✅ **criar pastas**" in report
        assert "pastas criadas" in report
        assert "`site/index.html`" in report
        assert "usar HTML puro" in report
        assert "### Como testar" in report
        assert "http.server" in report

    def test_duracao_e_tokens(self):
        report = build_report(make_board())
        assert "2m 05s" in report
        assert "45 tokens" in report

    def test_pendencia_aparece(self):
        report = build_report(make_board())
        assert "### Pendências" in report
        assert "validar página" in report
        assert "(pendente)" in report

    def test_falha_aparece(self):
        board = make_board()
        board.record_task_result(
            "t3", TASK_FALHOU,
            resumo="não deu", erro="arquivo não encontrado",
        )
        board.status = "falhou"
        report = build_report(board)
        assert "### Falhas" in report
        assert "arquivo não encontrado" in report

    def test_sem_tasks_concluidas(self):
        board = Board.new("vazio", run_id="r")
        board.add_task("f", "t", acoes=["a"])
        report = build_report(board)
        assert "_Nenhuma task concluída._" in report


class TestOutrosFormatos:
    def test_resumo(self):
        report = build_report(make_board("resumo"))
        assert report.startswith("Concluí 2 de 3 tasks")
        assert "✅ criar pastas" in report
        assert "##" not in report

    def test_whatsapp_sem_headers_e_limitado(self):
        report = build_report(make_board("whatsapp"))
        assert "*Multitask —" in report
        assert "##" not in report
        assert "|" not in report
        assert len(report) <= 3501
        assert "✅ *criar pastas*" in report

    def test_bullets(self):
        report = build_report(make_board("bullets"))
        assert "- **Status:**" in report
        assert "✅ **criar pastas**" in report
        assert "##" not in report

    def test_formato_invalido_cai_em_markdown(self):
        board = make_board()
        board.entrega["formato"] = "pdf"
        report = build_report(board)
        assert report.startswith("## Multitask")

    def test_override_de_formato(self):
        report = build_report(make_board("markdown"), formato="resumo")
        assert report.startswith("Concluí")
