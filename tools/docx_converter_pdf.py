"""Converte um .docx para PDF usando LibreOffice (soffice), para conferência visual do resultado."""

import shutil
import subprocess
from pathlib import Path

EXTRA = True


def run(caminho: str, diretorio_saida: str = '') -> str:
    """
    caminho: caminho do arquivo .docx a converter
    diretorio_saida: diretório onde o PDF será gravado (padrão: mesma pasta do .docx)
    """
    try:
        soffice = shutil.which('soffice') or shutil.which('libreoffice')
        if not soffice:
            return 'Erro: LibreOffice (soffice) não encontrado no sistema — instale-o para converter para PDF.'
        src = Path(caminho)
        if not src.is_file():
            return f'Erro: arquivo não encontrado: {caminho}'
        outdir = Path(diretorio_saida) if diretorio_saida else src.parent
        outdir.mkdir(parents=True, exist_ok=True)
        resultado = subprocess.run(
            [soffice, '--headless', '--norestore', '--convert-to', 'pdf', '--outdir', str(outdir), str(src)],
            capture_output=True, text=True, timeout=120)
        pdf = outdir / (src.stem + '.pdf')
        if pdf.is_file():
            return f'PDF gerado: {pdf}'
        return ('Erro: a conversão não produziu PDF. '
                f'stdout={resultado.stdout.strip()} stderr={resultado.stderr.strip()}')
    except subprocess.TimeoutExpired:
        return 'Erro: tempo limite excedido na conversão para PDF.'
    except Exception as e:
        return f'Erro: {e}'
