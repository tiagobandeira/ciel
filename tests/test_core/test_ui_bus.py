"""Testes do barramento de eventos e do trace do turno (SSE).

O contrato é: os eventos antigos (estado/tool/passo_erro/fala) continuam
saindo para o /ui, e os novos (passo/pensando) carregam turn_id para a
interface web montar o acordeão só do turno atual.
"""

import threading
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


# ── tools INTERACTIVE (perguntar) ─────────────────────────────────────────────

def _esperar(condicao, limite=2.0):
    fim = time.monotonic() + limite
    while time.monotonic() < fim:
        if condicao():
            return True
        time.sleep(0.01)
    return False


def _tem_pergunta(eventos, turno):
    return any(d["turn_id"] == turno for d in eventos.por_tipo("pergunta"))


class TestPerguntasInterativas:
    """A pergunta sai pelo SSE e a resposta volta por /api/chat/responder."""

    def test_resposta_libera_o_callback(self, eventos):
        import server
        from server import app, _ask_user_do_turno

        turno = "teste-resposta"
        resultado = {}

        def worker():
            ask = _ask_user_do_turno(turno, None)
            resultado["valor"] = ask("Qual seu SO?", ["Windows", "Linux"])

        t = threading.Thread(target=worker, daemon=True)
        t.start()
        try:
            assert _esperar(lambda: _tem_pergunta(eventos, turno))
            pergunta = next(
                d for d in eventos.por_tipo("pergunta") if d["turn_id"] == turno
            )
            assert pergunta["texto"] == "Qual seu SO?"
            assert pergunta["opcoes"] == ["Windows", "Linux"]

            r = app.test_client().post(
                "/api/chat/responder",
                json={"turn_id": turno, "resposta": "Linux"},
            )

            assert r.status_code == 200
            t.join(2)
            assert not t.is_alive()
            assert resultado["valor"] == "Linux"
        finally:
            with server._pergunta_lock:
                pendente = server._perguntas_pendentes.pop(turno, None)
            if pendente is not None:
                pendente.set()
            t.join(2)

    def test_cancelamento_acorda_a_espera(self, eventos):
        """O botão "parar" precisa funcionar com uma pergunta pendente."""
        import server
        from server import _ask_user_do_turno

        turno = "teste-cancelar"
        cancelar = threading.Event()
        resultado = {}

        def worker():
            ask = _ask_user_do_turno(turno, cancelar)
            resultado["valor"] = ask("Pergunta sem resposta?", None)

        t = threading.Thread(target=worker, daemon=True)
        t.start()
        try:
            assert _esperar(lambda: _tem_pergunta(eventos, turno))
            cancelar.set()
            t.join(2)
            assert not t.is_alive()
            assert resultado["valor"] == ""
        finally:
            with server._pergunta_lock:
                pendente = server._perguntas_pendentes.pop(turno, None)
            if pendente is not None:
                pendente.set()
            t.join(2)

    def test_timeout_devolve_vazio_e_encerra_o_turno(self, eventos, monkeypatch):
        import server

        monkeypatch.setattr(server, "_PER_PERGUNTA_TIMEOUT_S", 0.01)
        turno = "teste-timeout"
        cancelar = threading.Event()
        resultado = {}

        def worker():
            ask = server._ask_user_do_turno(turno, cancelar)
            resultado["valor"] = ask("Pergunta que ninguém responde?", None)

        t = threading.Thread(target=worker, daemon=True)
        t.start()
        try:
            t.join(2)
            assert not t.is_alive()
            assert resultado["valor"] == ""
            assert cancelar.is_set()
            assert any(
                d["turn_id"] == turno for d in eventos.por_tipo("pergunta_expirada")
            )
        finally:
            t.join(2)

    def test_sem_pergunta_pendente_da_404(self):
        from server import app

        r = app.test_client().post(
            "/api/chat/responder",
            json={"turn_id": "nao-existe", "resposta": "x"},
        )

        assert r.status_code == 404

    def test_resposta_ausente_da_400(self):
        from server import app

        r = app.test_client().post(
            "/api/chat/responder",
            json={"turn_id": "nao-existe"},
        )

        assert r.status_code == 400


