"""Anotação de formas para o modo leitura: escolhe, com o modelo secundário, a forma de cada trecho do texto.

Fluxo: o front manda as frases em leitura -> o secundário devolve marcadores (frase de início + forma) ->
as formas que faltam são geradas (cache em data/user/shapes) -> tudo chega ao front por eventos SSE:
  "marcas"     {id, marcas:[{i, nome}]}
  "forma_lib"  {id, nome, spec}     (formas internas do front não precisam de spec)
Se algo falhar, a leitura segue normal, só sem as trocas de forma.
"""
import importlib
import json
import sys
import threading
from datetime import datetime
from pathlib import Path

import ui_bus

_ROOT = Path(__file__).resolve().parent
_PROMPT = _ROOT / "prompts" / "marcadores_sistema.md"
_MAX_MARCAS = 6
_MAX_FRASES = 150
_RESERVADAS = {"esfera", "circulo", "lupa", "documento", "lapis", "terminal", "rede"}
_lock = threading.Lock()
_ultimo = {"id": None}  # só o pedido mais recente continua gastando o modelo


def _mod(nome: str):
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))
    return importlib.import_module(nome)


def _existentes(mf) -> list:
    # formas de tool (lupa, terminal...) e de estado (esfera, círculo) ficam fora: têm significado próprio
    nomes = set(mf._BUILTIN) - _RESERVADAS
    for pasta in (mf._BASE, mf._SHAPES):
        if pasta.exists():
            nomes |= {p.stem for p in pasta.glob("*.json")}
    return sorted(nomes)


def _marcas(mf, frases: list) -> list:
    sm = _mod("tools.secondary_model")
    n = min(len(frases), _MAX_FRASES)
    lista = "\n".join(f"{i}: {frases[i][:160]}" for i in range(n) if frases[i])
    msg = f"Formas existentes: {', '.join(_existentes(mf))}\n\nFrases:\n{lista}"
    resp = sm.run(msg, mode="text", session_id="marcas-" + datetime.now().strftime("%Y%m%d"),
                  system=_PROMPT.read_text(encoding="utf-8"))
    saida, ultima = [], -1
    for m in (mf._extrai(resp).get("marcas") or [])[:_MAX_MARCAS + 4]:
        try:
            i, nome = int(m["frase"]), mf._slug(str(m["forma"]))
        except (KeyError, TypeError, ValueError):
            continue
        if not 0 <= i < n or i <= ultima:  # índice inventado, repetido ou fora de ordem
            continue
        saida.append({"i": i, "nome": nome, "desc": str(m.get("desc") or nome)[:120]})
        ultima = i
        if len(saida) >= _MAX_MARCAS:
            break
    return saida


def _forma(mf, nome: str, desc: str):
    """Spec da forma (None se for interna do front); gera e guarda no cache se ainda não existir."""
    if nome in mf._BUILTIN:
        return None
    spec = mf._carrega(nome)
    if spec is not None:
        return spec
    spec = mf._gera(desc)
    mf._SHAPES.mkdir(parents=True, exist_ok=True)
    (mf._SHAPES / f"{nome}.json").write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
    return spec


def anotar(aid, frases: list) -> None:
    with _lock:
        if _ultimo["id"] != aid:
            return
        try:
            mf = _mod("tools.mostrar_forma")
            marcas = _marcas(mf, frases)
            ui_bus.publish("marcas", id=aid, marcas=[{"i": m["i"], "nome": m["nome"]} for m in marcas])
            vistos = set()
            for m in marcas:
                if m["nome"] in vistos:
                    continue
                vistos.add(m["nome"])
                if _ultimo["id"] != aid:  # o usuário já seguiu em frente
                    return
                try:
                    spec = _forma(mf, m["nome"], m["desc"])
                except Exception:
                    continue
                if spec:
                    ui_bus.publish("forma_lib", id=aid, nome=m["nome"], spec=spec)
        except Exception as e:
            ui_bus.publish("anotar_erro", id=aid, texto=str(e)[:120])


def iniciar(aid, frases: list) -> None:
    _ultimo["id"] = aid
    threading.Thread(target=anotar, args=(aid, frases), daemon=True).start()
