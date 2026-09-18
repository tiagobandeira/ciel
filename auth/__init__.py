# auth — módulo de autenticação do Ciel
# Usado por server.py; preparado para reuso em cli.py e ciel_tui.py.

from .manager import AuthManager

__all__ = ["AuthManager"]
