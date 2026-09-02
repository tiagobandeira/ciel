"""
mcp/google/sheets_server.py
============================
Servidor MCP para Google Sheets via REST API.
Implementa JSON-RPC 2.0 sobre stdio — sem dependências além de urllib (stdlib).

Uso (teste manual):
    GOOGLE_CLIENT_SECRET=/caminho/client_secret.json python mcp/google/sheets_server.py

Adicionando ao Ciel:
    mcp_add_server(
        name="google_sheets",
        type="stdio",
        command="python",
        args="mcp/google/sheets_server.py",
        env="GOOGLE_CLIENT_SECRET=/caminho/client_secret.json"
    )

Na primeira execução, o browser abre para autenticação OAuth.
As próximas conexões são automáticas.
"""

import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

# permite rodar diretamente ou como módulo
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from mcp.google.auth import GoogleAuth, GoogleAuthError

# ── Escopos necessários ────────────────────────────────────────────────────────

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",   # para sheets_list
]

_SHEETS_BASE = "https://sheets.googleapis.com/v4/spreadsheets"
_DRIVE_BASE  = "https://www.googleapis.com/drive/v3"

# ── Auth global (inicializado no main) ────────────────────────────────────────

_auth: GoogleAuth | None = None


def _headers() -> dict:
    """Retorna headers com token válido, renovando se necessário."""
    return _auth.auth_headers()


# ── Helpers HTTP ───────────────────────────────────────────────────────────────

def _get(url: str, params: dict | None = None) -> dict:
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    req  = urllib.request.Request(url, headers=_headers())
    resp = urllib.request.urlopen(req, timeout=20)
    return json.loads(resp.read())


def _put(url: str, body: dict) -> dict:
    data = json.dumps(body).encode()
    req  = urllib.request.Request(url, data=data, headers=_headers(), method="PUT")
    resp = urllib.request.urlopen(req, timeout=20)
    return json.loads(resp.read())


def _post(url: str, body: dict) -> dict:
    data = json.dumps(body).encode()
    req  = urllib.request.Request(url, data=data, headers=_headers(), method="POST")
    resp = urllib.request.urlopen(req, timeout=20)
    return json.loads(resp.read())


def _api_error(e: Exception) -> str:
    """Extrai mensagem legível de erros da API."""
    try:
        body = e.read()
        msg  = json.loads(body).get("error", {}).get("message", str(e))
        return f"Erro da API: {msg}"
    except Exception:
        return f"Erro: {e}"


# ── Tools ──────────────────────────────────────────────────────────────────────

def sheets_list(page_size: int = 20) -> str:
    """
    Lista planilhas do Google Drive do usuário.
    Retorna id, name e link de cada planilha.
    """
    try:
        data = _get(_DRIVE_BASE + "/files", {
            "q":        "mimeType='application/vnd.google-apps.spreadsheet' and trashed=false",
            "fields":   "files(id,name,webViewLink,modifiedTime)",
            "orderBy":  "modifiedTime desc",
            "pageSize": str(page_size),
        })
        files = data.get("files", [])
        if not files:
            return "Nenhuma planilha encontrada."
        result = [
            {"id": f["id"], "name": f["name"], "link": f.get("webViewLink", ""),
             "modified": f.get("modifiedTime", "")}
            for f in files
        ]
        return json.dumps(result, ensure_ascii=False, indent=2)
    except urllib.error.HTTPError as e:
        return _api_error(e)


def sheets_read(spreadsheet_id: str, range: str = "A1:Z1000",
                sheet: str | None = None) -> str:
    """
    Lê um intervalo de células de uma planilha.

    Parâmetros:
        spreadsheet_id — ID da planilha (da URL ou de sheets_list)
        range          — intervalo A1 notation (ex: "A1:D10"). Padrão: "A1:Z1000"
        sheet          — nome da aba (ex: "Plan1"). Se omitido, usa a primeira.
    """
    try:
        full_range = f"{sheet}!{range}" if sheet else range
        data = _get(f"{_SHEETS_BASE}/{spreadsheet_id}/values/{urllib.parse.quote(full_range)}")
        values = data.get("values", [])
        if not values:
            return "Intervalo vazio."
        return json.dumps(values, ensure_ascii=False, indent=2)
    except urllib.error.HTTPError as e:
        return _api_error(e)


