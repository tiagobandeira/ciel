"""
mcp/google/docs_server.py
==========================
Servidor MCP para Google Docs via REST API.
Implementa JSON-RPC 2.0 sobre stdio — sem dependências além de urllib (stdlib).

Uso (teste manual):
    GOOGLE_CLIENT_SECRET=/caminho/client_secret.json python mcp/google/docs_server.py

Adicionando ao Ciel:
    mcp_add_server(
        name="google_docs",
        type="stdio",
        command="python",
        args="mcp/google/docs_server.py",
        env="GOOGLE_CLIENT_SECRET=/caminho/client_secret.json"
    )

Na primeira execução, o browser abre para autenticação OAuth.
As próximas conexões são automáticas.

Nota: Google Sheets e Google Docs compartilham o mesmo client_secret.json,
mas guardam tokens separados por padrão (GOOGLE_TOKEN_STORE diferente).
Para compartilhar o token, defina GOOGLE_TOKEN_STORE com o mesmo caminho nos dois.
"""

import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from mcp.google.auth import GoogleAuth, GoogleAuthError

# ── Escopos necessários ────────────────────────────────────────────────────────

_SCOPES = [
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive.readonly",   # para docs_list
]

_DOCS_BASE  = "https://docs.googleapis.com/v1/documents"
_DRIVE_BASE = "https://www.googleapis.com/drive/v3"

# Caminho de token separado do Sheets para não colidir quando ambos estão ativos
_DEFAULT_TOKEN = str(Path.home() / ".ciel" / "google_docs_token.json")

# ── Auth global ────────────────────────────────────────────────────────────────

_auth: GoogleAuth | None = None


def _headers() -> dict:
    return _auth.auth_headers()


# ── Helpers HTTP ───────────────────────────────────────────────────────────────

def _get(url: str, params: dict | None = None) -> dict:
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    req  = urllib.request.Request(url, headers=_headers())
    resp = urllib.request.urlopen(req, timeout=20)
    return json.loads(resp.read())


def _post(url: str, body: dict) -> dict:
    data = json.dumps(body).encode()
    req  = urllib.request.Request(url, data=data, headers=_headers(), method="POST")
    resp = urllib.request.urlopen(req, timeout=20)
    return json.loads(resp.read())


def _api_error(e: Exception) -> str:
    try:
        body = e.read()
        msg  = json.loads(body).get("error", {}).get("message", str(e))
        return f"Erro da API: {msg}"
    except Exception:
        return f"Erro: {e}"


# ── Extrator de texto do documento ────────────────────────────────────────────

def _extract_text(doc: dict) -> str:
    """
    Extrai o texto plano de um documento Google Docs.
    A API retorna uma estrutura de 'body.content' com elementos estruturais.
    """
    parts = []
    for element in doc.get("body", {}).get("content", []):
        paragraph = element.get("paragraph")
        if not paragraph:
            continue
        line = []
        for pe in paragraph.get("elements", []):
            tr = pe.get("textRun", {})
            line.append(tr.get("content", ""))
        parts.append("".join(line))
    return "".join(parts)


# ── Tools ──────────────────────────────────────────────────────────────────────

def docs_list(page_size: int = 20) -> str:
    """
    Lista documentos do Google Drive do usuário (mais recentes primeiro).
    Retorna id, name, link e data de modificação.
    """
    try:
        data = _get(_DRIVE_BASE + "/files", {
            "q":        "mimeType='application/vnd.google-apps.document' and trashed=false",
            "fields":   "files(id,name,webViewLink,modifiedTime)",
            "orderBy":  "modifiedTime desc",
            "pageSize": str(page_size),
        })
        files = data.get("files", [])
        if not files:
            return "Nenhum documento encontrado."
        result = [
            {"id": f["id"], "name": f["name"], "link": f.get("webViewLink", ""),
             "modified": f.get("modifiedTime", "")}
            for f in files
        ]
        return json.dumps(result, ensure_ascii=False, indent=2)
    except urllib.error.HTTPError as e:
        return _api_error(e)


