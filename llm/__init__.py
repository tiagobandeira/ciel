"""Camada de acesso a modelos do Ciel.

Este pacote é deliberadamente livre de Rich/Textual/prompt_toolkit: qualquer
harness (CLI, TUI, server, bots) pode chamar modelos sem arrastar UI junto.

    from llm.client import make_client
    from llm.roles import load_roles

    client = make_client(provider="ollama", model="gemma4:cloud")
    result = client.chat(messages, model="gemma4:cloud")
    print(result.text, result.tokens_in, result.tokens_out)

Os papéis (orchestrator/planner/worker/reviewer/reporter) vivem em
`llm.roles`; este `__init__` reexporta só o cliente para não carregar
trust/secrets em quem só quer falar com o Ollama.
"""

from llm.client import (
    BaseClient,
    ChatResult,
    LLMError,
    OllamaClient,
    OpenAICompatClient,
    make_client,
)

__all__ = [
    "BaseClient",
    "ChatResult",
    "LLMError",
    "OllamaClient",
    "OpenAICompatClient",
    "make_client",
]
