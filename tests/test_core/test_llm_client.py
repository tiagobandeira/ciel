"""
tests/test_core/test_llm_client.py

Cobre `llm/client.py` sem rede:
  - payload/parse do Ollama (idêntico ao antigo agent_loop._call_model)
  - payload/parse do OpenAI-compatible
  - normalização de base_url
  - retry opcional (429/5xx e conexão)
  - factory make_client
"""

import pytest
import requests

from llm.client import (
    ChatResult,
    LLMError,
    OllamaClient,
    OpenAICompatClient,
    make_client,
)


# ── helpers ───────────────────────────────────────────────────────────────

class FakeResponse:
    def __init__(self, data=None, status_code=200, text=""):
        self._data = data if data is not None else {}
        self.status_code = status_code
        self.text = text

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(
                f"HTTP {self.status_code}", response=self
            )


def install_post(monkeypatch, responses):
    """
    Substitui requests.post por uma fila de respostas e devolve a lista
    de chamadas registradas.
    """
    calls = []
    queue = list(responses)

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append({
            "url": url, "json": json, "headers": headers, "timeout": timeout,
        })
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr("llm.client.requests.post", fake_post)
    monkeypatch.setattr("llm.client.time.sleep", lambda *_: None)
    return calls


# ── Ollama ────────────────────────────────────────────────────────────────

class TestOllamaClient:
    def test_payload_minimo_identico_ao_call_model_antigo(self, monkeypatch):
        """Sem temperature/max_tokens o payload é exatamente o histórico."""
        calls = install_post(monkeypatch, [FakeResponse({
            "message": {"content": "oi"},
            "prompt_eval_count": 11,
            "eval_count": 7,
        })])
        client = OllamaClient("http://localhost:11434")
        result = client.chat([{"role": "user", "content": "oi"}], model="gemma4:cloud")

        assert result.text == "oi"
        assert result.tokens_in == 11
        assert result.tokens_out == 7
        assert result.as_tuple() == ("oi", 11, 7)

        payload = calls[0]["json"]
        assert payload == {
            "model": "gemma4:cloud",
            "messages": [{"role": "user", "content": "oi"}],
            "stream": False,
        }
        assert calls[0]["url"] == "http://localhost:11434/api/chat"
        assert calls[0]["timeout"] == 120

    def test_aceita_url_completa_api_chat(self):
        client = OllamaClient("http://localhost:11434/api/chat")
        assert client.endpoint == "http://localhost:11434/api/chat"

    def test_options_quando_pedido(self, monkeypatch):
        calls = install_post(monkeypatch, [FakeResponse({"message": {"content": "x"}})])
        client = OllamaClient("http://localhost:11434")
        client.chat([], model="m", temperature=0.2, max_tokens=100)

        payload = calls[0]["json"]
        assert payload["options"] == {"temperature": 0.2, "num_predict": 100}

    def test_sem_usage_retorna_zero(self, monkeypatch):
        install_post(monkeypatch, [FakeResponse({"message": {"content": "x"}})])
        result = OllamaClient("http://localhost:11434").chat([], model="m")
        assert (result.tokens_in, result.tokens_out) == (0, 0)
        assert result.text == "x"

    def test_model_obrigatorio(self):
        with pytest.raises(LLMError):
            OllamaClient("http://localhost:11434").chat([], model="")

    def test_erro_de_conexao_propaga(self, monkeypatch):
        install_post(monkeypatch, [requests.ConnectionError("recusada")])
        with pytest.raises(requests.ConnectionError):
            OllamaClient("http://localhost:11434").chat([], model="m")


# ── OpenAI-compatible ─────────────────────────────────────────────────────

class TestOpenAICompatClient:
    def test_endpoint_e_payload(self, monkeypatch):
        calls = install_post(monkeypatch, [FakeResponse({
            "choices": [{"message": {"content": "resposta"}}],
            "usage": {"prompt_tokens": 21, "completion_tokens": 9},
        })])
        client = OpenAICompatClient(
            "https://integrate.api.nvidia.com/v1",
            api_key="segredo",
            model="modelo-default",
        )
        result = client.chat([{"role": "user", "content": "oi"}], max_tokens=50)

        assert result.text == "resposta"
        assert result.tokens_in == 21
        assert result.tokens_out == 9
        assert result.model == "modelo-default"

        assert calls[0]["url"] == "https://integrate.api.nvidia.com/v1/chat/completions"
        assert calls[0]["headers"]["Authorization"] == "Bearer segredo"
        assert calls[0]["json"] == {
            "model": "modelo-default",
            "messages": [{"role": "user", "content": "oi"}],
            "stream": False,
            "max_tokens": 50,
        }

    def test_base_url_ja_com_chat_completions(self):
        client = OpenAICompatClient(
            "https://x.test/v1/chat/completions", model="m"
        )
        assert client.endpoint == "https://x.test/v1/chat/completions"

    def test_content_em_lista_de_partes(self, monkeypatch):
        install_post(monkeypatch, [FakeResponse({
            "choices": [{"message": {"content": [
                {"type": "text", "text": "a"},
                {"type": "text", "text": "b"},
            ]}}],
        })])
        result = OpenAICompatClient("https://x.test/v1", model="m").chat([])
        assert result.text == "ab"

    def test_sem_choices_levanta_llm_error(self, monkeypatch):
        install_post(monkeypatch, [FakeResponse({"error": "ruim"})])
        with pytest.raises(LLMError):
            OpenAICompatClient("https://x.test/v1", model="m").chat([])

    def test_sem_base_url_levanta_llm_error(self):
        with pytest.raises(LLMError):
            OpenAICompatClient("", model="m").chat([])

    def test_model_obrigatorio(self):
        with pytest.raises(LLMError):
            OpenAICompatClient("https://x.test/v1").chat([])

    def test_400_nao_repete(self, monkeypatch):
        calls = install_post(monkeypatch, [FakeResponse({}, status_code=400)])
        with pytest.raises(requests.HTTPError):
            OpenAICompatClient("https://x.test/v1", model="m").chat([], retries=3)
        assert len(calls) == 1

    def test_503_repete_e_depois_sucede(self, monkeypatch):
        calls = install_post(monkeypatch, [
            FakeResponse({}, status_code=503),
            FakeResponse({"choices": [{"message": {"content": "ok"}}]}),
        ])
        result = OpenAICompatClient("https://x.test/v1", model="m").chat([], retries=1)
        assert result.text == "ok"
        assert len(calls) == 2


# ── factory ───────────────────────────────────────────────────────────────

class TestMakeClient:
    def test_ollama(self):
        assert isinstance(make_client(provider="ollama"), OllamaClient)
        assert isinstance(make_client(provider="local"), OllamaClient)
        assert isinstance(make_client(provider=""), OllamaClient)

    def test_cloud(self):
        client = make_client(
            provider="nvidia",
            base_url="https://integrate.api.nvidia.com/v1",
            api_key="k",
            model="m",
        )
        assert isinstance(client, OpenAICompatClient)
        assert client.api_key == "k"
        assert client.model == "m"

    def test_ollama_url_completa(self):
        client = make_client(
            provider="ollama", base_url="http://localhost:11434/api/chat"
        )
        assert client.endpoint == "http://localhost:11434/api/chat"
