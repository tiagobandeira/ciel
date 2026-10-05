"""
tests/test_core/test_whatsapp_launcher.py

Cobre mcp/whatsapp/launcher.py (subida do bridge junto com `ciel bot`) e o
filtro inicial de mcp/whatsapp/bot.py (from_me / allowlist):

  - pré-requisitos: node ausente/antigo, node_modules faltando, bridge.js ausente
  - sessão: is_paired() com e sem conta vinculada
  - ensure_bridge: bridge_url remota, bridge já respondendo, início normal
  - start_bridge: saída encaminhada com prefixo [bridge], porta sem número
  - wait_ready: processo que morre antes de conectar
  - Bridge.stop(): encerra o processo (terminate → kill)
  - bot: from_me descartado em silêncio; fora da allowlist loga 'ignorado'

Os testes de processo usam um bridge.js falso (Node real) em tmp_path e são
pulados se o node não estiver no PATH.
"""

import shutil
import socket
import sys
import time
from pathlib import Path

import pytest

from mcp.whatsapp import launcher as L

NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node não está no PATH")

DEPS = ["@whiskeysockets/baileys", "express", "pino", "qrcode-terminal"]

FAKE_BRIDGE = """
import http from "http";
const port = parseInt(process.env.BRIDGE_PORT ?? "8765", 10);
console.log("[bridge] fake no ar; webhook=" + process.env.CIEL_WEBHOOK_URL);
http.createServer((req, res) => {
  if (req.url === "/status") {
    res.setHeader("Content-Type", "application/json");
    res.end(JSON.stringify({ status: "connected" }));
  } else { res.statusCode = 404; res.end(); }
}).listen(port, "127.0.0.1");
"""

PACKAGE_JSON = '{"type": "module", "dependencies": {%s}, "engines": {"node": ">=20.0.0"}}' % (
    ", ".join(f'"{d}": "*"' for d in DEPS)
)


# ── helpers / fixtures ────────────────────────────────────────────────────────

def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _make_bridge_dir(root: Path, script: str = FAKE_BRIDGE, deps: bool = True, paired: bool = True) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "bridge.js").write_text(script, encoding="utf-8")
    (root / "package.json").write_text(PACKAGE_JSON, encoding="utf-8")
    if deps:
        for d in DEPS:
            (root / "node_modules" / d).mkdir(parents=True, exist_ok=True)
    if paired:
        (root / "auth").mkdir(exist_ok=True)
        (root / "auth" / "creds.json").write_text('{"me": {"id": "x@s.whatsapp.net"}}', encoding="utf-8")
    return root


@pytest.fixture
def bdir(tmp_path, monkeypatch):
    """Pasta de bridge falsa e isolada; o launcher passa a usá-la."""
    d = _make_bridge_dir(tmp_path / "bridge")
    monkeypatch.setattr(L, "BRIDGE_DIR", d)
    return d


@pytest.fixture
def started():
    """Garante que qualquer Bridge iniciado no teste seja encerrado no final."""
    handles = []
    yield handles
    for b in handles:
        b.stop()


# ── is_paired ─────────────────────────────────────────────────────────────────

class TestIsPaired:
    def test_com_conta_vinculada(self, bdir):
        assert L.is_paired() is True

    def test_sem_creds(self, bdir):
        (bdir / "auth" / "creds.json").unlink()
        assert L.is_paired() is False

    def test_creds_sem_me(self, bdir):
        (bdir / "auth" / "creds.json").write_text("{}", encoding="utf-8")
        assert L.is_paired() is False

    def test_creds_quebrado(self, bdir):
        (bdir / "auth" / "creds.json").write_text("{nao é json", encoding="utf-8")
        assert L.is_paired() is False


# ── check_prerequisites ───────────────────────────────────────────────────────

