"""
mcp/whatsapp/launcher.py
========================
Sobe o bridge (bridge.js) junto com o `ciel bot`.

Fluxo (ensure_bridge):
  1. bridge_url não é local          → não inicia nada (bridge de outra máquina)
  2. já há um bridge respondendo      → usa esse, não inicia um segundo
  3. checa node / versão / node_modules; se faltar algo, diz o que rodar
  4. sessão ainda não pareada         → bridge em PRIMEIRO PLANO (herda o terminal,
                                        o QR aparece inteiro); espera o pareamento
     sessão já pareada                → bridge em SEGUNDO PLANO, com a saída
                                        encaminhada ao terminal com o prefixo [bridge]
  5. no encerramento, o chamador chama bridge.stop()

O node é iniciado direto (não via `npm start`), para que terminate()/kill()
atinjam o processo certo — no Windows o npm deixa o node órfão.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

import requests

BRIDGE_DIR    = Path(__file__).parent
BRIDGE_SCRIPT = "bridge.js"

LOCAL_HOSTS      = {"127.0.0.1", "localhost", "::1"}
DEFAULT_MIN_NODE = 20     # usado se o package.json não declarar engines.node

READY_TIMEOUT   = 30      # s — bridge já pareado: tempo para conectar ao WhatsApp
PAIRING_TIMEOUT = 300     # s — esperando o usuário escanear o QR
STOP_TIMEOUT    = 5       # s — terminate() → kill()

Log = Callable[[str], None]


class BridgeError(RuntimeError):
    """Problema que impede subir o bridge. A mensagem já é para o usuário."""


def _print(line: str) -> None:
    """print seguro: não quebra em terminais cujo encoding não tem ▄ ← ✓."""
    try:
        print(line, flush=True)
    except UnicodeEncodeError:
        enc = sys.stdout.encoding or "utf-8"
        print(line.encode(enc, errors="replace").decode(enc), flush=True)


# ── sessão ────────────────────────────────────────────────────────────────────

def is_paired() -> bool:
    """
    True se auth/creds.json tem uma conta vinculada ('me'). Sem isso o bridge vai
    mostrar o QR, então precisa rodar em primeiro plano.
    """
    try:
        creds = json.loads((BRIDGE_DIR / "auth" / "creds.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(creds, dict) and bool(creds.get("me"))


# ── pré-requisitos ────────────────────────────────────────────────────────────

def _package_json() -> dict:
    try:
        data = json.loads((BRIDGE_DIR / "package.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _required_node_major() -> int:
    engines = _package_json().get("engines")
    spec = engines.get("node", "") if isinstance(engines, dict) else ""
    m = re.search(r"\d+", str(spec))
    return int(m.group()) if m else DEFAULT_MIN_NODE


def _node_major(node: str) -> int | None:
    try:
        out = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.match(r"v?(\d+)", out.strip())
    return int(m.group(1)) if m else None


def _missing_dependencies() -> list[str]:
    deps = _package_json().get("dependencies")
    names = list(deps) if isinstance(deps, dict) else []
    modules = BRIDGE_DIR / "node_modules"
    if not names:
        return [] if modules.is_dir() else ["node_modules"]
    return [n for n in names if not (modules / n).is_dir()]


def check_prerequisites() -> list[str]:
    """Lista de problemas (vazia = pode iniciar). Cada item diz o que fazer."""
    problems: list[str] = []

    if not (BRIDGE_DIR / BRIDGE_SCRIPT).is_file():
        problems.append(f"{BRIDGE_SCRIPT} não encontrado em {BRIDGE_DIR}.")

    node = shutil.which("node")
    if not node:
        problems.append(
            "Node.js não encontrado no PATH. Instale o Node 20 ou superior "
            "(https://nodejs.org) e abra um terminal novo."
        )
    else:
        need = _required_node_major()
        have = _node_major(node)
        if have is None:
            problems.append("Não consegui descobrir a versão do Node (`node --version` falhou).")
        elif have < need:
            problems.append(f"Node {have} é antigo demais: o bridge precisa do Node {need} ou superior.")

    missing = _missing_dependencies()
    if missing:
        problems.append(
            "Dependências do bridge não instaladas (" + ", ".join(missing) + "). Rode:\n"
            "      cd mcp/whatsapp && npm install\n"
            "    (precisa do Git instalado: o Baileys baixa uma dependência por ele)"
        )
    return problems


# ── consulta ao bridge ────────────────────────────────────────────────────────

def _status(url: str) -> str | None:
    """Status reportado pelo bridge, ou None se ele não responde."""
    try:
        resp = requests.get(url.rstrip("/") + "/status", timeout=2)
        return resp.json().get("status") if resp.ok else None
    except (requests.RequestException, ValueError, AttributeError):
        return None


def bridge_reachable(url: str) -> bool:
    """
    True se algo responde em <url>/status. Diferente do bridge_status() do bot,
    'WhatsApp desconectado' conta como alcançável: o processo existe e está
    tentando reconectar, então não se inicia um segundo.
    """
    try:
        return requests.get(url.rstrip("/") + "/status", timeout=2).ok
    except requests.RequestException:
        return False


# ── processo ──────────────────────────────────────────────────────────────────

class Bridge:
    """Handle do processo do bridge iniciado por start_bridge()."""

    def __init__(self, proc: subprocess.Popen, url: str, foreground: bool):
        self.proc = proc
        self.url = url.rstrip("/")
        self.foreground = foreground

    def alive(self) -> bool:
        return self.proc.poll() is None

    def stop(self, timeout: float = STOP_TIMEOUT) -> None:
        """terminate() e, se não sair no prazo, kill()."""
        if self.proc.poll() is not None:
            return
        self.proc.terminate()
        try:
            self.proc.wait(timeout)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()

    def wait_ready(self, timeout: float, poll: float = 0.5, log: Log = _print) -> bool:
        """
        Espera o status 'connected'. True se conectou, False se estourou o prazo.
        Levanta BridgeError se o processo morrer antes. Se aparecer um QR
        (sessão expirada), o prazo é estendido para dar tempo de escanear.
        """
        deadline = time.monotonic() + timeout
        qr_seen = False
        while True:
            code = self.proc.poll()
            if code is not None:
                where = "acima" if self.foreground else "nas linhas [bridge] acima"
                raise BridgeError(
                    f"O bridge encerrou (código {code}) antes de conectar. "
                    f"Veja o motivo {where}. Porta em uso por outro programa é uma causa comum."
                )
            status = _status(self.url)
            if status == "connected":
                return True
            if status == "waiting_qr" and not qr_seen:
                qr_seen = True
                deadline = max(deadline, time.monotonic() + PAIRING_TIMEOUT)
                if not self.foreground:
                    log("[whatsapp] A sessão não está mais pareada: escaneie o QR mostrado acima.")
            if time.monotonic() >= deadline:
                return False
            time.sleep(poll)


def _forward_output(proc: subprocess.Popen, log: Log) -> None:
    """Encaminha a saída do bridge com o prefixo [bridge]. O prefixo é constante,
    então o QR continua alinhado e legível."""
    for raw in proc.stdout:
        line = raw.rstrip("\r\n")
        if not line.strip():
            continue
        log(line if line.startswith("[bridge]") else f"[bridge] {line}")


def start_bridge(bridge_url: str, webhook_port: int, foreground: bool = False, log: Log = _print) -> Bridge:
    """
    Inicia o bridge e devolve o handle (não espera conectar).
    foreground=True herda o terminal (QR inteiro, sem prefixo);
    False captura a saída e a encaminha com o prefixo [bridge].
    """
    problems = check_prerequisites()
    if problems:
        raise BridgeError(
            "Não dá para iniciar o bridge do WhatsApp:\n"
            + "\n".join(f"  - {p}" for p in problems)
            + "\n  (para rodar o bridge por conta própria, use --no-bridge)"
        )

    port = urlparse(bridge_url).port
    if port is None:
        raise BridgeError(f"bridge_url sem porta ({bridge_url!r}). Use algo como http://127.0.0.1:8765.")

    env = {
        **os.environ,
        "BRIDGE_PORT": str(port),
        "CIEL_WEBHOOK_URL": f"http://127.0.0.1:{webhook_port}/webhook",
    }
    cmd = [shutil.which("node"), BRIDGE_SCRIPT]
    common = dict(cwd=str(BRIDGE_DIR), env=env, stdin=subprocess.DEVNULL)

    try:
        if foreground:
            proc = subprocess.Popen(cmd, **common)
        else:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", bufsize=1, **common,
            )
            threading.Thread(target=_forward_output, args=(proc, log), daemon=True).start()
    except OSError as e:
        raise BridgeError(f"Não consegui iniciar o node: {e}") from e

    return Bridge(proc, bridge_url, foreground)


def ensure_bridge(bridge_url: str, webhook_port: int, log: Log = _print) -> Bridge | None:
    """
    Garante um bridge rodando. Devolve o Bridge iniciado (para o chamador
    encerrar no final) ou None quando não foi preciso iniciar nada.
    Levanta BridgeError se não der para subir.
    """
    url = bridge_url.rstrip("/")
    host = urlparse(url).hostname

    if host not in LOCAL_HOSTS:
        log(f"[whatsapp] bridge_url aponta para {host!r}, fora desta máquina: não vou iniciar o bridge.")
        return None

    if bridge_reachable(url):
        log(f"[whatsapp] Já há um bridge respondendo em {url}; vou usar esse.")
        return None

    paired = is_paired()
    if not paired:
        log(
            "[whatsapp] Primeiro pareamento: o bridge vai mostrar um QR neste terminal.\n"
            "           No celular: WhatsApp > Aparelhos conectados > Conectar um aparelho."
        )

    bridge = start_bridge(url, webhook_port, foreground=not paired, log=log)
    try:
        ready = bridge.wait_ready(READY_TIMEOUT if paired else PAIRING_TIMEOUT, log=log)
    except BaseException:           # inclui Ctrl+C durante a espera
        bridge.stop()
        raise

    if not ready:
        what = "conectar ao WhatsApp" if paired else "concluir o pareamento"
        log(f"[whatsapp] O bridge ainda não conseguiu {what}. Ele segue tentando; o bot fica no ar.")
    return bridge
