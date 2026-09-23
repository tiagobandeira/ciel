"""
tests/test_security/test_redaction.py

Verifica que _redact() substitui corretamente padrões de segredos
e não toca conteúdo legítimo.
"""

import pytest
from history_store import _redact


# ── deve redactar ─────────────────────────────────────────────────────────────

class TestDeveRedactar:
    def test_openai_key(self):
        t = "minha chave sk-proj-abcdefghijklmnopqrstuvwxyz123456"
        assert "[REDACTED]" in _redact(t)

    def test_anthropic_key(self):
        t = "key: sk-ant-api03-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
        assert "[REDACTED]" in _redact(t)

    def test_nvidia_key(self):
        t = "nvapi-xKj3mNpQrStUvWxYzAbCdEfGhIjKlMnOpQrSt"
        assert "[REDACTED]" in _redact(t)

    def test_github_token(self):
        t = "token: ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi"
        assert "[REDACTED]" in _redact(t)

    def test_bearer_token(self):
        t = "Authorization: Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6Ikp"
        assert "[REDACTED]" in _redact(t)

    def test_api_key_env_style(self):
        t = "API_KEY=sk-prod-xkjhsdfkjhsdkfjhskdjfhskdjfh"
        assert "[REDACTED]" in _redact(t)

    def test_password_config(self):
        t = "password=minha_senha_secreta_muito_longa"
        assert "[REDACTED]" in _redact(t)

    def test_openai_key_config(self):
        t = "OPENAI_API_KEY: sk-ant-api03-xxx-xxxxxxxxxxxxxxxxxxxxxxxxxx"
        assert "[REDACTED]" in _redact(t)

    def test_connection_string_postgres(self):
        t = "postgres://admin:senha_secreta@db.host:5432/producao"
        assert "[REDACTED]" in _redact(t)

    def test_connection_string_mongodb(self):
        t = "mongodb://user:pass123@cluster.mongodb.net/db"
        assert "[REDACTED]" in _redact(t)

    def test_chave_no_meio_do_texto(self):
        t = "configurei com sk-proj-abcdefghijklmnopqrstuvwxyz e funcionou"
        resultado = _redact(t)
        assert "[REDACTED]" in resultado
        assert "sk-proj" not in resultado

    def test_valor_original_nao_aparece(self):
        """O valor original não deve aparecer no resultado."""
        chave = "sk-proj-abcdefghijklmnopqrstuvwxyz123456789"
        assert chave not in _redact(f"minha chave: {chave}")


# ── não deve redactar ─────────────────────────────────────────────────────────

class TestNaoDeveRedactar:
    def test_texto_normal(self):
        t = "a task foi concluída com sucesso"
        assert _redact(t) == t

    def test_resposta_do_modelo(self):
        t = "O arquivo foi salvo em data/user/resultado.md"
        assert _redact(t) == t

    def test_string_vazia(self):
        assert _redact("") == ""

    def test_chave_curta_demais(self):
        """Strings curtas com prefixo sk- não devem ser redactadas."""
        t = "minha chave é: sk-123"
        assert _redact(t) == t

    def test_palavra_password_sem_valor(self):
        """A palavra 'password' sozinha não deve ser redactada."""
        t = "o campo password é obrigatório"
        assert _redact(t) == t

    def test_url_publica_sem_credencial(self):
        t = "acesse https://docs.anthropic.com/claude"
        assert _redact(t) == t
