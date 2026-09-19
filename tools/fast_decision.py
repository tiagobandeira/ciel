"""Decisão rápida via TypeSafe/Jev. O parâmetro questions DEVE ser string JSON: {"campo": {"type": "noul", "instructions": "É urgente?"}, "acao": {"type": "choice", "instructions": "Qual ação?", "criteria": {"op_a": "descrição a", "op_b": "descrição b"}}, "nivel": {"type": "score", "instructions": "Quão grave?", "criteria": ["Leve", "Moderado", "Grave"]}}. Regras: choice→criteria é dict {opção: descrição}; score→criteria é lista ordenada; noul→sem criteria. Nunca passe questions como dict Python, sempre como string JSON."""

REQUIREMENTS = ["typesafe-sdk"]
EXTRA = True
OUTPUT = "external"

import json
import os
import time
from pathlib import Path

_CONFIG_PATH = Path(__file__).parent.parent / "ciel_config.json"

_QUESTION_TYPES = ("noul", "choice", "score")

_HELP = """
Tipos de pergunta:
  noul   → sim/não com probabilidade. Retorna {"noul": 0.0..1.0}
  choice → escolhe uma opção de um conjunto. Retorna {"choice": "...", "probabilities": {...}}
  score  → pontua em escala de níveis ordenados. Retorna {"score": float, "legend": {...}}

Formato de 'questions' (JSON):
{
  "campo": {
    "type": "noul",
    "instructions": "A mensagem expressa urgência?"
  },
  "departamento": {
    "type": "choice",
    "instructions": "Qual equipe deve atender?",
    "criteria": {
      "billing": "Problemas de pagamento",
      "tech":    "Bugs ou integração"
    }
  },
  "frustração": {
    "type": "score",
    "instructions": "Nível de frustração do usuário",
    "criteria": ["Calmo", "Irritado", "Muito irritado"]
  }
}
""".strip()


def _load_config() -> dict:
    defaults = {"api_key_env": "TYPESAFE_API_KEY", "timeout": 10, "model": "jev-latest"}
    if _CONFIG_PATH.exists():
        try:
            raw = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
            ts  = raw.get("typesafe", {})
            defaults.update({k: v for k, v in ts.items() if v})
        except Exception:
            pass
    return defaults


def _get_api_key(cfg: dict) -> str | None:
    if _CONFIG_PATH.exists():
        try:
            raw = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
            key = raw.get("typesafe", {}).get("api_key", "")
            if key and not key.startswith("SUA_"):
                return key
        except Exception:
            pass
    return os.environ.get(cfg["api_key_env"]) or None


def _validate_questions(q: dict) -> str | None:
    """Retorna mensagem de erro ou None se válido."""
    for name, spec in q.items():
        if not isinstance(spec, dict):
            return f"Campo '{name}': deve ser um objeto com 'type' e 'instructions'."
        t = spec.get("type")
        if t not in _QUESTION_TYPES:
            return f"Campo '{name}': type deve ser 'noul', 'choice' ou 'score', recebido '{t}'."
        if not spec.get("instructions"):
            return f"Campo '{name}': 'instructions' é obrigatório."
        if t == "choice" and not isinstance(spec.get("criteria"), dict):
            return f"Campo '{name}' (choice): 'criteria' deve ser um dict {{opção: descrição}}."
        if t == "score" and not isinstance(spec.get("criteria"), list):
            return f"Campo '{name}' (score): 'criteria' deve ser uma lista de níveis ordenados."
    return None


def run(state: str, questions: str) -> str:
    """
    state: contexto atual em texto livre — tudo que o Jev precisa saber para decidir
    questions: string JSON com perguntas tipadas — NUNCA passe como dict Python, sempre serialize para str antes. Use questions='help' para ver formato e exemplos.
    """
    if questions.strip().lower() == "help":
        return _HELP

    cfg     = _load_config()
    api_key = _get_api_key(cfg)

    if not api_key:
        return (
            f"Erro: chave TypeSafe não encontrada. "
            f"Configure 'typesafe.api_key' em ciel_config.json "
            f"ou exporte {cfg['api_key_env']}."
        )

    # parse e validação das questions
    try:
        q_dict = json.loads(questions)
    except json.JSONDecodeError as e:
        return f"Erro: 'questions' não é JSON válido — {e}\n\nPasse questions='help' para ver o formato."

    if not isinstance(q_dict, dict) or not q_dict:
        return "Erro: 'questions' deve ser um objeto JSON com ao menos uma chave."

    err = _validate_questions(q_dict)
    if err:
        return f"Erro de formato: {err}\n\nPasse questions='help' para ver o formato completo."

    # chamada via SDK
    try:
        from typesafe_sdk import TypeSafeClient, Choice, Score, Noul
    except ImportError:
        return "Erro: typesafe-sdk não instalado. Execute: pip install typesafe-sdk"

    # constrói objetos tipados a partir do dict
    typed_questions = {}
    for name, spec in q_dict.items():
        t = spec["type"]
        instr = spec["instructions"]
        if t == "noul":
            typed_questions[name] = Noul(instructions=instr)
        elif t == "choice":
            typed_questions[name] = Choice(instructions=instr, criteria=spec["criteria"])
        elif t == "score":
            typed_questions[name] = Score(instructions=instr, criteria=spec["criteria"])

    try:
        client = TypeSafeClient(api_key=api_key)
        t0 = time.time()
        resp = client.system_one(
            state=state,
            questions=typed_questions,
            model=cfg.get("model", "jev-latest"),
        )
        latency_ms = int((time.time() - t0) * 1000)
    except Exception as e:
        msg = str(e)
        if "401" in msg or "Unauthorized" in msg:
            return "Erro: API key inválida (401)."
        if "429" in msg:
            return "Erro: rate limit atingido (429). Aguarde alguns segundos."
        return f"Erro na chamada TypeSafe: {e}"

    # serializa respostas
    out = {"model": cfg.get("model", "jev-latest"), "answers": {}, "_latency_ms": latency_ms}
    for name, ans in resp.answers.items():
        t = ans.type
        entry: dict = {"type": t}
        if t == "noul":
            entry["noul"] = ans.noul
        elif t == "choice":
            entry["choice"]        = ans.choice
            entry["probabilities"] = ans.probabilities
            entry["confidence"]    = ans.confidence
        elif t == "score":
            entry["score"]      = ans.score
            entry["legend"]     = ans.legend
            entry["confidence"] = ans.confidence
        out["answers"][name] = entry

    if hasattr(resp, "usage") and resp.usage:
        out["usage"] = {
            "input_tokens":  resp.usage.input_tokens,
            "output_tokens": resp.usage.output_tokens,
        }

    return json.dumps(out, ensure_ascii=False)