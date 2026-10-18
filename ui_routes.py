"""Rotas da interface visual de partículas: página (/ui), eventos SSE (/ui/events), anotação de formas (/ui/anotar)
e voz (/ui/voz: áudio do microfone -> texto, com Whisper local)."""
import json
import os
import tempfile
import threading
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

# ── voz: motor local (faster-whisper, dependência opcional) ──────────────────────────────────────────────
_ROOT = Path(__file__).resolve().parent
_VOZ_MAX_BYTES = 8 * 1024 * 1024
_SUFIXOS = {"webm": ".webm", "ogg": ".ogg", "mp4": ".mp4", "mpeg": ".mp3", "wav": ".wav", "x-wav": ".wav", "m4a": ".m4a"}
_voz_lock = threading.Lock()
_whisper = {"modelo": None, "chave": None}
_ultimo_voz = {"t": 0.0}


def _cfg_voz() -> dict:
    """ciel_config.json -> "ui_voz": {"modelo": "small", "idioma": "pt", "device": "auto", "compute_type": "int8"}"""
    try:
        cfg = json.loads((_ROOT / "ciel_config.json").read_text(encoding="utf-8")).get("ui_voz") or {}
    except Exception:
        cfg = {}
    return {"modelo": cfg.get("modelo", "small"), "idioma": cfg.get("idioma", "pt"),
            "device": cfg.get("device", "auto"), "compute_type": cfg.get("compute_type", "int8")}


def _transcrever(dados: bytes, sufixo: str) -> str:
    """Motor de voz de entrada. Para trocar por outro motor (API, outro modelo), reescreva só esta função."""
    from faster_whisper import WhisperModel  # import tardio: só quem usa voz precisa instalar
    cfg = _cfg_voz()
    chave = (cfg["modelo"], cfg["device"], cfg["compute_type"])
    with _voz_lock:  # um áudio por vez; o modelo é carregado na primeira chamada
        if _whisper["chave"] != chave:
            _whisper["modelo"] = WhisperModel(cfg["modelo"], device=cfg["device"], compute_type=cfg["compute_type"])
            _whisper["chave"] = chave
        fd, caminho = tempfile.mkstemp(suffix=sufixo)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(dados)
            segmentos, _ = _whisper["modelo"].transcribe(
                caminho, language=cfg["idioma"] or None, beam_size=1, vad_filter=True)
            return " ".join(seg.text.strip() for seg in segmentos).strip()
        finally:
            try:
                os.remove(caminho)
            except OSError:
                pass


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


@bp.route("/ui/voz", methods=["POST"])
def ui_voz():
    """Corpo = áudio bruto do MediaRecorder (webm/ogg/mp4...). Devolve {ok, texto}."""
    if (request.content_length or 0) > _VOZ_MAX_BYTES:
        return jsonify(ok=False, erro="áudio grande demais"), 413
    agora = time.monotonic()
    if agora - _ultimo_voz["t"] < 1:
        return jsonify(ok=False, erro="aguarde um instante"), 429
    _ultimo_voz["t"] = agora
    dados = request.get_data(cache=False)
    if not dados:
        return jsonify(ok=False, erro="áudio vazio"), 400
    tipo = (request.content_type or "").split(";")[0].split("/")[-1].strip().lower()
    try:
        texto = _transcrever(dados, _SUFIXOS.get(tipo, ".webm"))
    except ImportError:
        return jsonify(ok=False, erro="faster-whisper não instalado (pip install faster-whisper)"), 501
    except Exception as e:
        return jsonify(ok=False, erro=f"falha ao transcrever: {str(e)[:120]}"), 500
    return jsonify(ok=True, texto=texto)