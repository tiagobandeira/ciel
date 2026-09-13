"""Lê o conteúdo de texto de um arquivo PDF usando a biblioteca PyPDF2 com limite opcional de caracteres."""

REQUIREMENTS = ["PyPDF2"]
EXTRA = True
PERMISSIONS = {"path": "read"}

from PyPDF2 import PdfReader

def run(path: str, max_chars: int = 20000) -> str:
    """
    path: caminho para o arquivo PDF a ser lido
    max_chars: número máximo de caracteres a retornar (padrão 20000)
    """
    try:
        reader = PdfReader(path)
        text = ""
        for page in reader.pages:
            text += page.extract_text() + "\n"
            if len(text) > max_chars:
                break
        
        final_text = text[:max_chars]
        
        if not final_text.strip():
            return "O PDF foi lido, mas nenhum texto foi extraído (pode ser um arquivo de imagem/escaneado)."
        
        if len(text) > max_chars:
            return f"{final_text}\n\n[Conteúdo truncado devido ao limite de {max_chars} caracteres]"
            
        return final_text
    except Exception as e:
        return f"Erro ao ler PDF: {e}"