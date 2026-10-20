"""
llm/client.py — cliente de modelo unificado do Ciel.

Motivação: hoje a única forma de falar com um modelo cloud é a tool
`secondary_model`, que carrega Rich/spinner junto e portanto só o
orquestrador local consegue usar. Este módulo separa a chamada HTTP da
apresentação, para que código de harness (planejador, revisor, reporter)
também consiga chamar qualquer provider.

Dois adapters cobrem os casos reais do projeto:

  OllamaClient        → /api/chat (modelo local)
  OpenAICompatClient  → /chat/completions (NVIDIA, OpenRouter, Groq,
                        9router, OpenAI, qualquer endpoint compatível)

Contrato: `chat()` devolve `ChatResult(text, tokens_in, tokens_out, raw)`.
Erros de rede/HTTP continuam sendo `requests.*Error` (as mesmas exceções
que `agent_loop.run_agent` já captura), então trocar `_call_model` por um
cliente não muda o tratamento de falha de quem chama.

Nada aqui imprime, usa Rich ou lê `input()`.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import requests

DEFAULT_OLLAMA_BASE    = "http://localhost:11434"
DEFAULT_OLLAMA_TIMEOUT = 120
DEFAULT_OPENAI_TIMEOUT = 180

# status HTTP que valem uma nova tentativa (429/5xx)
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
_MAX_BACKOFF       = 8.0


class LLMError(Exception):
    """Erro de configuração ou de resposta inválida (não é falha de rede)."""


@dataclass
class ChatResult:
    """Resposta normalizada de qualquer provider."""

    text: str
    tokens_in: int = 0
    tokens_out: int = 0
    model: str = ""
    raw: dict | None = field(default=None, repr=False)

    def as_tuple(self) -> tuple[str, int, int]:
        """Compatibilidade com o antigo `_call_model` (texto, in, out)."""
        return self.text, self.tokens_in, self.tokens_out


class BaseClient:
    """Interface mínima que planejador/worker/loop consomem."""

    name = "base"
    is_local = False

    def chat(
        self,
        messages: list[dict],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout: float | None = None,
        retries: int = 0,
    ) -> ChatResult:
        raise NotImplementedError

    # ── infraestrutura comum ──────────────────────────────────────────────

    @staticmethod
    def _backoff(attempt: int) -> None:
        time.sleep(min(2 ** attempt, _MAX_BACKOFF))

    def _post(
        self,
        url: str,
        *,
        payload: dict,
        headers: dict | None,
        timeout: float,
        retries: int,
    ) -> requests.Response:
        """
        POST com retry opcional.

        `retries=0` (default) preserva o comportamento atual: uma tentativa,
        exceção sobe. Erros 4xx não são repetidos; 429/5xx e falhas de
        conexão/timeout são.
        """
        attempts = max(0, int(retries)) + 1
        last_exc: Exception | None = None

        for attempt in range(attempts):
            last = attempt == attempts - 1
            try:
                resp = requests.post(
                    url, json=payload, headers=headers, timeout=timeout
                )
                if resp.status_code in _RETRYABLE_STATUS and not last:
                    self._backoff(attempt)
                    continue
                resp.raise_for_status()
                return resp
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_exc = exc
                if last:
                    raise
                self._backoff(attempt)

        # inalcançável na prática: o último attempt ou retorna ou levanta
        if last_exc is not None:
            raise last_exc
        raise LLMError(f"falha ao chamar {url}")


# ── Ollama ────────────────────────────────────────────────────────────────

def _normalize_ollama_base(base_url: str | None) -> str:
    """
    Aceita tanto `http://localhost:11434` quanto a URL completa
    `http://localhost:11434/api/chat` (que é o formato usado hoje em
    `agent_loop.OLLAMA_URL`).
    """
    base = (base_url or DEFAULT_OLLAMA_BASE).strip().rstrip("/")
    if base.endswith("/api/chat"):
        base = base[: -len("/api/chat")].rstrip("/")
    return base or DEFAULT_OLLAMA_BASE


class OllamaClient(BaseClient):
    """Cliente do Ollama nativo (`/api/chat`, sem streaming)."""

    name = "ollama"
    is_local = True

    def __init__(
        self,
        base_url: str | None = DEFAULT_OLLAMA_BASE,
        *,
        timeout: float = DEFAULT_OLLAMA_TIMEOUT,
        chat_path: str = "/api/chat",
        max_tokens: int | None = None,
    ):
        self.base_url = _normalize_ollama_base(base_url)
        self.chat_path = chat_path if chat_path.startswith("/") else f"/{chat_path}"
        self.timeout = timeout
        self.max_tokens = max_tokens

    @property
    def endpoint(self) -> str:
        return f"{self.base_url}{self.chat_path}"

    def chat(
        self,
        messages: list[dict],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout: float | None = None,
        retries: int = 0,
    ) -> ChatResult:
        if not model:
            raise LLMError("OllamaClient.chat() precisa de um model")

        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
        }

        # Só envia `options` quando o chamador pediu algo — mantém o payload
        # idêntico ao de `agent_loop._call_model` no caminho padrão.
        options: dict[str, Any] = {}
        if temperature is not None:
            options["temperature"] = temperature
        effective_max = max_tokens if max_tokens is not None else self.max_tokens
        if effective_max is not None:
            options["num_predict"] = effective_max
        if options:
            payload["options"] = options

        resp = self._post(
            self.endpoint,
            payload=payload,
            headers=None,
            timeout=timeout or self.timeout,
            retries=retries,
        )
        data = resp.json()
        message = data.get("message") or {}
        return ChatResult(
            text=message.get("content", "") or "",
            tokens_in=int(data.get("prompt_eval_count", 0) or 0),
            tokens_out=int(data.get("eval_count", 0) or 0),
            model=model,
            raw=data,
        )


# ── OpenAI-compatible ─────────────────────────────────────────────────────

def _normalize_openai_base(base_url: str | None) -> str:
    """Aceita a base com ou sem `/chat/completions` no final."""
    base = (base_url or "").strip().rstrip("/")
    if base.endswith("/chat/completions"):
        base = base[: -len("/chat/completions")].rstrip("/")
    return base


class OpenAICompatClient(BaseClient):
    """
    Cliente para qualquer API compatível com OpenAI.

    `base_url` é a raiz versionada do provider, ex.:
    `https://integrate.api.nvidia.com/v1` → endpoint
    `https://integrate.api.nvidia.com/v1/chat/completions`.
    """

    name = "openai-compatible"
    is_local = False

    def __init__(
        self,
        base_url: str,
        *,
        api_key: str = "",
        model: str = "",
        timeout: float = DEFAULT_OPENAI_TIMEOUT,
        extra_headers: dict | None = None,
        max_tokens: int | None = None,
    ):
        self.base_url = _normalize_openai_base(base_url)
        self.api_key = api_key or ""
        self.model = model or ""
        self.timeout = timeout
        self.extra_headers = dict(extra_headers or {})
        self.max_tokens = max_tokens

    @property
    def endpoint(self) -> str:
        if not self.base_url:
            raise LLMError(
                "OpenAICompatClient sem base_url — configure o provider "
                "com /connect ou em ciel_config.json"
            )
        return f"{self.base_url}/chat/completions"

    def chat(
        self,
        messages: list[dict],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout: float | None = None,
        retries: int = 0,
    ) -> ChatResult:
        use_model = model or self.model
        if not use_model:
            raise LLMError("OpenAICompatClient.chat() precisa de um model")

        payload: dict[str, Any] = {
            "model": use_model,
            "messages": messages,
            "stream": False,
        }
        if temperature is not None:
            payload["temperature"] = temperature
        effective_max = max_tokens if max_tokens is not None else self.max_tokens
        if effective_max is not None:
            payload["max_tokens"] = effective_max

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        headers.update(self.extra_headers)

        resp = self._post(
            self.endpoint,
            payload=payload,
            headers=headers,
            timeout=timeout or self.timeout,
            retries=retries,
        )
        data = resp.json()

        choices = data.get("choices") or []
        if not choices:
            raise LLMError(
                f"resposta sem 'choices': {str(data)[:200]}"
            )
        message = choices[0].get("message") or {}
        content = message.get("content", "")

        # Alguns providers devolvem content como lista de partes.
        if isinstance(content, list):
            content = "".join(
                part.get("text", "") if isinstance(part, dict) else str(part)
                for part in content
            )

        usage = data.get("usage") or {}
        return ChatResult(
            text=content or "",
            tokens_in=int(usage.get("prompt_tokens", 0) or 0),
            tokens_out=int(usage.get("completion_tokens", 0) or 0),
            model=use_model,
            raw=data,
        )


# ── factory ───────────────────────────────────────────────────────────────

def make_client(
    *,
    provider: str = "ollama",
    base_url: str = "",
    api_key: str = "",
    model: str = "",
    timeout: float | None = None,
    max_tokens: int | None = None,
    **kwargs,
) -> BaseClient:
    """
    Cria o cliente adequado ao provider.

    `provider` é o id salvo em secrets.json/providers.json ("nvidia",
    "openrouter", "9router"…) ou "ollama"/"local". Qualquer coisa que não
    seja Ollama é tratada como OpenAI-compatible — é o que o projeto já
    assume em `tools/secondary_model.py`.
    """
    pid = (provider or "ollama").strip().lower()
    if pid in ("ollama", "local", ""):
        return OllamaClient(
            base_url=base_url or DEFAULT_OLLAMA_BASE,
            timeout=timeout or DEFAULT_OLLAMA_TIMEOUT,
            max_tokens=max_tokens,
            **kwargs,
        )
    return OpenAICompatClient(
        base_url=base_url,
        api_key=api_key,
        model=model,
        timeout=timeout or DEFAULT_OPENAI_TIMEOUT,
        max_tokens=max_tokens,
        **kwargs,
    )


__all__ = [
    "BaseClient",
    "ChatResult",
    "LLMError",
    "OllamaClient",
    "OpenAICompatClient",
    "make_client",
    "DEFAULT_OLLAMA_BASE",
    "DEFAULT_OLLAMA_TIMEOUT",
    "DEFAULT_OPENAI_TIMEOUT",
]
