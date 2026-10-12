"""Rotas da interface visual de partículas: página (/ui), eventos SSE (/ui/events) e anotação de formas (/ui/anotar)."""
import time
from pathlib import Path
from flask import Blueprint, Response, jsonify, request, send_from_directory

import ui_anotar
import ui_bus

_UI_DIR = Path(__file__).resolve().parent / "web" / "static" / "ui"
bp = Blueprint("ui", __name__)

# No modo safe do Ciel só run_script/create_tool/create_temp_tool são bloqueadas; chamar o modelo
# (como o /api/chat) continua liberado. Por isso aqui não exigimos login, só um limite de frequência.
_ultimo_pedido = {"t": 0.0}


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


@bp.route("/ui/anotar", methods=["POST"])
def ui_anotar_rota():
    agora = time.monotonic()
    if agora - _ultimo_pedido["t"] < 2:
        return jsonify(ok=False, erro="aguarde um instante"), 429
    _ultimo_pedido["t"] = agora
    d = request.get_json(silent=True) or {}
    frases, aid = d.get("frases"), d.get("id")
    if (not isinstance(frases, list) or not 1 <= len(frases) <= 400
            or not all(isinstance(f, str) for f in frases) or not isinstance(aid, (int, str))):
        return jsonify(ok=False, erro="payload inválido"), 400
    ui_anotar.iniciar(aid, [f[:300] for f in frases])
    return jsonify(ok=True)