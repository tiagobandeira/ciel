"""Avalia expressões matemáticas (calculadora científica: trig, log, raiz, etc)."""

REQUIREMENTS = ["simpleeval>=1.0"]

import math
from simpleeval import SimpleEval

_MAX_EXPR_LEN = 500  # nenhuma calculadora de verdade precisa de mais que isso

_BASE = {
    "sqrt": math.sqrt, "log": math.log, "log10": math.log10, "log2": math.log2,
    "exp": math.exp, "factorial": math.factorial,
    "floor": math.floor, "ceil": math.ceil,
    "abs": abs, "round": round, "pow": pow,
}
_TRIG_RAD = {
    "sin": math.sin, "cos": math.cos, "tan": math.tan,
    "asin": math.asin, "acos": math.acos, "atan": math.atan,
}
_TRIG_DEG = {
    "sin": lambda x: math.sin(math.radians(x)),
    "cos": lambda x: math.cos(math.radians(x)),
    "tan": lambda x: math.tan(math.radians(x)),
    "asin": lambda x: math.degrees(math.asin(x)),
    "acos": lambda x: math.degrees(math.acos(x)),
    "atan": lambda x: math.degrees(math.atan(x)),
}
_NAMES = {"pi": math.pi, "e": math.e, "tau": math.tau}


def run(expression: str, mode: str = "rad") -> str:
    """
    expression: expressão matemática, ex: "sqrt(144) + sin(90) * 3"
    mode: 'rad' ou 'deg' — unidade angular usada por sin/cos/tan/asin/acos/atan (padrão 'rad')
    """
    if len(expression) > _MAX_EXPR_LEN:
        return f"Erro: expressão muito longa (máx {_MAX_EXPR_LEN} caracteres)."
    if mode not in ("rad", "deg"):
        return f"Erro: mode '{mode}' inválido. Use 'rad' ou 'deg'."
    try:
        functions = {**_BASE, **(_TRIG_DEG if mode == "deg" else _TRIG_RAD)}
        result = SimpleEval(functions=functions, names=_NAMES).eval(expression)
        if isinstance(result, float) and result.is_integer():
            result = int(result)
        return f"{expression} = {result} ({mode})"
    except Exception as e:
        return f"Erro ao avaliar '{expression}': {e}"
