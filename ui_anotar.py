"""Anotação de formas para o modo leitura: escolhe, com o modelo secundário, a forma de cada trecho do texto.

Fluxo: o front manda as frases em leitura -> o secundário devolve marcadores (frase de início + forma) ->
as formas que faltam são geradas (cache em data/user/shapes) -> tudo chega ao front por eventos SSE:
  "marcas"     {id, marcas:[{i, nome}]}
  "forma_lib"  {id, nome, spec}     (formas internas do front não precisam de spec)
Se algo falhar, a leitura segue normal, só sem as trocas de forma.

Criação de formas novas é opcional: ciel_config.json -> "ui_anotar": {"criar_formas": true}.
Padrão (false): o modelo só escolhe entre formas que já existem (tópico sem forma boa fica sem marca).
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
_SUFIXO_RESTRITO = (
    "\n\nMODO RESTRITO (vale mais que as regras acima sobre criar formas)\n"
    '- Use SOMENTE nomes que aparecem em "Formas existentes". Não crie formas novas.\n'
    "- Se nenhuma forma representar bem um tópico, não faça marca para ele.\n"
    '- O campo "desc" não é necessário.\n'
    '- Formato: {"marcas":[{"frase":N,"forma":"nome"}]}'
)
_lock = threading.Lock()
_ultimo = {"id": None}  # só o pedido mais recente continua gastando o modelo


def _criar_formas() -> bool:
    """Flag ciel_config.json -> ui_anotar.criar_formas (padrão False). Lida a cada leitura, sem reiniciar."""
    try:
        raw = json.loads((_ROOT / "ciel_config.json").read_text(encoding="utf-8"))
        return bool((raw.get("ui_anotar") or {}).get("criar_formas", False))
    except Exception:
        return False


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


# Formas que só existem no index.html (sem JSON). Rascunho: edite à vontade. As demais internas
# (esfera, círculo, lupa, documento, lápis, terminal, rede) são reservadas e nem entram na lista.
_DESC_BUILTIN = {
    "carro": "carro; trânsito, transporte",
    "casa": "casa; moradia, imóveis",
    "solar": "sistema solar; espaço, astronomia",
    "sorriso": "rosto sorrindo; algo positivo, alegre",
    "coracao": "coração; amor, saúde",
    "check": "marca de verificação; concluído, correto, aprovado",
}


def _descricao(mf, nome: str) -> str:
    """Descrição curta da forma: campo "desc" do JSON (repo ou cache), senão o dicionário das internas, senão ""."""
    try:
        spec = mf._carrega(nome)
    except Exception:
        spec = None
    d = spec.get("desc") if isinstance(spec, dict) else None
    return " ".join(str(d).split())[:100] if d else _DESC_BUILTIN.get(nome, "")


def _lista_formas(mf) -> str:
    """Uma forma por linha: "- nome: descrição" (ou só "- nome" quando não há descrição)."""
    linhas = []
    for nome in _existentes(mf):
        d = _descricao(mf, nome)
        linhas.append(f"- {nome}: {d}" if d else f"- {nome}")
    return "\n".join(linhas)


def _marcas(mf, frases: list, criar: bool) -> list:
    sm = _mod("tools.secondary_model")
    n = min(len(frases), _MAX_FRASES)
    lista = "\n".join(f"{i}: {frases[i][:160]}" for i in range(n) if frases[i])
    msg = f"Formas existentes:\n{_lista_formas(mf)}\n\nFrases:\n{lista}"
    system = _PROMPT.read_text(encoding="utf-8") + ("" if criar else _SUFIXO_RESTRITO)
    permitidas = set(_existentes(mf))
    resp = sm.run(msg, mode="text", session_id="marcas-" + datetime.now().strftime("%Y%m%d"), system=system)
    saida, ultima = [], -1
    for m in (mf._extrai(resp).get("marcas") or [])[:_MAX_MARCAS + 4]:
        try:
            i, nome = int(m["frase"]), mf._slug(str(m["forma"]))
        except (KeyError, TypeError, ValueError):
            continue
        if not 0 <= i < n or i <= ultima:  # índice inventado, repetido ou fora de ordem
            continue
        if not criar and nome not in permitidas:  # modo restrito: forma que não existe é descartada
            continue
        saida.append({"i": i, "nome": nome, "desc": str(m.get("desc") or nome)[:120]})
        ultima = i
        if len(saida) >= _MAX_MARCAS:
            break
    return saida


def _forma(mf, nome: str, desc: str, criar: bool):
    """Spec da forma (None se for interna do front); gera e guarda no cache se ainda não existir."""
    if nome in mf._BUILTIN:
        return None
    spec = mf._carrega(nome)
    if spec is not None:
        return spec
    if not criar:
        return None
    spec = mf._gera(desc)
    if isinstance(spec, dict):
        spec["desc"] = " ".join(desc.split())[:100]  # entra na lista de formas das próximas leituras
    mf._SHAPES.mkdir(parents=True, exist_ok=True)
    (mf._SHAPES / f"{nome}.json").write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
    return spec


def anotar(aid, frases: list) -> None:
    with _lock:
        if _ultimo["id"] != aid:
            return
        try:
            mf = _mod("tools.mostrar_forma")
            criar = _criar_formas()
            marcas = _marcas(mf, frases, criar)
            ui_bus.publish("marcas", id=aid, marcas=[{"i": m["i"], "nome": m["nome"]} for m in marcas])
            vistos = set()
            for m in marcas:
                if m["nome"] in vistos:
                    continue
                vistos.add(m["nome"])
                if _ultimo["id"] != aid:  # o usuário já seguiu em frente
                    return
                try:
                    spec = _forma(mf, m["nome"], m["desc"], criar)
                except Exception:
                    continue
                if spec:
                    ui_bus.publish("forma_lib", id=aid, nome=m["nome"], spec=spec)
        except Exception as e:
            ui_bus.publish("anotar_erro", id=aid, texto=str(e)[:120])


def iniciar(aid, frases: list) -> None:
    _ultimo["id"] = aid
    threading.Thread(target=anotar, args=(aid, frases), daemon=True).start()