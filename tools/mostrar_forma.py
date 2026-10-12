"""Mostra na interface visual uma forma de partículas que ilustra o assunto (gera com o modelo secundário se ainda não existir)."""

import importlib
import json
import re
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SHAPES = _ROOT / "data" / "user" / "shapes"
_PROMPT = _ROOT / "prompts" / "forma_sistema.md"
_TIPOS = {"box", "cil", "esf", "anel", "arco", "linha", "svg"}
_BUILTIN = {"esfera", "circulo", "carro", "casa", "solar", "sorriso", "coracao", "check"}


def _slug(t: str) -> str:
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")[:40] or "forma"


def _extrai(txt: str) -> dict:
    txt = re.sub(r"```(?:json)?", "", txt)
    txt = re.sub(r"(?<![\w.])\.(\d)", r"0.\1", txt)  # .5 -> 0.5
    i, j = txt.find("{"), txt.rfind("}")
    if i < 0 or j <= i:
        raise ValueError("resposta sem JSON")
    return json.loads(txt[i:j + 1])


def _valida(spec: dict) -> dict:
    partes = spec.get("partes")
    if not isinstance(partes, list) or not 1 <= len(partes) <= 24:
        raise ValueError("'partes' deve ser uma lista com 1 a 24 itens")
    for p in partes:
        if not isinstance(p, dict) or p.get("tipo") not in _TIPOS:
            raise ValueError(f"tipo de parte inválido: {p}")
    return {"nome": spec.get("nome", ""), "partes": partes}


def _gera(descricao: str) -> dict:
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))
    sm = importlib.import_module("tools.secondary_model")
    system = _PROMPT.read_text(encoding="utf-8")
    sid = "formas-" + datetime.now().strftime("%Y%m%d")  # cota diária própria
    prompt = f"Gere a forma: {descricao}"
    erro = None
    for _ in range(2):
        resp = sm.run(prompt, mode="text", session_id=sid, system=system)
        try:
            return _valida(_extrai(resp))
        except Exception as e:
            erro = f"{e} | resposta: {str(resp)[:100]}"
            prompt = (f"Gere a forma: {descricao}\n\nSua resposta anterior falhou ({e}). "
                      "Responda apenas com o JSON válido.")
    raise RuntimeError(erro)


def run(nome: str, descricao: str = "") -> str:
    """
    nome: nome curto da forma (ex.: foguete, casa, sorriso)
    descricao: o que desenhar, caso a forma ainda não exista (opcional)
    """
    slug = _slug(nome)
    spec, origem = None, "interna"
    if slug not in _BUILTIN:
        arq = _SHAPES / f"{slug}.json"
        try:
            if arq.exists():
                spec, origem = json.loads(arq.read_text(encoding="utf-8")), "cache"
            else:
                spec, origem = _gera(descricao or nome), "gerada"
                _SHAPES.mkdir(parents=True, exist_ok=True)
                arq.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            return f"Não foi possível mostrar a forma '{nome}': {e}"
    try:
        import ui_bus
        ui_bus.publish("forma", nome=slug, spec=spec)
    except Exception:
        pass
    return f"Forma '{slug}' exibida na interface ({origem})."