def docs_read(document_id: str, as_text: bool = True) -> str:
    """
    Lê o conteúdo de um documento Google Docs.

    Parâmetros:
        document_id — ID do documento (da URL ou de docs_list)
        as_text     — True: retorna texto plano (padrão)
                      False: retorna JSON completo da estrutura do documento
    """
    try:
        doc = _get(f"{_DOCS_BASE}/{document_id}")
        if as_text:
            text = _extract_text(doc)
            if not text.strip():
                return "Documento vazio."
            return text
        # JSON completo — útil para debug ou leitura de metadados
        return json.dumps({
            "title":    doc.get("title", ""),
            "docId":    doc.get("documentId", ""),
            "revision": doc.get("revisionId", ""),
            "body":     doc.get("body", {}),
        }, ensure_ascii=False, indent=2)
    except urllib.error.HTTPError as e:
        return _api_error(e)


def docs_create(title: str, content: str = "") -> str:
    """
    Cria um novo documento Google Docs.

    Parâmetros:
        title   — título do documento
        content — texto inicial (opcional). Inserido no início do documento.
    """
    try:
        # cria o documento vazio
        doc = _post(_DOCS_BASE, {"title": title})
        doc_id = doc["documentId"]

        # insere conteúdo inicial se fornecido
        if content:
            _post(f"{_DOCS_BASE}/{doc_id}:batchUpdate", {
                "requests": [{
                    "insertText": {
                        "location": {"index": 1},
                        "text":     content,
                    }
                }]
            })

        return json.dumps({
            "id":    doc_id,
            "title": title,
            "link":  f"https://docs.google.com/document/d/{doc_id}/edit",
        }, ensure_ascii=False, indent=2)
    except urllib.error.HTTPError as e:
        return _api_error(e)


def docs_append(document_id: str, content: str) -> str:
    """
    Adiciona texto ao final de um documento existente.

    Parâmetros:
        document_id — ID do documento
        content     — texto a adicionar (suporta \\n para quebras de linha)
    """
    try:
        # descobre o índice do fim do documento
        doc     = _get(f"{_DOCS_BASE}/{document_id}", {"fields": "body.content"})
        content_list = doc.get("body", {}).get("content", [])

        # o último elemento tem o endIndex do documento
        end_index = 1
        if content_list:
            last = content_list[-1]
            end_index = last.get("endIndex", 1) - 1  # -1 para ficar antes do \n final

        _post(f"{_DOCS_BASE}/{document_id}:batchUpdate", {
            "requests": [{
                "insertText": {
                    "location": {"index": end_index},
                    "text":     content,
                }
            }]
        })
        return f"OK — texto adicionado ao final do documento."
    except urllib.error.HTTPError as e:
        return _api_error(e)


def docs_replace(document_id: str, find: str, replace: str,
                 match_case: bool = True) -> str:
    """
    Localiza e substitui texto em um documento.

    Parâmetros:
        document_id — ID do documento
        find        — texto a localizar
        replace     — texto substituto
        match_case  — diferencia maiúsculas/minúsculas (padrão: True)
    """
    try:
        result = _post(f"{_DOCS_BASE}/{document_id}:batchUpdate", {
            "requests": [{
                "replaceAllText": {
                    "containsText": {
                        "text":      find,
                        "matchCase": match_case,
                    },
                    "replaceText": replace,
                }
            }]
        })
        replies = result.get("replies", [{}])
        count   = replies[0].get("replaceAllText", {}).get("occurrencesChanged", 0)
        if count == 0:
            return f"Texto '{find}' não encontrado no documento."
        return f"OK — {count} ocorrência(s) substituída(s)."
    except urllib.error.HTTPError as e:
        return _api_error(e)


# ── Schema MCP ─────────────────────────────────────────────────────────────────

