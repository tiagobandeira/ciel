"""
tests/test_security/test_ssrf_guard.py

Cobre todos os vetores que o _ssrf_guard deve bloquear e os casos
legítimos que deve deixar passar.
"""

import pytest
from tools._ssrf_guard import check_url


# ── deve bloquear ────────────────────────────────────────────────────────────

class TestBloqueados:
    def test_loopback_direto(self):
        assert check_url("http://127.0.0.1:11434/api/tags") is not None

    def test_loopback_porta_zero(self):
        assert check_url("http://127.0.0.1/admin") is not None

    def test_localhost(self):
        assert check_url("http://localhost/admin") is not None

    def test_localhost_porta(self):
        assert check_url("http://localhost:8080") is not None

    def test_rede_local_classe_c(self):
        assert check_url("http://192.168.1.1") is not None

    def test_rede_local_classe_a(self):
        assert check_url("http://10.0.0.1") is not None

    def test_rede_local_classe_b(self):
        assert check_url("http://172.16.0.1") is not None

    def test_link_local_metadata_cloud(self):
        """169.254.169.254 é o endpoint de metadados AWS/GCP — sempre bloquear."""
        assert check_url("http://169.254.169.254/latest/meta-data") is not None

    def test_scheme_ftp(self):
        assert check_url("ftp://example.com") is not None

    def test_scheme_file(self):
        assert check_url("file:///etc/passwd") is not None

    def test_url_vazia(self):
        assert check_url("") is not None

    def test_url_sem_hostname(self):
        assert check_url("http://") is not None


# ── deve permitir ─────────────────────────────────────────────────────────────

class TestPermitidos:
    def test_dominio_publico_https(self):
        assert check_url("https://google.com") is None

    def test_api_publica(self):
        assert check_url("https://api.github.com/users/test") is None

    def test_nvidia_api(self):
        assert check_url("https://integrate.api.nvidia.com/v1/chat/completions") is None

    def test_http_publico(self):
        assert check_url("http://example.com") is None
