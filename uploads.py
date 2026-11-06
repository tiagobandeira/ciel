"""
uploads.py — anexos do chat salvos em `data/user/uploads/<id>/`.

O chat não manda o arquivo inteiro para o orquestrador: ele recebe só uma
prévia (~2k chars) e o caminho. O arquivo fica em disco para o modelo ler
trechos sob demanda (`read_file`) ou passar em `secondary_model(files=[...])`,
sem o conteúdo passar pelo contexto do orquestrador.

O índice (`uploads.json`) guarda nome, tipo, caminho, tamanho, nº de páginas,
prévia e a sessão dona (para limpar junto da sessão).
"""

from __future__ import annotations

import io
import json
import re
import secrets
import threading
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PASTA = ROOT / "data" / "user" / "uploads"
INDICE = PASTA / "uploads.json"

MAX_BYTES = 25 * 1024 * 1024       # 25 MB por anexo
PREVIA_CHARS = 2_000
MAX_ORFAOS_DIAS = 7
MAX_POR_MENSAGEM = 5

_LOCK = threading.Lock()

_TIPOS = {
    ".pdf": "pdf", ".docx": "docx",
    ".md": "md", ".markdown": "md", ".txt": "txt", ".csv": "csv",
    ".json": "json", ".py": "py", ".js": "js", ".ts": "ts",
    ".html": "html", ".css": "css", ".xml": "xml",
    ".yaml": "yaml", ".yml": "yaml", ".sql": "sql",
}


def _nome_seguro(nome: str) -> str:
    nome = Path(str(nome or "")).name.strip()
    nome = re.sub(r"[\x00-\x1f<>:\"/\\|?*]", "_", nome).strip(" .")
    return (nome or "arquivo")[:120]


def _texto_pdf(dados: bytes) -> tuple[str, int]:
    try:
        from PyPDF2 import PdfReader
    except ImportError as e:  # pragma: no cover - ambiente sem PyPDF2
        raise ValueError("PyPDF2 não instalado (pip install -r requirements.txt)") from e

    leitor = PdfReader(io.BytesIO(dados))
    partes = []
    for pagina in leitor.pages:
        try:
            partes.append(pagina.extract_text() or "")
        except Exception:
            partes.append("")
    texto = "\n\n".join(partes).strip()
    if not texto:
        raise ValueError(
            "PDF sem texto extraível (digitalizado?). Para esse caso, converta "
            "para texto ou indexe em Fontes."
        )
    return texto, len(leitor.pages)


def _texto_docx(dados: bytes) -> str:
    try:
        import docx
    except ImportError as e:  # pragma: no cover - ambiente sem python-docx
        raise ValueError("python-docx não instalado; converta o .docx em .txt/.md") from e

    documento = docx.Document(io.BytesIO(dados))
    return "\n".join(p.text for p in documento.paragraphs).strip()


def _texto_puro(dados: bytes) -> str:
    for codec in ("utf-8", "cp1252"):
        try:
            texto = dados.decode(codec)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError("não parece texto (codificação desconhecida)")

    if "\x00" in texto or texto.count("\ufffd") > max(10, len(texto) * 0.01):
        raise ValueError("arquivo binário — anexe PDF, DOCX ou texto")
    return texto


def extrair(nome: str, dados: bytes) -> tuple[str, str, int]:
    """
    Texto do arquivo + tipo + nº de páginas (0 quando não se aplica).

    PDF/DOCX são extraídos em memória; o arquivo original fica no disco para
    leitura sob demanda.
    """
    ext = Path(nome).suffix.lower()
    tipo = _TIPOS.get(ext, "arquivo")
    if ext == ".pdf":
        texto, paginas = _texto_pdf(dados)
        return texto, tipo, paginas
    if ext == ".docx":
        return _texto_docx(dados), tipo, 0
    return _texto_puro(dados), tipo, 0


