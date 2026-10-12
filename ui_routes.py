"""Rotas da interface visual de partículas: página (/ui) e eventos em tempo real (/ui/events, SSE)."""
from pathlib import Path
from flask import Blueprint, Response, send_from_directory

import ui_bus

_UI_DIR = Path(__file__).resolve().parent / "web" / "static" / "ui"
bp = Blueprint("ui", __name__)


@bp.route("/ui")
def ui_index():
    return send_from_directory(_UI_DIR, "index.html")


@bp.route("/ui/events")
def ui_events():
    return Response(
        ui_bus.stream(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
