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

# O backend "xet" do HuggingFace grava log em %USERPROFILE%\.cache\huggingface\xet; em
# ambiente restrito (ou sem permissão nessa pasta) isso vira "acesso negado" no log, mesmo
# com o download funcionando. O download por HTTP normal resolve e evita o ruído.
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

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

# Medido na máquina de desenvolvimento (CPU, small/int8): a transcrição custa ~4 s por fala
# independentemente da duração (1 s ou 29 s), porque o encoder do Whisper sempre trabalha na
# janela de 30 s. Cortar silêncio ou encurtar o áudio não reduz esse custo; o que reduz é um
# modelo menor (base/tiny), GPU ou outro motor (ex.: Vosk, que é streaming).


def _cfg_voz() -> dict:
    """ciel_config.json -> "ui_voz".

    Chaves aceitas (todas opcionais):
      modelo, idioma, device, compute_type — como antes;
      cpu_threads   — threads do CTranslate2 (0 = automático);
      pasta_modelos — onde guardar o modelo (vazio = cache padrão do HuggingFace);
      preload       — carrega o modelo quando a página /ui abre (padrão true);
      sem_timestamps— transcreve sem timestamps por segmento (padrão true, mais rápido);
      beam_size     — 1 = mais rápido; 5 melhora números/acentos em troca de tempo;
      prompt_inicial— texto de contexto para o Whisper (padrão "").
    """
    try:
        cfg = json.loads((_ROOT / "ciel_config.json").read_text(encoding="utf-8")).get("ui_voz") or {}
    except Exception:
        cfg = {}
    try:
        threads = max(0, int(cfg.get("cpu_threads") or 0))
    except (TypeError, ValueError):
        threads = 0
    try:
        beam = max(1, min(10, int(cfg.get("beam_size") or 1)))
    except (TypeError, ValueError):
        beam = 1
    return {
        "modelo": cfg.get("modelo", "small"),
        "idioma": cfg.get("idioma", "pt"),
        "device": cfg.get("device", "auto"),
        "compute_type": cfg.get("compute_type", "int8"),
        "cpu_threads": threads,
        "pasta_modelos": str(cfg.get("pasta_modelos") or "").strip(),
        "preload": bool(cfg.get("preload", True)),
        "sem_timestamps": bool(cfg.get("sem_timestamps", True)),
        "beam_size": beam,
        "prompt_inicial": str(cfg.get("prompt_inicial") or ""),
    }


def _chave_modelo(cfg: dict) -> tuple:
    return (cfg["modelo"], cfg["device"], cfg["compute_type"], cfg["cpu_threads"])


def _carrega_modelo(cfg: dict) -> tuple:
    """Carrega o modelo se a config mudou. Devolve (modelo, ms_de_carga). Exige _voz_lock."""
    from faster_whisper import WhisperModel  # import tardio: só quem usa voz precisa instalar
    chave = _chave_modelo(cfg)
    if _whisper["modelo"] is not None and _whisper["chave"] == chave:
        return _whisper["modelo"], 0
    t0 = time.monotonic()
    extras = {}
    if cfg["cpu_threads"]:
        extras["cpu_threads"] = cfg["cpu_threads"]
    if cfg["pasta_modelos"]:
        # cache do modelo dentro do projeto: evita o acesso negado em %USERPROFILE%\.cache
        # quando o servidor roda em sandbox/ambiente restrito
        pasta = Path(cfg["pasta_modelos"])
        if not pasta.is_absolute():
            pasta = _ROOT / pasta
        pasta.mkdir(parents=True, exist_ok=True)
        extras["download_root"] = str(pasta)
    _whisper["modelo"] = WhisperModel(
        cfg["modelo"], device=cfg["device"], compute_type=cfg["compute_type"], num_workers=1, **extras)
    _whisper["chave"] = chave
    return _whisper["modelo"], int((time.monotonic() - t0) * 1000)


