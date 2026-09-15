"""
Gera um cronograma de estudos para o ENEM com base na matéria escolhida.
"""

import json

CONTEUDOS_ENEM = {
    "redacao": {
        "assuntos": [
            "Estrutura da Dissertação-Argumentativa",
            "Competências da Redação ENEM",
            "Repertório Sociocultural",
            "Proposta de Intervenção",
            "Coesão e Coerência"
        ],
        "recomendacoes": "Canal Poxalulu no YouTube, Blog do Inep, e redações nota 1000 de anos anteriores."
    },
    "matematica": {
        "assuntos": [
            "Matemática Básica (Razão, Proporção, Porcentagem)",
            "Regra de Três",
            "Geometria Plana e Espacial",
            "Funções (1º e 2º grau, Logarítmica, Exponencial)",
            "Estatística (Média, Mediana, Moda) e Probabilidade"
        ],
        "recomendacoes": "Canal Ferretto Matemática no YouTube, Khan Academy, Plataforma Me Salva!"
    },
    "biologia": {
        "assuntos": [
            "Ecologia (Cadeias Alimentares, Ciclos Biogeoquímicos)",
            "Genética e Biotecnologia",
            "Citologia",
            "Fisiologia Humana",
            "Botânica"
        ],
        "recomendacoes": "Canal Bio com Samuel ou Professor Jubilut, Livros de Biologia do Ensino Médio."
    },
    "historia": {
        "assuntos": [
            "Brasil Colônia e Império",
            "Era Vargas e Ditadura Militar",
            "Revolução Industrial e Francesa",
            "Primeira e Segunda Guerra Mundial",
            "Idade Média e Renascimento"
        ],
        "recomendacoes": "Canal Débora Aladim, Podcasts de História, Documentários do History Channel."
    }
}

def run(materia: str) -> str:
    """
    materia: matéria que o usuário deseja estudar (ex: 'redacao', 'matematica')
    """
    try:
        materia_clean = materia.lower().strip()
        match = None
        for key in CONTEUDOS_ENEM:
            if key in materia_clean:
                match = CONTEUDOS_ENEM[key]
                break
        
        if not match:
            return f"Desculpe, não tenho um cronograma detalhado para '{materia}'. Tente 'redacao', 'matematica', 'biologia' ou 'historia'."

        cronograma = "\n".join([f"- {item}" for item in match['assuntos']])
        return (f"📚 Cronograma de Estudos para {materia.upper()}:\n\n"
                f"Principais Assuntos:\n{cronograma}\n\n"
                f"💡 Recomendações de onde estudar:\n{match['recomendacoes']}")
    except Exception as e:
        return f"Erro ao gerar cronograma: {e}"
