"""Lista os servidores de preview ativos."""

from tools.preview_manager import list_all as _list_all


def run() -> str:
    return _list_all()
