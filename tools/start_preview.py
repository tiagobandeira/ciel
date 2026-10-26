"""Inicia um servidor de preview estático para uma pasta do workspace."""

PERMISSIONS = {"path": "read"}

from tools.preview_manager import start as _start


def run(path: str, port: int = 8765) -> str:
    """
    path: pasta a servir (ex.: data/user/app_web)
    port: porta local (127.0.0.1); 0 escolhe uma livre
    """
    return _start(path, port)
