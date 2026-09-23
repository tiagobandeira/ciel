"""
conftest.py — fixtures compartilhadas entre todos os testes Ciel.

Adiciona o diretório raiz ao sys.path automaticamente, então os módulos
do projeto (workspace, trust, tools_registry…) são importáveis em qualquer
teste sem sys.path.insert manual.
"""

import sys
from pathlib import Path

# garante que o projeto é importável independente de onde pytest é chamado
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
