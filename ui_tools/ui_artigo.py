"""Abre um artigo explicativo no palco central, com blocos declarativos (texto, fórmula, gráfico, tabela, SVG animado e imagem)."""
from artigo_schema import validar_artigo


def run(titulo: str, blocos: list) -> str:
    """
    titulo: título curto do artigo explicativo
    blocos: lista de blocos. Tipos: texto {corpo}, formula {tex}, animacao {svg},
            grafico {dados:[{rotulo,a2b2,c2}]}, tabela {colunas,linhas},
            imagem {nome,bio}. Todos aceitam titulo e fala opcionais.
            animacao.svg deve ser SVG inline com animações SMIL (<animate>,
            <animateTransform> ou <animateMotion>), sem script/style/href/URL.
    """
    try:
        artigo = validar_artigo(titulo, blocos)
    except ValueError as e:
        return f"Artigo inválido: {e}"
    import ui_bus
    meta = ui_bus.artigo_meta()
    ui_bus.publish("artefato", fase="inicio", id=artigo["id"], titulo=artigo["titulo"], meta=meta)
    for seq, bloco in enumerate(artigo["blocos"], 1):
        ui_bus.publish("artefato", fase="bloco", id=artigo["id"], seq=seq, bloco=bloco, meta=meta)
    ui_bus.publish("artefato", fase="fim", id=artigo["id"], total=len(artigo["blocos"]), meta=meta)
    return f"Artigo '{artigo['titulo']}' aberto no palco ({len(artigo['blocos'])} blocos, id: {artigo['id']})."
