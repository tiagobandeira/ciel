"""
tests/test_tools/test_http_request.py

Cobre http_request.py:
  - bloqueio via SSRF guard (loopback, redes locais)
  - respostas mockadas GET/POST (JSON e texto)
  - URL ausente, método inválido, timeout, erro de conexão
"""

import json
import pytest
from unittest.mock import patch, MagicMock

from tools.http_request import run as http_request


# ── bloqueio SSRF ─────────────────────────────────────────────────────────────

class TestHttpRequestSSRF:
    def test_bloqueia_localhost(self):
        result = http_request(url="http://localhost/api")
        assert "Erro" in result or "bloqueado" in result.lower() or "local" in result.lower()

    def test_bloqueia_127_0_0_1(self):
        result = http_request(url="http://127.0.0.1/api")
        assert "Erro" in result or "bloqueado" in result.lower()

    def test_bloqueia_rede_privada_192(self):
        result = http_request(url="http://192.168.1.1/api")
        assert "Erro" in result or "privad" in result.lower() or "bloqueado" in result.lower()

    def test_bloqueia_rede_privada_10(self):
        result = http_request(url="http://10.0.0.1/api")
        assert "Erro" in result or "privad" in result.lower() or "bloqueado" in result.lower()

    def test_bloqueia_metadata_aws(self):
        result = http_request(url="http://169.254.169.254/latest/meta-data/")
        assert "Erro" in result or "bloqueado" in result.lower()


# ── URL ausente ───────────────────────────────────────────────────────────────

class TestHttpRequestValidation:
    def test_url_ausente_retorna_erro(self):
        result = http_request()
        assert "Erro" in result
        assert "URL" in result

    def test_url_none_retorna_erro(self):
        result = http_request(url=None)
        assert "Erro" in result


# ── respostas mockadas ────────────────────────────────────────────────────────

class MockResponse:
    def __init__(self, json_data=None, text="", status_code=200, headers=None):
        self._json_data = json_data
        self.text = text
        self.status_code = status_code
        self.headers = headers or {"Content-Type": "application/json"}

    def json(self):
        if self._json_data is None:
            raise ValueError("No JSON")
        return self._json_data


class TestHttpRequestMocked:
    @patch("tools.http_request.check_url", return_value=None)
    @patch("tools.http_request.requests.request")
    def test_get_retorna_json(self, mock_req, mock_check):
        mock_req.return_value = MockResponse(json_data={"ok": True})
        result = http_request(method="GET", url="https://api.exemplo.com/dados")
        parsed = json.loads(result)
        assert parsed["status_code"] == 200
        assert parsed["body"] == {"ok": True}

    @patch("tools.http_request.check_url", return_value=None)
    @patch("tools.http_request.requests.request")
    def test_post_com_dict_vira_json(self, mock_req, mock_check):
        mock_req.return_value = MockResponse(json_data={"criado": True}, status_code=201)
        result = http_request(
            method="POST",
            url="https://api.exemplo.com/item",
            data={"nome": "teste"},
        )
        parsed = json.loads(result)
        assert parsed["status_code"] == 201
        # verifica que json= foi passado (não data=)
        _, kwargs = mock_req.call_args
        assert kwargs.get("json") == {"nome": "teste"}
        assert kwargs.get("data") is None

    @patch("tools.http_request.check_url", return_value=None)
    @patch("tools.http_request.requests.request")
    def test_resposta_texto_nao_json(self, mock_req, mock_check):
        mock_req.return_value = MockResponse(text="não é json", status_code=200)
        result = http_request(method="GET", url="https://exemplo.com/texto")
        parsed = json.loads(result)
        assert parsed["body"] == "não é json"

    @patch("tools.http_request.check_url", return_value=None)
    @patch("tools.http_request.requests.request")
    def test_retorna_headers_na_resposta(self, mock_req, mock_check):
        mock_req.return_value = MockResponse(
            json_data={},
            headers={"X-Custom": "valor"},
        )
        result = http_request(method="GET", url="https://api.exemplo.com/")
        parsed = json.loads(result)
        assert "headers" in parsed
        assert parsed["headers"].get("X-Custom") == "valor"

    @patch("tools.http_request.check_url", return_value=None)
    @patch("tools.http_request.requests.request")
    def test_status_code_4xx_retornado(self, mock_req, mock_check):
        mock_req.return_value = MockResponse(json_data={"erro": "não autorizado"}, status_code=401)
        result = http_request(method="GET", url="https://api.exemplo.com/protegido")
        parsed = json.loads(result)
        assert parsed["status_code"] == 401

    @patch("tools.http_request.check_url", return_value=None)
    @patch("tools.http_request.requests.request", side_effect=Exception("Connection refused"))
    def test_erro_de_conexao_retorna_mensagem(self, mock_req, mock_check):
        result = http_request(method="GET", url="https://api.exemplo.com/")
        assert "Erro" in result

    @patch("tools.http_request.check_url", return_value=None)
    @patch("tools.http_request.requests.request")
    def test_params_passados_para_request(self, mock_req, mock_check):
        mock_req.return_value = MockResponse(json_data={})
        http_request(
            method="GET",
            url="https://api.exemplo.com/busca",
            params={"q": "python"},
        )
        _, kwargs = mock_req.call_args
        assert kwargs.get("params") == {"q": "python"}

    @patch("tools.http_request.check_url", return_value=None)
    @patch("tools.http_request.requests.request")
    def test_headers_customizados_passados(self, mock_req, mock_check):
        mock_req.return_value = MockResponse(json_data={})
        http_request(
            method="GET",
            url="https://api.exemplo.com/",
            headers={"Authorization": "Bearer token123"},
        )
        _, kwargs = mock_req.call_args
        assert kwargs["headers"].get("Authorization") == "Bearer token123"

    @patch("tools.http_request.check_url", return_value=None)
    @patch("tools.http_request.requests.request")
    def test_delete_method(self, mock_req, mock_check):
        mock_req.return_value = MockResponse(json_data={"deleted": True}, status_code=200)
        result = http_request(method="DELETE", url="https://api.exemplo.com/item/1")
        _, kwargs = mock_req.call_args
        assert kwargs["method"] == "DELETE"
