"""
tests/test_tools/test_read_write_file.py

Cobre read_file.py e write_file.py:
  - leitura: arquivo existente, inexistente, binário (não-UTF-8), truncagem
  - escrita: criação, sobrescrita, append, diretórios intermediários, mode inválido
"""

import pytest
from pathlib import Path
from unittest.mock import patch

from tools.read_file import run as read_file
from tools.write_file import run as write_file


# ── read_file ─────────────────────────────────────────────────────────────────

class TestReadFile:
    def test_le_arquivo_existente(self, tmp_path):
        f = tmp_path / "texto.txt"
        f.write_text("olá mundo", encoding="utf-8")
        result = read_file(str(f))
        assert result == "olá mundo"

    def test_arquivo_inexistente_retorna_erro(self, tmp_path):
        result = read_file(str(tmp_path / "nao_existe.txt"))
        assert "Erro" in result
        assert "não encontrado" in result

    def test_path_e_diretorio_retorna_erro(self, tmp_path):
        result = read_file(str(tmp_path))
        assert "Erro" in result

    def test_arquivo_binario_retorna_erro_de_decode(self, tmp_path):
        f = tmp_path / "binario.bin"
        f.write_bytes(bytes(range(256)))
        result = read_file(str(f))
        assert "Erro" in result
        assert "decodificar" in result.lower() or "utf-8" in result.lower()

    def test_arquivo_grande_e_truncado(self, tmp_path):
        f = tmp_path / "grande.txt"
        # escreve mais que MAX_CHARS (8_000) caracteres
        conteudo = "x" * 9_000
        f.write_text(conteudo, encoding="utf-8")
        result = read_file(str(f))
        assert "trecho" in result or "truncado" in result
        assert len(result) < 9_000 + 200  # margem para a mensagem de truncagem

    def test_offset_e_limit(self, tmp_path):
        f = tmp_path / "trecho.txt"
        f.write_text("0123456789abcdefghij", encoding="utf-8")
        result = read_file(str(f), offset=5, limit=5)
        assert result.startswith("56789")
        assert "trecho 5–10 de 20" in result

    def test_offset_alem_do_fim(self, tmp_path):
        f = tmp_path / "curto.txt"
        f.write_text("abc", encoding="utf-8")
        result = read_file(str(f), offset=99)
        assert "trecho 3–3 de 3" in result

    def test_por_linhas_com_numeracao(self, tmp_path):
        f = tmp_path / "linhas.txt"
        f.write_text("um\ndois\ntres\nquatro\n", encoding="utf-8")
        result = read_file(str(f), start_line=2, end_line=3, numbered=True)
        assert "    2 | dois" in result
        assert "    3 | tres" in result
        assert "quatro" not in result
        assert "linhas 2–3 de 4" in result

    def test_por_linhas_sem_end_line(self, tmp_path):
        f = tmp_path / "linhas.txt"
        f.write_text("a\nb\nc\n", encoding="utf-8")
        result = read_file(str(f), start_line=2, numbered=True)
        assert "    2 | b" in result
        assert "    3 | c" in result

    def test_char_mode_com_numeracao(self, tmp_path):
        f = tmp_path / "linhas.txt"
        f.write_text("a\nb\nc\n", encoding="utf-8")
        result = read_file(str(f), offset=2, limit=1, numbered=True)
        assert "    2 | b" in result

    def test_arquivo_vazio_retorna_string_vazia(self, tmp_path):
        f = tmp_path / "vazio.txt"
        f.write_text("", encoding="utf-8")
        result = read_file(str(f))
        assert result == ""

    def test_encoding_alternativo(self, tmp_path):
        f = tmp_path / "latin.txt"
        f.write_bytes("café".encode("latin-1"))
        result = read_file(str(f), encoding="latin-1")
        assert "café" in result

    def test_conteudo_multiline(self, tmp_path):
        f = tmp_path / "multi.txt"
        f.write_text("linha 1\nlinha 2\nlinha 3", encoding="utf-8")
        result = read_file(str(f))
        assert "linha 1" in result
        assert "linha 2" in result
        assert "linha 3" in result


# ── write_file ────────────────────────────────────────────────────────────────

class TestWriteFile:
    def test_cria_arquivo_novo(self, tmp_path):
        dest = tmp_path / "novo.txt"
        result = write_file(str(dest), "conteúdo novo")
        assert "sucesso" in result.lower() or "sobrescrito" in result.lower()
        assert dest.read_text(encoding="utf-8") == "conteúdo novo"

    def test_sobrescreve_arquivo_existente(self, tmp_path):
        dest = tmp_path / "existente.txt"
        dest.write_text("conteúdo antigo", encoding="utf-8")
        write_file(str(dest), "conteúdo novo", mode="overwrite")
        assert dest.read_text(encoding="utf-8") == "conteúdo novo"

    def test_modo_append(self, tmp_path):
        dest = tmp_path / "log.txt"
        dest.write_text("linha 1\n", encoding="utf-8")
        write_file(str(dest), "linha 2\n", mode="append")
        conteudo = dest.read_text(encoding="utf-8")
        assert "linha 1" in conteudo
        assert "linha 2" in conteudo

    def test_cria_diretorios_intermediarios(self, tmp_path):
        dest = tmp_path / "a" / "b" / "c" / "arquivo.txt"
        result = write_file(str(dest), "aninhado")
        assert dest.exists()
        assert dest.read_text(encoding="utf-8") == "aninhado"

    def test_mode_invalido_retorna_erro(self, tmp_path):
        dest = tmp_path / "qualquer.txt"
        result = write_file(str(dest), "texto", mode="destruir")
        assert "Erro" in result
        assert "mode" in result.lower() or "inválido" in result.lower()

    def test_retorna_contagem_de_caracteres(self, tmp_path):
        dest = tmp_path / "contagem.txt"
        conteudo = "abc123"
        result = write_file(str(dest), conteudo)
        assert str(len(conteudo)) in result

    def test_conteudo_unicode(self, tmp_path):
        dest = tmp_path / "unicode.txt"
        write_file(str(dest), "çãõêü 日本語")
        assert dest.read_text(encoding="utf-8") == "çãõêü 日本語"

    def test_append_em_arquivo_inexistente_cria(self, tmp_path):
        dest = tmp_path / "novo_append.txt"
        write_file(str(dest), "primeiro", mode="append")
        assert dest.exists()
        assert dest.read_text(encoding="utf-8") == "primeiro"
