"""
Tool para coletar informações básicas de hardware e sistema operacional.
"""
import platform
import psutil

def run():
    try:
        info = {
            'sistema': platform.system(),
            'versao_os': platform.version(),
            'arquitetura': platform.machine(),
            'processador': platform.processor(),
            'nucleos_fisicos': psutil.cpu_count(logical=False),
            'nucleos_logicos': psutil.cpu_count(logical=True),
            'memoria_total_gb': round(psutil.virtual_memory().total / (1024**3), 2),
            'memoria_disponivel_gb': round(psutil.virtual_memory().available / (1024**3), 2)
        }
        return info
    except Exception as e:
        return {'error': str(e)}