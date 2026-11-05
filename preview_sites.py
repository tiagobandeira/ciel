"""
preview_sites.py — servidores estáticos efêmeros para o visualizador do site.

Por que isso existe
-------------------
O painel do site precisa abrir uma página gerada com os arquivos irmãos
(`style.css`, `script.js`), `type="module"` e `localStorage`. Servir pelo
próprio Flask não resolve:

  - no mesmo origin do Ciel, a página alcançaria a API e o cookie da sessão;
  - num iframe com `sandbox` (origem opaca), os subrecursos saem sem cookie e
    o CSS/JS volta 401 — a página abre "crua" —, além de `localStorage` e
    `fetch()` local falharem.

Um servidor estático por pasta, em porta própria e com token no caminho, dá
origem separada (não fala com o Ciel) e ao mesmo tempo mantém tudo funcionando:
caminho relativo, `type="module"`, storage e fetch de arquivo vizinho.

Segurança
---------
  - escuta só em loopback, ou em 0.0.0.0 quando o site roda com `--lan`;
  - a raiz é sempre a pasta de um projeto dentro de `data/` (quem decide é o
    server, com o mesmo guard do `/download`);
  - todo request precisa do token no caminho (`/p/<token>/...`); sem ele é 404;
  - o caminho resolvido tem que ficar dentro da raiz (symlink não escapa);
  - sem listagem de diretório: quem lista é o navegador de arquivos do painel.
"""

from __future__ import annotations

import functools
import http.server
import secrets
import threading
import time
from pathlib import Path
from urllib.parse import quote

# teto de servidores vivos — cada projeto aberto ocupa uma porta
MAX_SITES = 8

_LOCK = threading.Lock()
_SITES: dict[str, dict] = {}


class _Handler(http.server.SimpleHTTPRequestHandler):
    """Serve a pasta configurada, somente sob /p/<token>/."""

    server_version = "CielPreview/1.0"
    protocol_version = "HTTP/1.1"

    # ── resolução de caminho ─────────────────────────────────────────────
    def translate_path(self, path: str) -> str:
        raiz = Path(self.directory or ".").resolve()
        limpo = path.split("?", 1)[0].split("#", 1)[0]
        partes = [p for p in limpo.split("/") if p not in ("", ".")]

        token = getattr(self.server, "ciel_token", "")
        if len(partes) < 2 or partes[0] != "p" or not secrets.compare_digest(partes[1], token):
            return str(raiz / "__token_invalido__")

        try:
            alvo = (raiz / "/".join(partes[2:])).resolve()
            alvo.relative_to(raiz)
        except (ValueError, OSError):
            return str(raiz / "__fora_da_raiz__")
        return str(alvo)

    # ── respostas ────────────────────────────────────────────────────────
    def list_directory(self, path):  # noqa: ARG002 - assinatura do stdlib
        self.send_error(404, "sem listagem")
        return None

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()

    def log_message(self, fmt, *args):  # silencia o log por request
        pass


def _encerrar(site: dict) -> None:
    try:
        site["httpd"].shutdown()
        site["httpd"].server_close()
    except Exception:
        pass


def iniciar(pasta: Path, host: str = "127.0.0.1") -> dict:
    """
    Garante um servidor estático para `pasta` e devolve o descritor.

    Reaproveita o servidor da mesma pasta; quando passa de MAX_SITES, derruba
    o mais antigo (o painel reabre e sobe outro na hora).
    """
    pasta = pasta.resolve()
    chave = str(pasta)

    with _LOCK:
        site = _SITES.get(chave)
        if site is not None:
            site["usado"] = time.time()
            return site

        while len(_SITES) >= MAX_SITES:
            antigo = min(_SITES.items(), key=lambda kv: kv[1]["usado"])[0]
            _encerrar(_SITES.pop(antigo))

        handler = functools.partial(_Handler, directory=chave)
        httpd = http.server.ThreadingHTTPServer((host, 0), handler)
        httpd.daemon_threads = True
        httpd.ciel_token = secrets.token_urlsafe(18)
        porta = int(httpd.server_address[1])

        thread = threading.Thread(
            target=httpd.serve_forever,
            name=f"ciel-preview-site-{porta}",
            daemon=True,
        )
        thread.start()

        site = {
            "httpd":    httpd,
            "porta":    porta,
            "token":    httpd.ciel_token,
            "pasta":    chave,
            "host":     host,
            "usado":    time.time(),
            "thread":   thread,
        }
        _SITES[chave] = site
        return site


def url_do(site: dict, host_visto: str, entrada: str = "") -> str:
    """URL pública do site, já com o token no caminho."""
    base = f"http://{host_visto}:{site['porta']}/p/{site['token']}/"
    return base + quote(entrada.lstrip("/"))


def ativos() -> dict[str, dict]:
    with _LOCK:
        return {chave: dict(site) for chave, site in _SITES.items()}


def parar_todos() -> None:
    with _LOCK:
        for site in list(_SITES.values()):
            _encerrar(site)
        _SITES.clear()
