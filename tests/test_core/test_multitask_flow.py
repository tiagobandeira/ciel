"""
tests/test_core/test_multitask_flow.py

Cobre `multitask/flow.py`: cabeçalho, tasks, dependências por nome/id,
validação e listagem.
"""

from pathlib import Path

import pytest

from multitask.flow import (
    FlowError,
    build_board,
    command_checks,
    detect_format,
    is_trusted_flow_path,
    list_flows,
    load_flow,
)


FLOW = """\
## flow: site_teste
objetivo: criar um site de teste
perfil: build
formato: resumo
como_testar: abra index.html
idioma: pt-BR

## task: estrutura
fase: estrutura
agente: dev_helper
objetivo: criar os arquivos base
ações:
- criar index.html
- criar style.css
resultado esperado: os arquivos existem
checagem: {"tipo": "arquivo", "path": "index.html"}

## task: conferir
fase: verificação
depende_de: estrutura
objetivo: conferir a listagem
ações:
- listar a pasta [tool: list_directory]
resultado esperado: a listagem contém os arquivos
"""


@pytest.fixture
def flows_dir(tmp_path):
    d = tmp_path / "flows"
    d.mkdir()
    (d / "site_teste.md").write_text(FLOW, encoding="utf-8")
    return d


class TestLoadFlow:
    def test_cabecalho_e_tasks(self, flows_dir):
        flow = load_flow("site_teste", flows_dir=flows_dir)
        assert flow.name == "site_teste"
        assert flow.objetivo == "criar um site de teste"
        assert flow.perfil == "nuvem"
        assert flow.formato == "resumo"
        assert flow.como_testar == "abra index.html"
        assert flow.meta["idioma"] == "pt-BR"
        assert len(flow.tasks) == 2
        assert flow.tasks[0]["nome"] == "estrutura"
        assert flow.tasks[1]["depende_de"] == ["estrutura"]

    def test_por_caminho(self, flows_dir):
        flow = load_flow(flows_dir / "site_teste.md")
        assert flow.name == "site_teste"

    def test_nome_inexistente(self, flows_dir):
        with pytest.raises(FlowError) as exc:
            load_flow("nao-existe", flows_dir=flows_dir)
        assert "site_teste" in str(exc.value)

    def test_sem_tasks(self, tmp_path):
        d = tmp_path / "flows"
        d.mkdir()
        (d / "vazio.md").write_text("## flow: vazio\nobjetivo: nada\n", encoding="utf-8")
        with pytest.raises(FlowError):
            load_flow("vazio", flows_dir=d)

    def test_formato_invalido_cai_em_markdown(self, tmp_path):
        d = tmp_path / "flows"
        d.mkdir()
        (d / "x.md").write_text(
            "## flow: x\nobjetivo: x\nformato: pdf\n\n"
            "## task: a\nações:\n- fazer\n",
            encoding="utf-8",
        )
        assert load_flow("x", flows_dir=d).formato == "markdown"

    def test_objetivo_herda_da_primeira_task(self, tmp_path):
        d = tmp_path / "flows"
        d.mkdir()
        (d / "x.md").write_text(
            "## flow: x\n\n## task: a\nobjetivo: da task\nações:\n- fazer\n",
            encoding="utf-8",
        )
        assert load_flow("x", flows_dir=d).objetivo == "da task"


