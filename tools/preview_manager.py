"""Gerencia servidores de preview estáticos locais (127.0.0.1)."""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

STATE_DIR = Path("data/preview")
STATE_FILE = STATE_DIR / "previews.json"
_LOCK = threading.Lock()


def _load_state() -> dict:
    try:
        if STATE_FILE.exists():
            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except Exception:
        pass
    return {}


def _save_state(state: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STATE_FILE)


def _pid_alive(pid: int) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def _wait_http(url: str, timeout: float = 6.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.0) as resp:
                if 200 <= resp.status < 500:
                    return True
        except Exception:
            time.sleep(0.15)
    return False


def start(path: str, port: int = 8765) -> str:
    directory = Path(path).expanduser().resolve()
    if not directory.is_dir():
        return f"Erro: pasta de preview não encontrada: {path}"

    try:
        selected_port = int(port or 0)
    except (TypeError, ValueError):
        return "Erro: porta inválida."
    if selected_port <= 0:
        selected_port = _free_port()
    if selected_port > 65535:
        return "Erro: porta fora do intervalo."
    if not _port_free(selected_port):
        return f"Erro: porta {selected_port} já está em uso."

    with _LOCK:
        state = _load_state()
        for preview_id, info in state.items():
            if (
                info.get("path") == str(directory)
                and int(info.get("port", 0)) == selected_port
                and _pid_alive(int(info.get("pid", 0)))
            ):
                url = info.get("url") or f"http://127.0.0.1:{selected_port}/"
                return f"Preview já ativo: {url} ({preview_id})"

        STATE_DIR.mkdir(parents=True, exist_ok=True)
        log_path = STATE_DIR / f"preview-{selected_port}.log"
        log = log_path.open("a", encoding="utf-8")
        command = [
            sys.executable, "-m", "http.server",
            str(selected_port), "--bind", "127.0.0.1",
        ]
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        try:
            proc = subprocess.Popen(
                command,
                cwd=str(directory),
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=flags,
            )
        except Exception as exc:
            log.close()
            return f"Erro ao iniciar preview: {exc}"
        finally:
            try:
                log.close()
            except Exception:
                pass

        url = f"http://127.0.0.1:{selected_port}/"
        if not _wait_http(url):
            try:
                proc.terminate()
            except Exception:
                pass
            return f"Erro: preview não respondeu em {url}."

        preview_id = f"preview-{selected_port}"
        state[preview_id] = {
            "pid": proc.pid,
            "port": selected_port,
            "path": str(directory),
            "url": url,
            "log": str(log_path),
            "started": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        _save_state(state)
        return f"Preview ativo: {url} (id={preview_id}, pid={proc.pid})"


def stop(preview_id: str = "", port: int = 0) -> str:
    with _LOCK:
        state = _load_state()
        target_id = (preview_id or "").strip()
        if not target_id and port:
            target_id = f"preview-{int(port)}"
        if not target_id:
            return "Erro: informe preview_id ou port."
        info = state.pop(target_id, None)
        if info is None:
            _save_state(state)
            return f"Preview '{target_id}' não encontrado."

        pid = int(info.get("pid", 0) or 0)
        if pid:
            try:
                os.kill(pid, signal.SIGTERM)
            except Exception:
                pass
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline and _pid_alive(pid):
                time.sleep(0.15)
            if _pid_alive(pid):
                try:
                    os.kill(pid, signal.SIGKILL)
                except Exception:
                    pass
        _save_state(state)
        return f"Preview encerrado: {target_id}"


def active() -> dict:
    """Devolve os previews vivos, removendo entradas mortas do estado."""
    with _LOCK:
        state = _load_state()
        alive = {
            preview_id: info
            for preview_id, info in state.items()
            if _pid_alive(int(info.get("pid", 0)))
        }
        if alive != state:
            _save_state(alive)
    return alive


def list_all() -> str:
    alive = active()
    if not alive:
        return "Nenhum preview ativo."
    lines = ["Previews ativos:"]
    for preview_id, info in sorted(alive.items()):
        lines.append(
            f"- {preview_id}: {info.get('url')} "
            f"(pid={info.get('pid')}, {info.get('path')})"
        )
    return "\n".join(lines)