class TestFiacaoDoChatComPerguntas:
    """_chat_turn injeta on_ask_user conforme o opt-in "perguntas_interativas"."""

    @pytest.fixture
    def estado_falso(self, monkeypatch):
        import server

        class StoreFalso:
            def append_turn(self, *a, **kw):
                pass

            def get_session(self, sid):
                return {"title": "teste"}

            def new_session(self, **kw):
                return 1

        class EstadoFalso:
            model = "modelo-teste"
            model_client = None
            model_label = "modelo-teste"
            perfil = "local"
            agent_id = "general"
            agent_info = {"name": "General"}
            tools = {}
            schema = []
            session_id = 1
            context_injection = None
            base_url = "http://localhost"
            tokens_in = 0
            tokens_out = 0
            branch_pending = None
            force_safe = False

            def __init__(self):
                self.history = []
                self.store = StoreFalso()

            def reload_tools_for_request(self):
                pass

        monkeypatch.setattr(server, "state", EstadoFalso())
        return server.state

    def test_duas_perguntas_no_mesmo_turno(self, eventos, estado_falso, monkeypatch):
        import server
        from agent_loop import AgentResult

        respostas = []

        def run_agent_falso(prompt, tools, schema, model, agent_info, **kw):
            ask = kw.get("on_ask_user")
            assert ask is not None, "server deve injetar on_ask_user"
            respostas.append(ask("Primeira pergunta?", ["A", "B"]))
            respostas.append(ask("Segunda pergunta?", None))
            return AgentResult("done", f"recebi:{respostas}", steps=2)

        monkeypatch.setattr(server, "run_agent", run_agent_falso)

        turno = "teste-chat-1"
        resposta = {}

        def worker():
            with server.app.test_client() as c:
                resposta["r"] = c.post(
                    "/api/chat",
                    json={
                        "message": "conduza a entrevista",
                        "turn_id": turno,
                        "perguntas_interativas": True,
                    },
                )

        t = threading.Thread(target=worker, daemon=True)
        t.start()

        def quantas_perguntas():
            return len(
                [d for d in eventos.por_tipo("pergunta") if d["turn_id"] == turno]
            )

        try:
            assert _esperar(lambda: quantas_perguntas() >= 1)
            r1 = server.app.test_client().post(
                "/api/chat/responder",
                json={"turn_id": turno, "resposta": "A"},
            )
            assert r1.status_code == 200

            assert _esperar(lambda: quantas_perguntas() >= 2)
            r2 = server.app.test_client().post(
                "/api/chat/responder",
                json={"turn_id": turno, "resposta": "resposta livre"},
            )
            assert r2.status_code == 200

            t.join(5)
            assert not t.is_alive()
            assert resposta["r"].status_code == 200
            assert resposta["r"].get_json()["reply"] == (
                "recebi:['A', 'resposta livre']"
            )
            assert respostas == ["A", "resposta livre"]
        finally:
            if t.is_alive():
                server.app.test_client().post(
                    "/api/chat/cancel", json={"turn_id": turno}
                )
            t.join(5)

    def test_sem_opt_in_nao_injeta_ask_user(self, estado_falso, monkeypatch):
        """/ui e clientes antigos continuam sem UI de pergunta: on_ask_user=None."""
        import server
        from agent_loop import AgentResult

        vistos = []

        def run_agent_falso(prompt, tools, schema, model, agent_info, **kw):
            vistos.append(kw.get("on_ask_user"))
            return AgentResult("done", "ok", steps=1)

        monkeypatch.setattr(server, "run_agent", run_agent_falso)

        r = server.app.test_client().post(
            "/api/chat",
            json={"message": "oi", "turn_id": "teste-chat-2"},
        )

        assert r.status_code == 200
        assert vistos == [None]
