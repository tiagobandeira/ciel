"""Mostra na interface visual uma forma de partículas que ilustra o assunto (gera com o modelo secundário se ainda não existir)."""

import importlib
import json
import re
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SHAPES = _ROOT / "data" / "user" / "shapes"                     # cache das formas geradas (dados do usuário)
_BASE = _ROOT / "web" / "static" / "ui" / "shapes"                 # formas-base versionadas no repositório
_PROMPT = _ROOT / "prompts" / "forma_sistema.md"
_TIPOS = {"box", "cil", "esf", "anel", "arco", "linha", "svg"}
_BUILTIN = {"esfera", "circulo", "carro", "casa", "solar", "sorriso", "coracao", "check",
            "lupa", "documento", "lapis", "terminal", "rede"}


def _slug(t: str) -> str:
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")[:40] or "forma"


def _carrega(slug: str):
    """Spec da forma pelo nome: biblioteca-base primeiro, depois o cache do usuário. None se não existir."""
    for pasta in (_BASE, _SHAPES):
        arq = pasta / f"{slug}.json"
        if arq.exists():
            return json.loads(arq.read_text(encoding="utf-8"))
    return None


def _extrai(txt: str) -> dict:
    txt = re.sub(r"```(?:json)?", "", txt)
    txt = re.sub(r"(?<![\w.])\.(\d)", r"0.\1", txt)  # .5 -> 0.5
    i, j = txt.find("{"), txt.rfind("}")
    if i < 0 or j <= i:
        raise ValueError("resposta sem JSON")
    return json.loads(txt[i:j + 1])


def _num(x, lo=None, hi=None):
    """Converte para float finito, com limites opcionais. None se inválido (string, NaN, ±inf)."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if v != v or v in (float("inf"), float("-inf")):  # NaN / ±inf
        return None
    if lo is not None:
        v = max(lo, v)
    if hi is not None:
        v = min(hi, v)
    return v


def _valida(spec: dict) -> dict:
    partes = spec.get("partes")
    if not isinstance(partes, list) or not 1 <= len(partes) <= 24:
        raise ValueError("'partes' deve ser uma lista com 1 a 24 itens")
    for p in partes:
        if not isinstance(p, dict) or p.get("tipo") not in _TIPOS:
            raise ValueError(f"tipo de parte inválido: {p}")
        # "giro" numérico por parte (esf/anel/arco): órbita em torno da origem.
        # Inválido/vazio -> removido (o JS usa 0 por padrão).
        if "giro" in p:
            g = _num(p["giro"], lo=-3.0, hi=3.0)
            if g is None:
                p.pop("giro", None)
            else:
                p["giro"] = g
    nome = spec.get("nome")
    out = {
        "nome": nome if isinstance(nome, str) else "",
        "plano": bool(spec.get("plano")),
        "partes": partes,
    }
    # "pose":[inclinacao_x, giro_y_base] — inclina o conjunto e fixa a rotação base em Y.
    # Só aceita lista de exatamente 2 números; parcial é pior que nenhum.
    pose = spec.get("pose")
    if isinstance(pose, list) and len(pose) == 2:
        px = _num(pose[0], lo=-1.5, hi=1.5)
        py = _num(pose[1], lo=-2.0, hi=2.0)
        if px is not None and py is not None:
            out["pose"] = [px, py]
    # "giro" do objeto (topo): modo de rotação global do grupo.
    giro = spec.get("giro")
    if giro in ("y", "z", "none"):
        out["giro"] = giro
    return out


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
        try:
            spec, origem = _carrega(slug), "biblioteca"
            if spec is None:
                spec, origem = _gera(descricao or nome), "gerada"
                if descricao:
                    spec["desc"] = " ".join(descricao.split())[:100]  # alimenta a lista de formas do modo leitura
                _SHAPES.mkdir(parents=True, exist_ok=True)
                (_SHAPES / f"{slug}.json").write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            return f"Não foi possível mostrar a forma '{nome}': {e}"
    try:
        import ui_bus
        ui_bus.publish("forma", nome=slug, spec=spec)
    except Exception:
        pass
    return f"Forma '{slug}' exibida na interface ({origem})."