def _ler_indice() -> dict:
    try:
        dados = json.loads(INDICE.read_text(encoding="utf-8"))
        return dados if isinstance(dados, dict) else {}
    except (OSError, ValueError):
        return {}


def _gravar_indice(dados: dict) -> None:
    INDICE.parent.mkdir(parents=True, exist_ok=True)
    tmp = INDICE.with_suffix(".tmp")
    tmp.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(INDICE)


def salvar(nome: str, dados: bytes, sessao=None) -> dict:
    """
    Grava o anexo e devolve o descritor (com prévia já extraída).

    Levanta ValueError para arquivo vazio, grande demais, binário ou PDF sem
    texto — o chamador transforma em 400.
    """
    if not dados:
        raise ValueError("arquivo vazio")
    if isinstance(dados, str):
        dados = dados.encode("utf-8")
    if len(dados) > MAX_BYTES:
        raise ValueError(f"arquivo grande demais (limite {MAX_BYTES // (1024*1024)} MB)")

    nome = _nome_seguro(nome)
    texto, tipo, paginas = extrair(nome, dados)

    uid = secrets.token_hex(8)
    pasta = PASTA / uid
    pasta.mkdir(parents=True, exist_ok=True)
    destino = pasta / nome
    destino.write_bytes(dados)

    info = {
        "id":       uid,
        "nome":     nome,
        "tipo":     tipo,
        "caminho":  destino.relative_to(ROOT).as_posix(),
        "bytes":    len(dados),
        "chars":    len(texto),
        "paginas":  paginas,
        "previa":   texto[:PREVIA_CHARS].strip(),
        "sessao":   str(sessao) if sessao else "",
        "criado":   datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
    }
    with _LOCK:
        indice = _ler_indice()
        indice[uid] = info
        _gravar_indice(indice)
    return info


def obter(upload_id: str) -> dict | None:
    """Descritor do anexo (ou None se sumiu do índice)."""
    return _ler_indice().get(str(upload_id))


def vincular(upload_id: str, sessao) -> None:
    """Marca a sessão dona do anexo (para limpar junto da sessão)."""
    if not sessao:
        return
    with _LOCK:
        indice = _ler_indice()
        info = indice.get(str(upload_id))
        if not info:
            return
        info["sessao"] = str(sessao)
        indice[str(upload_id)] = info
        _gravar_indice(indice)


def _apagar(uid: str, info: dict) -> None:
    caminho = ROOT / info.get("caminho", "")
    try:
        if caminho.is_file():
            caminho.unlink()
        pasta = PASTA / uid
        if pasta.is_dir():
            for resto in pasta.iterdir():
                resto.unlink(missing_ok=True)
            pasta.rmdir()
    except OSError:
        pass


def limpar_sessao(sessao) -> int:
    """Remove os anexos de uma sessão (chamado ao apagar a sessão)."""
    alvo = str(sessao)
    removidos = 0
    with _LOCK:
        indice = _ler_indice()
        for uid, info in list(indice.items()):
            if str(info.get("sessao", "")) == alvo:
                _apagar(uid, info)
                indice.pop(uid, None)
                removidos += 1
        if removidos:
            _gravar_indice(indice)
    return removidos


def limpar_orfaos(dias: int = MAX_ORFAOS_DIAS) -> int:
    """
    Remove anexos sem sessão e antigos (uploads de conversa abandonada).

    Roda de forma preguiçosa no upload — não precisa de cron.
    """
    corte = datetime.now() - timedelta(days=dias)
    removidos = 0
    with _LOCK:
        indice = _ler_indice()
        for uid, info in list(indice.items()):
            if str(info.get("sessao", "")):
                continue
            try:
                criado = datetime.strptime(info.get("criado", ""), "%Y-%m-%dT%H:%M:%S")
            except (TypeError, ValueError):
                criado = corte
            if criado < corte:
                _apagar(uid, info)
                indice.pop(uid, None)
                removidos += 1
        if removidos:
            _gravar_indice(indice)
    return removidos
