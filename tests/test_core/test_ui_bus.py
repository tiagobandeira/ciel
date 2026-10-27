"""Testes do barramento de eventos e do trace do turno (SSE).

O contrato é: os eventos antigos (estado/tool/passo_erro/fala) continuam
saindo para o /ui, e os novos (passo/pensando) carregam turn_id para a
interface web montar o acordeão só do turno atual.
"""

import time

import pytest

import ui_bus


class Eventos:
    """Substitui ui_bus.publish para capturar o que sairia no SSE."""

    def __init__(self):
        self.lista = []

    def __call__(self, tipo, **dados):
        self.lista.append((tipo, dados))

    def por_tipo(self, tipo):
        return [d for t, d in self.lista if t == tipo]


@pytest.fixture
def eventos(monkeypatch):
    captura = Eventos()
    monkeypatch.setattr(ui_bus, "publish", captura)
    return captura


class TestPasso:
    def test_carrega_turn_id_seq_e_status(self, eventos):
        cb = ui_bus.callbacks("abc123")

        cb["on_step"](1, "modelo", "aguardando…", "model")
        cb["on_step"](2, "tool › read_file", '{"path": "x"}', "tool")

        passos = eventos.por_tipo("passo")
        assert [p["seq"] for p in passos] == [1, 2]
        assert all(p["turn_id"] == "abc123" for p in passos)
        assert passos[1]["status"] == "tool"
        assert passos[1]["label"] == "tool › read_file"
        assert passos[1]["texto"] == '{"path": "x"}'
        assert isinstance(passos[1]["ms"], int)

    def test_texto_longo_e_truncado(self, eventos):
        cb = ui_bus.callbacks("t1")

        cb["on_step"](1, "resultado", "x" * 2000, "done")

        assert len(eventos.por_tipo("passo")[0]["texto"]) == 400

    def test_sem_turn_id_nao_quebra(self, eventos):
        cb = ui_bus.callbacks()

        cb["on_step"](1, "modelo", "x", "model")

        assert eventos.por_tipo("passo")[0]["turn_id"] is None


class TestCompatibilidadeComOUI:
    def test_eventos_antigos_continuam_saindo(self, eventos):
        cb = ui_bus.callbacks()

        cb["on_model_start"](1)
        cb["on_step"](1, "tool › run_script", "{}", "tool")
        cb["on_step"](1, "erro", "falhou", "error")
        cb["on_done"]("pronto", 1, 10, 5)

        assert eventos.por_tipo("estado")[0]["valor"] == "pensando"
        assert eventos.por_tipo("tool")[0]["nome"] == "run_script"
        assert eventos.por_tipo("passo_erro")[0]["texto"] == "falhou"
        assert eventos.por_tipo("fala")[0]["texto"] == "pronto"


class TestPensando:
    def test_marca_inicio_e_fim_da_chamada(self, eventos):
        cb = ui_bus.callbacks("t1")

        cb["on_model_start"](1)
        cb["on_model_end"](1)

        pensando = eventos.por_tipo("pensando")
        assert [p["ativo"] for p in pensando] == [True, False]
        assert all(p["turn_id"] == "t1" for p in pensando)


class TestColetor:
    def test_coletor_recebe_os_passos_para_o_historico(self, eventos):
        coletor = []
        cb = ui_bus.callbacks("t1", coletor=coletor)

        cb["on_model_start"](1)   # pensando não entra no trace salvo
        cb["on_step"](1, "modelo", "x", "model")
        cb["on_step"](1, "tool › read_file", "{}", "tool")

        assert [p["seq"] for p in coletor] == [1, 2]
        assert [p["tipo"] for p in coletor] == ["passo", "passo"]
        assert coletor[1]["status"] == "tool"
        assert coletor[1]["turn_id"] == "t1"

    def test_sem_coletor_nao_quebra(self, eventos):
        cb = ui_bus.callbacks("t1")
        cb["on_step"](1, "modelo", "x", "model")
        assert len(eventos.por_tipo("passo")) == 1


class TestCancelamento:
    def test_cancelar_seta_o_evento_do_turno(self):
        from server import app, _registrar_cancelamento, _esquecer_cancelamento

        evento = _registrar_cancelamento("t-cancel")
        try:
            r = app.test_client().post("/api/chat/cancel", json={"turn_id": "t-cancel"})

            assert r.status_code == 200
            assert r.get_json()["ok"] is True
            assert evento.is_set()
        finally:
            _esquecer_cancelamento("t-cancel")

    def test_turno_desconhecido_da_404(self):
        from server import app

        r = app.test_client().post("/api/chat/cancel", json={"turn_id": "nao-existe"})

        assert r.status_code == 404

    def test_sem_turn_id_da_404(self):
        from server import app

        r = app.test_client().post("/api/chat/cancel", json={})

        assert r.status_code == 404


class TestContratoDoServer:
    def test_turn_id_do_cliente_e_validado(self):
        from server import _turn_id_valido

        assert _turn_id_valido("abc-123_xy") == "abc-123_xy"
        assert _turn_id_valido("curto") != "curto"          # curto demais
        assert _turn_id_valido("../../etc/passwd") != "../../etc/passwd"
        assert _turn_id_valido(None) != _turn_id_valido(None)  # gera novo

    def test_publica_fim_com_duracao(self, eventos):
        from server import _publica_fim

        _publica_fim("t1", "done", 3, 10, 5, time.monotonic() - 0.5)

        dado = eventos.por_tipo("turno_fim")[0]
        assert dado["turn_id"] == "t1"
        assert dado["status"] == "done"
        assert dado["steps"] == 3
        assert dado["tokens_in"] == 10
        assert dado["tokens_out"] == 5
        assert dado["ms"] >= 400