class TestPrerequisites:
    @needs_node
    def test_tudo_ok(self, bdir):
        assert L.check_prerequisites() == []

    def test_node_ausente(self, bdir, monkeypatch):
        monkeypatch.setattr(L.shutil, "which", lambda _name: None)
        problems = L.check_prerequisites()
        assert any("Node.js não encontrado" in p for p in problems)

    def test_node_antigo(self, bdir, monkeypatch):
        monkeypatch.setattr(L.shutil, "which", lambda _name: "/fake/node")
        monkeypatch.setattr(L, "_node_major", lambda _node: 18)
        problems = L.check_prerequisites()
        assert any("Node 18" in p and "20" in p for p in problems)

    def test_versao_do_node_ilegivel(self, bdir, monkeypatch):
        monkeypatch.setattr(L.shutil, "which", lambda _name: "/fake/node")
        monkeypatch.setattr(L, "_node_major", lambda _node: None)
        assert any("versão do Node" in p for p in L.check_prerequisites())

    def test_dependencias_faltando(self, bdir, monkeypatch):
        monkeypatch.setattr(L.shutil, "which", lambda _name: "/fake/node")
        monkeypatch.setattr(L, "_node_major", lambda _node: 22)
        shutil.rmtree(bdir / "node_modules")
        problems = L.check_prerequisites()
        joined = "\n".join(problems)
        assert "npm install" in joined
        assert "Git" in joined
        assert "express" in joined

    def test_bridge_js_ausente(self, bdir, monkeypatch):
        monkeypatch.setattr(L.shutil, "which", lambda _name: "/fake/node")
        monkeypatch.setattr(L, "_node_major", lambda _node: 22)
        (bdir / "bridge.js").unlink()
        assert any("bridge.js não encontrado" in p for p in L.check_prerequisites())

    def test_engines_do_package_json_define_o_minimo(self, bdir):
        (bdir / "package.json").write_text('{"engines": {"node": ">=22.1.0"}}', encoding="utf-8")
        assert L._required_node_major() == 22

    def test_sem_engines_usa_o_padrao(self, bdir):
        (bdir / "package.json").write_text("{}", encoding="utf-8")
        assert L._required_node_major() == L.DEFAULT_MIN_NODE


# ── ensure_bridge ─────────────────────────────────────────────────────────────

class TestEnsureBridge:
    def test_url_remota_nao_inicia_nada(self, bdir, monkeypatch):
        called = []
        monkeypatch.setattr(L, "start_bridge", lambda *a, **k: called.append(1))
        logs = []
        result = L.ensure_bridge("http://192.168.0.5:8765", 8766, log=logs.append)
        assert result is None
        assert called == []
        assert any("fora desta máquina" in l for l in logs)

    def test_bridge_ja_respondendo_e_reaproveitado(self, bdir, monkeypatch):
        monkeypatch.setattr(L, "bridge_reachable", lambda _url: True)
        called = []
        monkeypatch.setattr(L, "start_bridge", lambda *a, **k: called.append(1))
        logs = []
        assert L.ensure_bridge("http://127.0.0.1:8765", 8766, log=logs.append) is None
        assert called == []
        assert any("Já há um bridge" in l for l in logs)

    @needs_node
    def test_inicia_e_fica_conectado(self, bdir, started):
        port = _free_port()
        logs = []
        bridge = L.ensure_bridge(f"http://127.0.0.1:{port}", 8766, log=logs.append)
        assert bridge is not None
        started.append(bridge)
        assert bridge.alive()
        assert L._status(f"http://127.0.0.1:{port}") == "connected"

    @needs_node
    def test_bridge_que_morre_cedo_levanta_erro_claro(self, tmp_path, monkeypatch):
        d = _make_bridge_dir(tmp_path / "morre", script='console.log("boom"); process.exit(3);')
        monkeypatch.setattr(L, "BRIDGE_DIR", d)
        with pytest.raises(L.BridgeError) as exc:
            L.ensure_bridge(f"http://127.0.0.1:{_free_port()}", 8766, log=lambda _l: None)
        assert "código 3" in str(exc.value)


# ── start_bridge ──────────────────────────────────────────────────────────────

class TestStartBridge:
    def test_pre_requisito_faltando_levanta_erro_com_no_bridge(self, bdir, monkeypatch):
        monkeypatch.setattr(L.shutil, "which", lambda _name: None)
        with pytest.raises(L.BridgeError) as exc:
            L.start_bridge("http://127.0.0.1:8765", 8766)
        msg = str(exc.value)
        assert "Node.js não encontrado" in msg
        assert "--no-bridge" in msg

    @needs_node
    def test_url_sem_porta(self, bdir):
        with pytest.raises(L.BridgeError, match="sem porta"):
            L.start_bridge("http://127.0.0.1", 8766)

    @needs_node
    def test_saida_encaminhada_com_prefixo_e_webhook_na_env(self, bdir, started):
        logs = []
        port = _free_port()
        bridge = L.start_bridge(f"http://127.0.0.1:{port}", 18766, log=logs.append)
        started.append(bridge)
        deadline = time.monotonic() + 10
        while not logs and time.monotonic() < deadline:
            time.sleep(0.05)
        assert logs, "o bridge não imprimiu nada"
        assert logs[0].startswith("[bridge]")
        assert "http://127.0.0.1:18766/webhook" in logs[0]


# ── wait_ready ────────────────────────────────────────────────────────────────