class TestBuildBoard:
    def test_fases_ids_e_campos(self, flows_dir):
        board = build_board(load_flow("site_teste", flows_dir=flows_dir))

        assert board.objetivo == "criar um site de teste"
        assert board.fluxo == "site_teste"
        assert board.perfil == "nuvem"
        assert board.entrega == {
            "formato": "resumo",
            "como_testar": "abra index.html",
        }

        tasks = board.tasks()
        assert [t.id for t in tasks] == ["t1", "t2"]
        assert tasks[0].titulo == "estrutura"
        assert tasks[0].objetivo == "criar os arquivos base"
        assert tasks[0].acoes == ["criar index.html", "criar style.css"]
        assert tasks[0].agente == "dev_helper"
        assert tasks[0].checagem == {"tipo": "arquivo", "path": "index.html"}
        assert tasks[1].depende_de == ["t1"]
        assert board.validate() == []

    def test_dependencia_por_id(self, tmp_path):
        d = tmp_path / "flows"
        d.mkdir()
        (d / "x.md").write_text(
            "## flow: x\nobjetivo: x\n\n"
            "## task: a\nações:\n- fazer\n\n"
            "## task: b\ndepende_de: t1\nações:\n- fazer\n",
            encoding="utf-8",
        )
        board = build_board(load_flow("x", flows_dir=d))
        assert board.task("t2").depende_de == ["t1"]

    def test_dependencia_desconhecida(self, tmp_path):
        d = tmp_path / "flows"
        d.mkdir()
        (d / "x.md").write_text(
            "## flow: x\nobjetivo: x\n\n"
            "## task: a\ndepende_de: fantasma\nações:\n- fazer\n",
            encoding="utf-8",
        )
        with pytest.raises(FlowError) as exc:
            build_board(load_flow("x", flows_dir=d))
        assert "fantasma" in str(exc.value)

    def test_task_duplicada(self, tmp_path):
        d = tmp_path / "flows"
        d.mkdir()
        (d / "x.md").write_text(
            "## flow: x\nobjetivo: x\n\n"
            "## task: a\nações:\n- fazer\n\n"
            "## task: a\nações:\n- fazer\n",
            encoding="utf-8",
        )
        with pytest.raises(FlowError) as exc:
            build_board(load_flow("x", flows_dir=d))
        assert "duplicada" in str(exc.value)

    def test_override_de_objetivo_e_formato(self, flows_dir):
        flow = load_flow("site_teste", flows_dir=flows_dir)
        board = build_board(flow, objetivo="outro objetivo", formato="whatsapp")
        assert board.objetivo == "outro objetivo"
        assert board.entrega["formato"] == "whatsapp"

    def test_fase_default(self, tmp_path):
        d = tmp_path / "flows"
        d.mkdir()
        (d / "x.md").write_text(
            "## flow: x\nobjetivo: x\n\n## task: a\nações:\n- fazer\n",
            encoding="utf-8",
        )
        board = build_board(load_flow("x", flows_dir=d))
        assert board.fases[0].nome == "geral"
        assert board.perfil == ""       # herda o perfil do ciel_config.json

    def test_override_de_perfil(self, flows_dir):
        flow = load_flow("site_teste", flows_dir=flows_dir)
        board = build_board(flow, perfil="build")
        assert board.perfil == "nuvem"


class TestListFlows:
    def test_lista_validos_e_ignora_quebrados(self, flows_dir):
        (flows_dir / "quebrado.md").write_text("nada aqui", encoding="utf-8")
        flows = list_flows(flows_dir)
        assert [f["name"] for f in flows] == ["site_teste"]
        assert flows[0]["tasks"] == 2

    def test_pasta_inexistente(self, tmp_path):
        assert list_flows(tmp_path / "nada") == []


class TestDetectFormat:
    def test_whatsapp(self):
        assert detect_format("me manda isso no whatsapp") == "whatsapp"

    def test_topicos(self):
        assert detect_format("responda em tópicos") == "bullets"

    def test_resumo(self):
        assert detect_format("quero um resumo curto") == "resumo"

    def test_sem_hint(self):
        assert detect_format("criar um site de portfólio") is None

    def test_objetivo_define_formato_do_quadro(self, flows_dir):
        flow = load_flow("site_teste", flows_dir=flows_dir)
        board = build_board(flow, objetivo="entregue em tópicos")
        assert board.entrega["formato"] == "bullets"

    def test_formato_explicito_vence_o_pedido(self, flows_dir):
        flow = load_flow("site_teste", flows_dir=flows_dir)
        board = build_board(
            flow, objetivo="entregue em tópicos", formato="resumo",
        )
        assert board.entrega["formato"] == "resumo"


class TestTrustEPerigo:
    def test_fluxo_dentro_de_flows_e_confiavel(self, flows_dir):
        flow = load_flow("site_teste", flows_dir=flows_dir)
        assert is_trusted_flow_path(flow.path, flows_dir=flows_dir) is True

    def test_fluxo_fora_de_flows_nao_e_confiavel(self, tmp_path, flows_dir):
        externo = tmp_path / "externo.md"
        externo.write_text(FLOW, encoding="utf-8")
        assert is_trusted_flow_path(externo, flows_dir=flows_dir) is False

    def test_command_checks_aninhados(self, tmp_path):
        d = tmp_path / "flows"
        d.mkdir()
        (d / "x.md").write_text(
            "## flow: x\nobjetivo: x\n\n"
            "## task: a\n"
            'checagem: [{"tipo":"arquivo","path":"a"},'
            '{"tipo":"comando","cmd":["echo","ok"]}]\n'
            "ações:\n- fazer\n",
            encoding="utf-8",
        )
        flow = load_flow("x", flows_dir=d)
        assert len(command_checks(flow)) == 1

    def test_command_checks_sem_comando(self, flows_dir):
        flow = load_flow("site_teste", flows_dir=flows_dir)
        assert command_checks(flow) == []