def sheets_write(spreadsheet_id: str, range: str, values: str,
                 sheet: str | None = None) -> str:
    """
    Escreve valores em um intervalo de células (sobrescreve).

    Parâmetros:
        spreadsheet_id — ID da planilha
        range          — intervalo de início (ex: "A1" ou "A1:C3")
        values         — JSON de lista de listas: [["col1","col2"],["val1","val2"]]
        sheet          — nome da aba (opcional)
    """
    try:
        parsed_values = json.loads(values)
        full_range    = f"{sheet}!{range}" if sheet else range
        url = (
            f"{_SHEETS_BASE}/{spreadsheet_id}/values/{urllib.parse.quote(full_range)}"
            f"?valueInputOption=USER_ENTERED"
        )
        result = _put(url, {"range": full_range, "majorDimension": "ROWS", "values": parsed_values})
        updated = result.get("updatedCells", "?")
        return f"OK — {updated} célula(s) atualizada(s) em {result.get('updatedRange', full_range)}."
    except json.JSONDecodeError:
        return "Erro: 'values' deve ser JSON de lista de listas. Ex: [[\"a\",\"b\"],[\"1\",\"2\"]]"
    except urllib.error.HTTPError as e:
        return _api_error(e)


def sheets_append(spreadsheet_id: str, values: str,
                  sheet: str | None = None) -> str:
    """
    Adiciona linhas ao final de uma planilha (após os dados existentes).

    Parâmetros:
        spreadsheet_id — ID da planilha
        values         — JSON de lista de listas: [["col1","col2"],["val1","val2"]]
        sheet          — nome da aba (opcional)
    """
    try:
        parsed_values = json.loads(values)
        range_        = f"{sheet}!A1" if sheet else "A1"
        url = (
            f"{_SHEETS_BASE}/{spreadsheet_id}/values/{urllib.parse.quote(range_)}:append"
            f"?valueInputOption=USER_ENTERED&insertDataOption=INSERT_ROWS"
        )
        result = _post(url, {"majorDimension": "ROWS", "values": parsed_values})
        updates = result.get("updates", {})
        return f"OK — {updates.get('updatedRows', '?')} linha(s) adicionada(s) em {updates.get('updatedRange', range_)}."
    except json.JSONDecodeError:
        return "Erro: 'values' deve ser JSON de lista de listas. Ex: [[\"a\",\"b\"],[\"1\",\"2\"]]"
    except urllib.error.HTTPError as e:
        return _api_error(e)


def sheets_clear(spreadsheet_id: str, range: str, sheet: str | None = None) -> str:
    """
    Limpa um intervalo de células (remove valores, mantém formatação).

    Parâmetros:
        spreadsheet_id — ID da planilha
        range          — intervalo (ex: "A1:D10")
        sheet          — nome da aba (opcional)
    """
    try:
        full_range = f"{sheet}!{range}" if sheet else range
        url    = f"{_SHEETS_BASE}/{spreadsheet_id}/values/{urllib.parse.quote(full_range)}:clear"
        result = _post(url, {})
        return f"OK — intervalo {result.get('clearedRange', full_range)} limpo."
    except urllib.error.HTTPError as e:
        return _api_error(e)


def sheets_info(spreadsheet_id: str) -> str:
    """
    Retorna metadados da planilha: título, abas e propriedades básicas.

    Parâmetros:
        spreadsheet_id — ID da planilha
    """
    try:
        data   = _get(f"{_SHEETS_BASE}/{spreadsheet_id}",
                      {"fields": "spreadsheetId,properties,sheets.properties"})
        props  = data.get("properties", {})
        sheets = [
            {"title": s["properties"]["title"],
             "index": s["properties"]["index"],
             "rows":  s["properties"].get("gridProperties", {}).get("rowCount"),
             "cols":  s["properties"].get("gridProperties", {}).get("columnCount")}
            for s in data.get("sheets", [])
        ]
        return json.dumps({
            "id":     data.get("spreadsheetId"),
            "title":  props.get("title"),
            "locale": props.get("locale"),
            "sheets": sheets,
        }, ensure_ascii=False, indent=2)
    except urllib.error.HTTPError as e:
        return _api_error(e)


