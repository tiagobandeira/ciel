"""
tests/test_tools/test_secondary_quota.py

Cota do modelo secundário em tokens e atribuição de limite (usuário x
provedor). O objetivo é nunca mais devolver um "Erro HTTP 429" mudo.
"""

import json

import pytest

from tools import secondary_model as sm


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setattr(sm, "_QUOTA_PATH", tmp_path / "data" / "secondary_quota.json")
    monkeypatch.setattr(sm, "_LIMITE_PATH", tmp_path / "data" / "secondary_limite.json")
    return tmp_path / "data"


class TestLimiteTokens:
    def test_campo_novo_manda(self):
        assert sm._limite_tokens({"max_tokens_per_session": 5_000}) == 5_000

    def test_legado_em_chars_converte(self):
        # 60k chars ÷ 3 chars/token = 20k tokens
        assert sm._limite_tokens({"max_chars_per_session": 60_000}) == 20_000

    def test_default_sem_config(self):
        # sem nada no config: 1M (guarda de custo, não corte curto)
        assert sm._limite_tokens(sm._DEFAULT_CONFIG) == 1_000_000
        assert sm._limite_tokens({}) == 1_000_000

    def test_valor_invalido_cai_no_legado(self):
        assert sm._limite_tokens({"max_tokens_per_session": "x",
                                  "max_chars_per_session": 3_000}) == 1_000


class TestQuota:
    def test_ida_e_volta(self, data):
        sm._save_quota("12", {"tokens": 1_500, "chars": 4_500})

        assert sm._load_quota("12") == {"tokens": 1_500, "chars": 4_500}

    def test_legado_int_em_chars(self, data):
        data.mkdir(parents=True)
        (data / "secondary_quota.json").write_text(json.dumps({"12": 9_000}))

        assert sm._load_quota("12") == {"tokens": 3_000, "chars": 9_000}

    def test_sessao_sem_uso(self, data):
        assert sm._load_quota("99") == {"tokens": 0, "chars": 0}


class TestClassificacao:
    @pytest.mark.parametrize("status,corpo,esperado", [
        (429, "rate limit exceeded", "rate_limit"),
        (402, "insufficient_quota", "credito"),
        (400, '{"error":"maximum context length is 128000 tokens"}', "contexto"),
        (500, "boom", "outro"),
    ])
    def test_subtipo(self, status, corpo, esperado):
        info = sm._classificar_erro_provedor(status, corpo)

        assert info["origem"] == "provedor"
        assert info["subtipo"] == esperado
        assert str(status) in info["detalhe"]

    def test_mensagem_do_usuario(self):
        texto = sm._mensagem_limite({"origem": "usuario", "usado": 900, "teto": 1_000})

        assert "definido por você" in texto
        assert "900" in texto and "1,000" in texto
        assert "90%" in texto

    def test_mensagem_do_provedor(self):
        texto = sm._mensagem_limite({
            "origem": "provedor", "subtipo": "rate_limit",
            "detalhe": "HTTP 429: rate limit",
        })

        assert "provedor" in texto
        assert "rate limit" in texto
        assert "HTTP 429" in texto


class TestRegistro:
    def test_grava_arquivo_e_publica(self, data, monkeypatch):
        import ui_bus
        publicados = []
        monkeypatch.setattr(ui_bus, "publish",
                            lambda tipo, **dados: publicados.append((tipo, dados)))

        info = sm._registrar_limite("usuario", "cota da sessão",
                                    usado=10, teto=100)

        assert info["origem"] == "usuario"
        salvo = json.loads((data / "secondary_limite.json").read_text(encoding="utf-8"))
        assert salvo["teto"] == 100 and salvo["usado"] == 10
        assert publicados and publicados[0][0] == "limite"
        assert publicados[0][1]["origem"] == "usuario"
