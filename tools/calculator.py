"""Realiza operações matemáticas básicas: soma, subtração, multiplicação, divisão e potência."""


def run(operation: str, a: float, b: float) -> str:
    """
    operation: 'add' | 'subtract' | 'multiply' | 'divide' | 'power'
    a: primeiro número
    b: segundo número
    """
    ops = {
        "add":      ("+", lambda a, b: a + b),
        "subtract": ("-", lambda a, b: a - b),
        "multiply": ("*", lambda a, b: a * b),
        "divide":   ("/", lambda a, b: a / b),
        "power":    ("^", lambda a, b: a ** b),
    }

    if operation not in ops:
        return f"Erro: operation '{operation}' inválida. Use: {list(ops.keys())}"

    if operation == "divide" and b == 0:
        return "Erro: divisão por zero."

    symbol, fn = ops[operation]
    result = fn(a, b)

    # remove .0 se o resultado for inteiro
    result_str = str(int(result)) if isinstance(result, float) and result.is_integer() else str(result)

    return f"{a} {symbol} {b} = {result_str}"