def precarregar() -> None:
    """Chamado quando /ui abre: deixa o modelo pronto antes de o usuário apertar Falar.

    É best-effort: sem faster-whisper instalado (ou com erro de download) a página abre igual
    e o /ui/voz devolve o erro de sempre.
    """
    if not _cfg_voz()["preload"]:
        return
    try:
        with _voz_lock:
            _carrega_modelo(_cfg_voz())
    except Exception:
        pass


def _transcrever(dados: bytes, sufixo: str, inicio: float = 0.0) -> dict:
    """Motor de voz de entrada. Para trocar por outro motor (API, outro modelo), reescreva só esta função.

    `inicio` (segundos) corta o começo do áudio. O modo live usa isso quando o usuário fala por
    cima do Ciel: a gravação começa junto com o TTS, mas só a parte depois da interrupção entra
    na transcrição (menos 0,3 s de pré-roll para não perder a primeira sílaba).

    Devolve {"texto", "ms_carga", "ms_transcricao", "audio_s"}.
    """
    cfg = _cfg_voz()
    t_total = time.monotonic()
    with _voz_lock:  # um áudio por vez; o modelo é carregado na primeira chamada
        modelo, ms_carga = _carrega_modelo(cfg)
        fd, caminho = tempfile.mkstemp(suffix=sufixo)
        t_tx = time.monotonic()
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(dados)
            opcoes = dict(
                language=cfg["idioma"] or None,
                beam_size=cfg["beam_size"],
                best_of=1,
                vad_filter=True,
                without_timestamps=cfg["sem_timestamps"],
                condition_on_previous_text=False,
                initial_prompt=cfg["prompt_inicial"] or None,
            )
            if inicio > 0.05:
                from faster_whisper.audio import decode_audio
                audio = decode_audio(caminho, sampling_rate=16000)
                audio = audio[max(0, int((inicio - 0.3) * 16000)):]
                duracao = len(audio) / 16000.0
                if audio.size:
                    segmentos, _ = modelo.transcribe(audio, **opcoes)
                else:
                    segmentos = []
            else:
                segmentos, info = modelo.transcribe(caminho, **opcoes)
                duracao = float(getattr(info, "duration", 0) or 0)
            texto = " ".join(seg.text.strip() for seg in segmentos).strip()
            return {
                "texto": texto,
                "ms_carga": ms_carga,
                "ms_transcricao": int((time.monotonic() - t_tx) * 1000),
                "ms_total": int((time.monotonic() - t_total) * 1000),
                "audio_s": round(duracao, 2),
            }
        finally:
            try:
                os.remove(caminho)
            except OSError:
                pass


@bp.route("/ui")
def ui_index():
    # carrega o Whisper em segundo plano enquanto a página monta: o botão Falar já encontra
    # o modelo pronto (a carga leva vários segundos e antes caía no primeiro pedido de voz).
    threading.Thread(target=precarregar, daemon=True).start()
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
    live = bool(d.get("live", False))
    if (not isinstance(frases, list) or not 1 <= len(frases) <= 400
            or not all(isinstance(f, str) for f in frases) or not isinstance(aid, (int, str))):
        return jsonify(ok=False, erro="payload inválido"), 400
    ui_anotar.iniciar(aid, [f[:300] for f in frases], live)
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
        inicio = max(0.0, min(600.0, float(request.args.get("inicio") or 0)))
    except (TypeError, ValueError):
        inicio = 0.0
    try:
        r = _transcrever(dados, _SUFIXOS.get(tipo, ".webm"), inicio)
    except ImportError:
        return jsonify(ok=False, erro="faster-whisper não instalado (pip install faster-whisper)"), 501
    except Exception as e:
        return jsonify(ok=False, erro=f"falha ao transcrever: {str(e)[:120]}"), 500
    # tempos por etapa: aparecem no console (e na linha de debug) do front para medir a latência
    return jsonify(
        ok=True,
        texto=r["texto"],
        audio_s=r["audio_s"],
        inicio=inicio,
        ms={"carga": r["ms_carga"], "transcricao": r["ms_transcricao"], "total": r["ms_total"]},
    )