# ── Schema MCP ─────────────────────────────────────────────────────────────────

TOOLS = [
    {
        "name": "sheets_list",
        "description": (
            "Lista as planilhas do Google Drive do usuário (mais recentes primeiro). "
            "Retorna id, name, link e data de modificação. "
            "Use para descobrir o spreadsheet_id antes de ler ou escrever."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "page_size": {"type": "integer", "description": "Quantidade máxima de planilhas (padrão: 20)"},
            },
            "required": [],
        },
    },
    {
        "name": "sheets_info",
        "description": (
            "Retorna metadados de uma planilha: título, lista de abas, "
            "número de linhas e colunas de cada aba. "
            "Use antes de sheets_read para saber os nomes das abas."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "spreadsheet_id": {"type": "string", "description": "ID da planilha (da URL ou de sheets_list)"},
            },
            "required": ["spreadsheet_id"],
        },
    },
    {
        "name": "sheets_read",
        "description": (
            "Lê um intervalo de células de uma planilha. "
            "Retorna lista de listas com os valores. "
            "Use sheets_info antes para saber os nomes das abas."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "spreadsheet_id": {"type": "string", "description": "ID da planilha"},
                "range":          {"type": "string", "description": "Intervalo A1 notation (padrão: A1:Z1000)"},
                "sheet":          {"type": "string", "description": "Nome da aba (opcional — usa a primeira se omitido)"},
            },
            "required": ["spreadsheet_id"],
        },
    },
    {
        "name": "sheets_write",
        "description": (
            "Escreve valores em um intervalo de células (sobrescreve o conteúdo existente). "
            "'values' deve ser JSON de lista de listas: [[\"col1\",\"col2\"],[\"val1\",\"val2\"]]."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "spreadsheet_id": {"type": "string", "description": "ID da planilha"},
                "range":          {"type": "string", "description": "Célula inicial ou intervalo (ex: A1 ou A1:C3)"},
                "values":         {"type": "string", "description": "JSON de lista de listas com os valores"},
                "sheet":          {"type": "string", "description": "Nome da aba (opcional)"},
            },
            "required": ["spreadsheet_id", "range", "values"],
        },
    },
    {
        "name": "sheets_append",
        "description": (
            "Adiciona linhas ao final dos dados existentes em uma planilha. "
            "'values' deve ser JSON de lista de listas: [[\"col1\",\"col2\"]]."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "spreadsheet_id": {"type": "string", "description": "ID da planilha"},
                "values":         {"type": "string", "description": "JSON de lista de listas com as novas linhas"},
                "sheet":          {"type": "string", "description": "Nome da aba (opcional)"},
            },
            "required": ["spreadsheet_id", "values"],
        },
    },
    {
        "name": "sheets_clear",
        "description": "Limpa um intervalo de células (remove valores, mantém formatação).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "spreadsheet_id": {"type": "string", "description": "ID da planilha"},
                "range":          {"type": "string", "description": "Intervalo a limpar (ex: A1:D10)"},
                "sheet":          {"type": "string", "description": "Nome da aba (opcional)"},
            },
            "required": ["spreadsheet_id", "range"],
        },
    },
]

TOOL_MAP = {
    "sheets_list":   sheets_list,
    "sheets_info":   sheets_info,
    "sheets_read":   sheets_read,
    "sheets_write":  sheets_write,
    "sheets_append": sheets_append,
    "sheets_clear":  sheets_clear,
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
            "serverInfo":      {"name": "google_sheets", "version": "1.0.0"},
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
            # renova token se necessário antes de cada chamada
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
    try:
        _auth = GoogleAuth(scopes=_SCOPES)
        _auth.ensure_valid()
    except GoogleAuthError as e:
        # inicia o servidor mesmo sem auth — tools retornarão erro descritivo
        print(f"[google_sheets] Aviso de auth: {e}", file=sys.stderr)

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
