"""Classificador local do modo live (sem secundário): escolhe forma por nome + descrição/aliases."""

import ui_anotar
import tools.mostrar_forma as mf


def nomes(frases):
    return [m["nome"] for m in ui_anotar._marcas_local(mf, frases)]


def test_live_escolhe_pelo_nome():
    marcas = ui_anotar._marcas_local(mf, ["Um foguete vence a gravidade e sobe."])
    assert [m["nome"] for m in marcas] == ["foguete"]
    assert marcas[0]["i"] == 0


def test_live_sem_assunto_nao_marca():
    assert ui_anotar._marcas_local(mf, ["Oi, tudo bem por aqui?"]) == []


def test_live_usa_aliases_de_assunto():
    assert nomes(["As eleições municipais acontecem no domingo."]) == ["urna"]
    assert nomes(["A fotossíntese transforma luz em energia química."]) == ["arvore"]
    assert nomes(["A previsão indica chuva forte amanhã."]) == ["nuvem"]


def test_live_nao_usa_secundario(monkeypatch):
    def explode(*args, **kwargs):
        raise AssertionError("o live não deve chamar o modelo secundário")

    monkeypatch.setattr(ui_anotar, "_marcas", explode)
    monkeypatch.setattr(ui_anotar, "_ultimo", {"id": 123})
    ui_anotar.anotar(123, ["Um foguete vence a gravidade e sobe."], True)
