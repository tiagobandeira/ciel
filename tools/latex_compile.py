"""
Compila arquivos .tex para PDF, garantindo que todos os arquivos de saída fiquem na mesma pasta do arquivo original.
"""

import subprocess
from pathlib import Path

def run(tex_path: str) -> str:
    """
    tex_path: caminho para o arquivo .tex a ser compilado
    """
    try:
        path = Path(tex_path)
        if not path.exists():
            return f"Erro: Arquivo {tex_path} não encontrado."

        # Define o diretório de trabalho como a pasta onde o arquivo .tex está
        working_dir = path.parent

        result = subprocess.run(
            ["pdflatex", "-interaction=nonstopmode", path.name],
            cwd=str(working_dir),
            capture_output=True,
            text=True,
            timeout=60
        )

        if result.returncode != 0:
            return f"Erro na compilação:\n{result.stdout}\n{result.stderr}"

        pdf_path = path.with_suffix(".pdf")
        if pdf_path.exists():
            return f"Sucesso! Arquivos gerados em {working_dir}. PDF: {pdf_path}"
        else:
            return "O pdflatex reportou sucesso, mas o PDF não foi encontrado na pasta."

    except Exception as e:
        return f"Erro inesperado: {e}"
