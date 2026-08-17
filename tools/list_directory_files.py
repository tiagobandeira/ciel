"""
Tool para listar arquivos em um diretório específico ou buscar arquivos por padrão.
"""
import os
import fnmatch

def run(directory='.', pattern='*'):
    try:
        if not os.path.exists(directory):
            return f"Erro: O diretório '{directory}' não existe."
        
        files = os.listdir(directory)
        filtered_files = fnmatch.filter(files, pattern)
        
        if not filtered_files:
            return f"Nenhum arquivo encontrado com o padrão '{pattern}' em '{directory}'."
        
        return "\n".join(filtered_files)
    except Exception as e:
        return f"Erro ao listar arquivos: {str(e)}"