TOOLS = [
    {
        "name": "docs_list",
        "description": (
            "Lista os documentos Google Docs do usuário (mais recentes primeiro). "
            "Retorna id, name, link e data de modificação. "
            "Use para descobrir o document_id antes de ler ou editar."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "page_size": {"type": "integer", "description": "Quantidade máxima de documentos (padrão: 20)"},
            },
            "required": [],
        },
    },
    {
        "name": "docs_read",
        "description": (
            "Lê o conteúdo de um documento Google Docs. "
            "Por padrão retorna texto plano. "
            "Use as_text=false para obter a estrutura JSON completa do documento."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "document_id": {"type": "string", "description": "ID do documento (da URL ou de docs_list)"},
                "as_text":     {"type": "boolean", "description": "True: texto plano (padrão). False: JSON estrutural."},
            },
            "required": ["document_id"],
        },
    },
    {
        "name": "docs_create",
        "description": (
            "Cria um novo documento Google Docs com título e conteúdo inicial opcional. "
            "Retorna o id e o link do documento criado."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "title":   {"type": "string", "description": "Título do documento"},
                "content": {"type": "string", "description": "Texto inicial (opcional)"},
            },
            "required": ["title"],
        },
    },
    {
        "name": "docs_append",
        "description": (
            "Adiciona texto ao final de um documento existente. "
            "Use \\n para quebras de linha."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "document_id": {"type": "string", "description": "ID do documento"},
                "content":     {"type": "string", "description": "Texto a adicionar"},
            },
            "required": ["document_id", "content"],
        },
    },
    {
        "name": "docs_replace",
        "description": (
            "Localiza e substitui texto em um documento. "
            "Útil para preencher templates com placeholders como {{nome}}, {{data}}."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "document_id": {"type": "string", "description": "ID do documento"},
                "find":        {"type": "string", "description": "Texto a localizar"},
                "replace":     {"type": "string", "description": "Texto substituto"},
                "match_case":  {"type": "boolean", "description": "Diferencia maiúsculas (padrão: true)"},
            },
            "required": ["document_id", "find", "replace"],
        },
    },
]

TOOL_MAP = {
    "docs_list":    docs_list,
    "docs_read":    docs_read,
    "docs_create":  docs_create,
    "docs_append":  docs_append,
    "docs_replace": docs_replace,
}


# ── Loop JSON-RPC 2.0 ──────────────────────────────────────────────────────────

def _respond(req_id, result):
    print(json.dumps({"jsonrpc": "2.0", "id": req_id, "result": result}), flush=True)


def _error(req_id, code, message):
    print(json.dumps({"jsonrpc": "2.0", "id": req_id,
                      "error": {"code": code, "message": message}}), flush=True)


def _handle(req: dict) -> None:
    method = req.get("method", "")
    params = req.get("params", {})
    req_id = req.get("id")

    if method == "initialize":
        _respond(req_id, {
            "protocolVersion": "2024-11-05",
            "capabilities":    {"tools": {}},
            "serverInfo":      {"name": "google_docs", "version": "1.0.0"},
        })

    elif method == "notifications/initialized":
        pass

    elif method == "tools/list":
        _respond(req_id, {"tools": TOOLS})

    elif method == "tools/call":
        name = params.get("name", "")
        args = params.get("arguments", {})
        fn   = TOOL_MAP.get(name)
        if fn is None:
            _error(req_id, -32601, f"Tool desconhecida: '{name}'")
            return
        try:
            _auth.ensure_valid()
            text = fn(**args)
        except GoogleAuthError as e:
            text = f"Erro de autenticação: {e}"
        except TypeError as e:
            text = f"Parâmetros inválidos: {e}"
        except Exception as e:
            text = f"Erro inesperado: {e}"
        _respond(req_id, {"content": [{"type": "text", "text": text}]})

    else:
        _error(req_id, -32601, f"Método desconhecido: '{method}'")


def main() -> None:
    global _auth
    import os
    # token separado do Sheets por padrão, mas configurável via env
    token_path = os.environ.get("GOOGLE_TOKEN_STORE", _DEFAULT_TOKEN)
    try:
        _auth = GoogleAuth(scopes=_SCOPES, token_path=token_path)
        _auth.ensure_valid()
    except GoogleAuthError as e:
        print(f"[google_docs] Aviso de auth: {e}", file=sys.stderr)

    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            req = json.loads(raw)
        except json.JSONDecodeError:
            continue
        _handle(req)


if __name__ == "__main__":
    main()
