"""Anotação de formas para o modo leitura e live.

Leitura: o front manda as frases -> o secundário devolve marcadores (frase de início + forma) ->
as formas que faltam são geradas (cache em data/user/shapes) -> eventos SSE:
  "marcas"     {id, marcas:[{i, nome}]}
  "forma_lib"  {id, nome, spec}
Live: o front manda a resposta curta e o classificador local escolhe no máximo uma forma existente
(sem secundário e sem criar forma) -> mesmos eventos. O caminho pelo secundário continua disponível
com "ui_anotar.live_motor": "secundario" (gasta cota e ~8 s por chamada).
Se algo falhar, a leitura segue normal, só sem as trocas de forma.

Criação de formas novas é opcional: ciel_config.json -> "ui_anotar": {"criar_formas": true}.
Padrão (false): o modelo só escolhe entre formas que já existem (tópico sem forma boa fica sem marca).
"""
import importlib
import json
import re
import sys
import threading
import unicodedata
from datetime import datetime
from pathlib import Path

import ui_bus

_ROOT = Path(__file__).resolve().parent
_PROMPT = _ROOT / "prompts" / "marcadores_sistema.md"
_MAX_MARCAS = 6
_MAX_MARCAS_LIVE = 2
_MAX_FRASES = 150
_RESERVADAS = {"esfera", "circulo", "lupa", "documento", "lapis", "terminal", "rede"}
_SUFIXO_RESTRITO = (
    "\n\nMODO RESTRITO (vale mais que as regras acima sobre criar formas)\n"
    '- Use SOMENTE nomes que aparecem em "Formas existentes". Não crie formas novas.\n'
    "- Se nenhuma forma representar bem um tópico, não faça marca para ele.\n"
    '- O campo "desc" não é necessário.\n'
    '- Formato: {"marcas":[{"frase":N,"forma":"nome"}]}'
)
# Modo live: resposta curta e conversa. O objetivo é no máximo uma troca de forma por resposta,
# sem criação e sem gastar o secundário com tópicos que não combinam.
_SUFIXO_LIVE = (
    "\n\nMODO LIVE (resposta curta de conversa)\n"
    "- Escolha no máximo 2 formas para a resposta inteira.\n"
    "- Marque só quando a forma representar claramente o assunto; se nenhuma combinar, devolva {\"marcas\":[]}.\n"
    "- Prefira a frase 0 para a primeira forma; use a segunda só se o assunto mudar no meio.\n"
    "- Não crie formas: use apenas nomes de \"Formas existentes\".\n"
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


def _live_ligado() -> bool:
    """Flag ciel_config.json -> ui_anotar.live (padrão True): formas automáticas no modo live."""
    try:
        raw = json.loads((_ROOT / "ciel_config.json").read_text(encoding="utf-8"))
        return bool((raw.get("ui_anotar") or {}).get("live", True))
    except Exception:
        return True


def _motor_live() -> str:
    """ciel_config.json -> ui_anotar.live_motor: "heuristica" (padrão) ou "secundario"."""
    try:
        raw = json.loads((_ROOT / "ciel_config.json").read_text(encoding="utf-8"))
        return str((raw.get("ui_anotar") or {}).get("live_motor", "heuristica")).strip().lower()
    except Exception:
        return "heuristica"


# Palavras que não ajudam a distinguir assunto (já normalizadas, sem acento).
# As genéricas de geometria/descrição evitam que "linha" ou "tempo" escolham uma forma errada.
_STOP = set(
    "a o e de da do das dos que em no na nos nas um uma uns umas para por com sem sobre como se ao aos "
    "as os a as é sao foi ser esta este isso isto mais menos muito pouco ja nao sim tambem ainda cada "
    "seu sua seus suas pelo pela pelos pelas entre ate quando onde qual quais quem porque como "
    "tempo linha ponto marcas marca horizontal vertical simples pequena pequeno grande central "
    "esfera circulo forma formas parte lado dentro fora cima baixo redondo circular duas dois tres".split()
)

# Atalhos de assunto -> forma, para o classificador local. Peso 2,5 (entre o nome e a descrição).
# É uma tabela curta e conservadora; o ideal é que as descrições das formas cresçam com o tempo.
_ALIAS = {
    "nuvem": {"chuva", "previsao", "clima", "meteorologia"},
    "moeda": {"bolsa", "acao", "inflacao", "juros", "dinheiro", "financa", "economia"},
    "urna": {"eleicao", "voto", "votacao", "democracia"},
    "jornal": {"noticia", "manchete", "imprensa"},
    "linha-do-tempo": {"historia", "guerra", "seculo", "decada", "cronologia"},
    "monitor-com-codigo": {"codigo", "programacao", "software", "python"},
    "violao": {"musica", "cancao", "acorde"},
    "engrenagem": {"motor", "mecanica", "engenharia"},
    "solar": {"planeta", "espaco", "astronomia"},
    "galaxia": {"universo", "estrela", "cosmos"},
    "foguete": {"nasa", "lancamento", "astronauta"},
    "globo": {"mapa", "mundo"},
    "predio": {"cidade", "edificio", "empresa"},
    "livro": {"estudo", "leitura", "educacao", "aprender"},
    "chip": {"computador", "processador", "hardware", "eletronica"},
    "dna": {"gene", "genetica", "hereditariedade", "celula"},
    "arvore": {"planta", "natureza", "fotossintese"},
}


def _tokens(texto: str) -> set:
    """Conjunto de palavras normalizadas (sem acento, sem plural simples, sem stopwords)."""
    t = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode().lower()
    saida = set()
    for w in re.findall(r"[a-z0-9]{3,}", t):
        if w in _STOP:
            continue
        w = re.sub(r"oes$", "ao", w)   # eleições -> eleicao
        w = re.sub(r"aes$", "ao", w)
        if len(w) > 4 and w.endswith("s"):
            w = w[:-1]
        saida.add(w)
    return saida


def _marcas_local(mf, frases: list) -> list:
    """Classificador de live: escolhe no máximo uma forma existente pelo nome + descrição.

    Exige o nome da forma, um alias de assunto ou duas palavras da descrição, e não decide em
    caso de empate. Sem modelo, sem cota e em poucos milissegundos.
    """
    tt = _tokens(" ".join(frases))
    if not tt:
        return []
    melhor, pontos, empate = None, 0, False
    for nome in _existentes(mf):
        if nome in _RESERVADAS:
            continue
        base = _tokens(nome.replace("-", " "))
        desc = _tokens(_descricao(mf, nome))
        alias = _ALIAS.get(nome, set())
        score = 3 * len(tt & base) + len(tt & desc) + 2.5 * len(tt & alias)
        if score > pontos:
            melhor, pontos, empate = nome, score, False
        elif score == pontos and score >= 1:
            empate = True
    if not melhor or pontos < 1 or empate:
        return []
    return [{"i": 0, "nome": melhor, "desc": _descricao(mf, melhor) or melhor}]


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


def _marcas(mf, frases: list, criar: bool, live: bool = False) -> list:
    sm = _mod("tools.secondary_model")
    n = min(len(frases), _MAX_FRASES)
    lista = "\n".join(f"{i}: {frases[i][:160]}" for i in range(n) if frases[i])
    msg = f"Formas existentes:\n{_lista_formas(mf)}\n\nFrases:\n{lista}"
    system = _PROMPT.read_text(encoding="utf-8") + ("" if criar else _SUFIXO_RESTRITO)
    if live:
        system += _SUFIXO_LIVE
    limite = _MAX_MARCAS_LIVE if live else _MAX_MARCAS
    permitidas = set(_existentes(mf))
    resp = sm.run(msg, mode="text", session_id="marcas-" + datetime.now().strftime("%Y%m%d"), system=system)
    saida, ultima = [], -1
    for m in (mf._extrai(resp).get("marcas") or [])[:limite + 4]:
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
        if len(saida) >= limite:
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


def _publicar(aid, mf, marcas: list, criar: bool) -> None:
    """Publica as marcas e as specs das formas que o front ainda não tem."""
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


def _anotar_local(aid, frases: list) -> None:
    """Caminho do live: rápido e sem lock, para não esperar uma anotação do secundário."""
    try:
        if _ultimo["id"] != aid or not _live_ligado():
            return
        mf = _mod("tools.mostrar_forma")
        marcas = _marcas_local(mf, frases)
        _publicar(aid, mf, marcas, False)
    except Exception as e:
        ui_bus.publish("anotar_erro", id=aid, texto=str(e)[:120])


def anotar(aid, frases: list, live: bool = False) -> None:
    if live and _motor_live() != "secundario":
        _anotar_local(aid, frases)
        return
    with _lock:
        if _ultimo["id"] != aid:
            return
        try:
            if live and not _live_ligado():
                return
            mf = _mod("tools.mostrar_forma")
            criar = False if live else _criar_formas()  # no live o secundário só escolhe, não cria
            marcas = _marcas(mf, frases, criar, live)
            _publicar(aid, mf, marcas, criar)
        except Exception as e:
            ui_bus.publish("anotar_erro", id=aid, texto=str(e)[:120])


def iniciar(aid, frases: list, live: bool = False) -> None:
    _ultimo["id"] = aid
    threading.Thread(target=anotar, args=(aid, frases, live), daemon=True).start()