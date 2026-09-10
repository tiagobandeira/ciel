"""
image_input.py - Parsing de input com imagem para o Ciel CLI.

Suporta paths Windows (com barras invertidas e espacos no nome),
paths Unix e paths entre aspas duplas. O path pode aparecer no
inicio, meio ou fim do input.

Exports:
  parse_image_input(user_input)   -> (texto, image_b64 | None)
  parse_image_command(user_input) -> (texto, image_b64) | None
  format_image_hint(path, texto)  -> str
  IMAGE_EXTENSIONS
"""

import base64
import re
from pathlib import Path

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}


def _is_image_path(token: str) -> bool:
    return Path(token).suffix.lower() in IMAGE_EXTENSIONS


def _load_image(path: str) -> str | None:
    try:
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode()
    except (OSError, IOError):
        return None


def _find_image_in_tokens(tokens: list[str]) -> tuple[int, int, str] | None:
    """
    Varre todas as janelas possiveis de tokens tentando montar um path de
    imagem existente em disco. Prefere janelas maiores (path mais longo).

    Retorna (start_idx, end_idx_exclusive, path_str) ou None.

    Ex: tokens = ["olha", "Captura", "de", "tela", "2026.png", "analise"]
        testa "olha Captura de tela 2026.png analise" -> nao existe
        testa "olha Captura de tela 2026.png" -> nao existe
        ...
        testa "Captura de tela 2026.png" -> EXISTE -> retorna (1, 5, "Captura de tela 2026.png")
    """
    n = len(tokens)
    # varre todas as janelas: tamanho decrescente para pegar o path mais longo
    for size in range(n, 0, -1):
        for start in range(0, n - size + 1):
            candidate = " ".join(tokens[start : start + size])
            if _is_image_path(candidate) and Path(candidate).exists():
                return start, start + size, candidate
    return None


def _find_quoted_image(text: str) -> tuple[str, str] | None:
    """
    Procura por "path entre aspas" com extensao de imagem no texto.
    Retorna (path, texto_sem_o_trecho) ou None.
    """
    pattern = re.compile(r'"([^"]+)"')
    for m in pattern.finditer(text):
        candidate = m.group(1)
        if _is_image_path(candidate) and Path(candidate).exists():
            remaining = (text[:m.start()] + text[m.end():]).strip()
            return candidate, remaining
    return None


def parse_image_input(user_input: str) -> tuple[str, str | None]:
    """
    Detecta imagem inline no input normal (sem /img).
    O path pode estar em qualquer posicao e ter espacos no nome.

    Retorna (texto_sem_path, image_b64) ou (user_input, None).
    """
    stripped = user_input.strip()
    if not stripped:
        return stripped, None

    # 1. Tenta path entre aspas primeiro (mais preciso)
    quoted = _find_quoted_image(stripped)
    if quoted:
        path, remaining = quoted
        image_b64 = _load_image(path)
        if image_b64:
            return remaining, image_b64

    # 2. Sem aspas: varre janelas de tokens
    tokens = stripped.split(" ")
    result = _find_image_in_tokens(tokens)
    if result:
        start, end, path = result
        remaining_tokens = tokens[:start] + tokens[end:]
        remaining = " ".join(remaining_tokens).strip()
        image_b64 = _load_image(path)
        if image_b64:
            return remaining, image_b64

    return stripped, None


def _split_path_and_text(rest: str) -> tuple[str, str]:
    """
    Para uso no parse_image_command: divide 'rest' em (path, texto).
    O path vem ANTES do texto, entao so precisa acumular tokens do inicio.
    """
    rest = rest.strip()

    # caso 1: path entre aspas duplas
    if rest.startswith('"'):
        end = rest.find('"', 1)
        if end != -1:
            return rest[1:end], rest[end + 1:].strip()
        return rest[1:], ""

    # caso 2: acumula tokens do inicio, do maior para o menor
    tokens = rest.split(" ")
    for i in range(len(tokens), 0, -1):
        candidate = " ".join(tokens[:i])
        if _is_image_path(candidate) and Path(candidate).exists():
            texto = " ".join(tokens[i:]).strip()
            return candidate, texto

    parts = rest.split(None, 1)
    return parts[0], parts[1].strip() if len(parts) > 1 else ""


def parse_image_command(user_input: str) -> tuple[str, str | None] | None:
    """
    Processa /img e /imagem.

    Retorna:
      None         - nao e comando de imagem
      (texto, b64) - sucesso
      (None, None) - comando reconhecido mas path invalido/nao encontrado
    """
    lower = user_input.strip().lower()
    if not (lower.startswith("/img ") or lower.startswith("/imagem ")):
        return None

    parts = user_input.split(None, 1)
    rest  = parts[1].strip() if len(parts) > 1 else ""
    if not rest:
        return None, None

    path_token, texto = _split_path_and_text(rest)

    if not _is_image_path(path_token) or not Path(path_token).exists():
        return None, None

    image_b64 = _load_image(path_token)
    if image_b64 is None:
        return None, None

    return texto, image_b64


def format_image_hint(path: str, texto: str) -> str:
    name = Path(path).name
    return f"[imagem: {name}] {texto}" if texto else f"[imagem: {name}]"