class TestWaitReady:
    @needs_node
    def test_conecta(self, bdir, started):
        port = _free_port()
        bridge = L.start_bridge(f"http://127.0.0.1:{port}", 8766, log=lambda _l: None)
        started.append(bridge)
        assert bridge.wait_ready(timeout=10, log=lambda _l: None) is True

    @needs_node
    def test_estoura_o_prazo_sem_matar_o_bridge(self, tmp_path, monkeypatch, started):
        # sobe um servidor que nunca responde "connected"
        script = (
            'import http from "http";'
            'http.createServer((q, r) => { r.setHeader("Content-Type","application/json");'
            ' r.end(JSON.stringify({status: "disconnected"})); })'
            '.listen(parseInt(process.env.BRIDGE_PORT, 10), "127.0.0.1");'
        )
        d = _make_bridge_dir(tmp_path / "lento", script=script)
        monkeypatch.setattr(L, "BRIDGE_DIR", d)
        bridge = L.start_bridge(f"http://127.0.0.1:{_free_port()}", 8766, log=lambda _l: None)
        started.append(bridge)
        assert bridge.wait_ready(timeout=1, poll=0.1, log=lambda _l: None) is False
        assert bridge.alive()


# ── Bridge.stop ───────────────────────────────────────────────────────────────

class TestStop:
    @needs_node
    def test_encerra_o_processo(self, bdir):
        port = _free_port()
        url = f"http://127.0.0.1:{port}"
        bridge = L.start_bridge(url, 8766, log=lambda _l: None)
        assert bridge.wait_ready(timeout=10, log=lambda _l: None)
        bridge.stop()
        assert not bridge.alive()
        assert L.bridge_reachable(url) is False

    @needs_node
    def test_stop_duas_vezes_nao_quebra(self, bdir):
        bridge = L.start_bridge(f"http://127.0.0.1:{_free_port()}", 8766, log=lambda _l: None)
        bridge.stop()
        bridge.stop()
        assert not bridge.alive()

    @needs_node
    def test_kill_quando_ignora_terminate(self, tmp_path, monkeypatch):
        if sys.platform == "win32":
            pytest.skip("no Windows terminate() já é kill()")
        script = 'process.on("SIGTERM", () => {}); setInterval(() => {}, 1000); console.log("[bridge] teimoso");'
        d = _make_bridge_dir(tmp_path / "teimoso", script=script)
        monkeypatch.setattr(L, "BRIDGE_DIR", d)
        bridge = L.start_bridge(f"http://127.0.0.1:{_free_port()}", 8766, log=lambda _l: None)
        time.sleep(0.5)
        t0 = time.monotonic()
        bridge.stop(timeout=0.5)
        assert not bridge.alive()
        assert time.monotonic() - t0 < 5


# ── bot: filtro inicial de mensagens ──────────────────────────────────────────

class TestBotFiltro:
    def _event(self, **over):
        ev = {"chat_id": "123@lid", "sender": "+123", "text": "oi", "type": "direct", "from_me": False}
        ev.update(over)
        return ev

    def test_from_me_e_descartado_em_silencio(self, monkeypatch):
        from mcp.whatsapp import bot
        errors, events = [], []
        monkeypatch.setattr(bot.ch, "is_allowed", lambda *_a, **_k: pytest.fail("não deveria checar allowlist"))
        bot._handle_message_inner(
            self._event(from_me=True), "m", False,
            on_event=lambda *a: events.append(a),
            on_error=lambda *a: errors.append(a),
        )
        assert errors == []
        assert events == []

    def test_fora_da_allowlist_loga_remetente(self, monkeypatch):
        from mcp.whatsapp import bot
        errors, events = [], []
        monkeypatch.setattr(bot.ch, "is_allowed", lambda *_a, **_k: False)
        bot._handle_message_inner(
            self._event(sender="+247000000000000"), "m", False,
            on_event=lambda *a: events.append(a),
            on_error=lambda *a: errors.append(a),
        )
        assert events == []
        assert len(errors) == 1
        kind, msg = errors[0]
        assert kind == "ignorado"
        assert "+247000000000000" in msg
        assert "fora da allowlist" in msg
        assert "chat_id=123@lid" in msg

    def test_excecao_na_thread_chega_ao_on_error(self, monkeypatch):
        from mcp.whatsapp import bot
        errors = []

        def boom(*_a, **_k):
            raise RuntimeError("falhou")

        monkeypatch.setattr(bot, "_handle_message_inner", boom)
        bot._handle_message(self._event(), "m", False, on_error=lambda *a: errors.append(a))
        assert errors == [("exception", "RuntimeError: falhou")]