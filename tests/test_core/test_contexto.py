"""
tests/test_core/test_contexto.py

Cobre o orçamento de contexto por perfil/modelo (contexto.py): defaults,
override por perfil e por modelo, conversão para chars, keep_last e anexo.
"""

import json

import contexto


def _config(tmp_path, bloco):
    caminho = tmp_path / "ciel_config.json"
    caminho.write_text(json.dumps({"contexto": bloco}), encoding="utf-8")
    return caminho


class TestDefaults:
    def test_sem_config(self, tmp_path):
        cfg = contexto.carregar(tmp_path / "nao-existe.json")

        assert contexto.teto_tokens("local", cfg=cfg) == 32_000
        assert contexto.teto_tokens("nuvem", cfg=cfg) == 128_000
        assert contexto.chars_por_token(cfg) == 3
        assert contexto.teto_chars("local", cfg=cfg) == 96_000
        assert contexto.keep_last("local", cfg) == 4
        assert contexto.keep_last("nuvem", cfg) == 6
        assert contexto.anexo(cfg) == {"previa_chars": 2000, "teto_tokens": 8000}
        assert contexto.avisar_truncamento(cfg) is True

    def test_config_corrompida_usa_default(self, tmp_path):
        caminho = tmp_path / "ciel_config.json"
        caminho.write_text("{isso não é json", encoding="utf-8")

        cfg = contexto.carregar(caminho)

        assert contexto.teto_tokens("local", cfg=cfg) == 32_000

    def test_config_sem_bloco_contexto(self, tmp_path):
        caminho = tmp_path / "ciel_config.json"
        caminho.write_text(json.dumps({"web": {"perfil": "local"}}), encoding="utf-8")

        assert contexto.teto_tokens("local", cfg=contexto.carregar(caminho)) == 32_000


class TestOverride:
    def test_por_perfil(self, tmp_path):
        cfg = contexto.carregar(_config(tmp_path, {"teto_tokens": {"local": 16_000}}))

        assert contexto.teto_tokens("local", cfg=cfg) == 16_000
        assert contexto.teto_tokens("nuvem", cfg=cfg) == 128_000   # não foi tocado

    def test_por_modelo(self, tmp_path):
        cfg = contexto.carregar(_config(tmp_path, {
            "por_modelo": {"gemma4:cloud": 24_000, "deepseek-chat": 200_000},
        }))

        assert contexto.teto_tokens("local", "gemma4:cloud", cfg) == 24_000
        assert contexto.teto_tokens("local", "gemma4", cfg) == 24_000      # sem tag
        assert contexto.teto_tokens("nuvem", "deepseek-chat", cfg) == 200_000
        assert contexto.teto_tokens("local", "outro-modelo", cfg) == 32_000

    def test_chars_por_token(self, tmp_path):
        cfg = contexto.carregar(_config(tmp_path, {"chars_por_token": 4}))

        assert contexto.teto_chars("local", cfg=cfg) == 128_000

    def test_keep_last_e_anexo(self, tmp_path):
        cfg = contexto.carregar(_config(tmp_path, {
            "history_keep_last": {"local": 2},
            "anexo": {"previa_chars": 500},
        }))

        assert contexto.keep_last("local", cfg) == 2
        assert contexto.keep_last("nuvem", cfg) == 6
        assert contexto.anexo(cfg)["previa_chars"] == 500
        assert contexto.anexo(cfg)["teto_tokens"] == 8000     # default preservado

    def test_valores_invalidos_caem_no_default(self, tmp_path):
        cfg = contexto.carregar(_config(tmp_path, {
            "teto_tokens": {"local": "muito"},
            "chars_por_token": 0,
        }))

        assert contexto.teto_tokens("local", cfg=cfg) == 32_000
        assert contexto.chars_por_token(cfg) == 3

    def test_perfil_alias(self, tmp_path):
        cfg = contexto.carregar(_config(tmp_path, {"teto_tokens": {"nuvem": 64_000}}))

        assert contexto.teto_tokens("cloud", cfg=cfg) == 64_000
        assert contexto.teto_tokens("build", cfg=cfg) == 64_000
        assert contexto.teto_tokens("", cfg=cfg) == 32_000
