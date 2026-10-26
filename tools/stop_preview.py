"""Encerra um servidor de preview iniciado por start_preview."""

from tools.preview_manager import stop as _stop


def run(preview_id: str = "", port: int = 0) -> str:
    """
    preview_id: id retornado por start_preview (ex.: preview-8765)
    port: alternativa ao id
    """
    return _stop(preview_id, port)
