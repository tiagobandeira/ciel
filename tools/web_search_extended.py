"""Pesquisa na web e extrai conteúdo completo das páginas encontradas."""

REQUIREMENTS = ["ddgs", "requests", "beautifulsoup4", "lxml"]

from ddgs import DDGS
import requests
from bs4 import BeautifulSoup
import re
from urllib.parse import urlparse


def _clean_text(html: str) -> str:
    """Remove tags HTML, scripts e estilos, retornando texto limpo."""
    soup = BeautifulSoup(html, "lxml")
    # Remove scripts, estilos, navegação, rodapé
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()
    # Pega o texto e limpa espaços extras
    text = " ".join(soup.get_text().split())
    # Remove URLs e caracteres repetidos
    text = re.sub(r"http\S+", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _scrape_page(url: str, timeout: int = 10, max_chars: int = 3000) -> str:
    """Baixa e extrai o conteúdo principal de uma página."""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        resp = requests.get(url, headers=headers, timeout=timeout)
        resp.raise_for_status()
        content = _clean_text(resp.text)
        if len(content) > max_chars:
            content = content[:max_chars] + "..."
        return content
    except Exception as e:
        return f"[Erro ao extrair: {e}]"


def run(query: str, limit: int = 5, extract: bool = False, max_results_with_content: int = 1) -> str:
    """
    query: termo de busca
    limit: número máximo de resultados na lista (padrão: 5)
    extract: se True, extrai o conteúdo completo das páginas (padrão: False)
    max_results_with_content: número de resultados que terão conteúdo extraído (padrão: 1, só o primeiro)
    """
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=limit))
        if not results:
            return f"Nenhum resultado encontrado para '{query}'."

        linhas = []
        for i, r in enumerate(results, 1):
            title = r.get("title", "Sem título")
            url = r.get("href", "")
            body = r.get("body", "")

            entrada = f"[{i}] {title}\n    {url}"
            if body:
                entrada += f"\n    {body[:300]}"

            # Extração de conteúdo completo (se solicitado)
            if extract and i <= max_results_with_content:
                entrada += "\n\n    📄 Conteúdo extraído:\n    " + _scrape_page(url)

            linhas.append(entrada)

        cabecalho = f"Resultados para '{query}' via DuckDuckGo ({len(linhas)} encontrados):\n\n"
        return cabecalho + "\n\n".join(linhas)

    except ImportError:
        return "Erro: bibliotecas não instaladas. Execute: pip install ddgs requests beautifulsoup4 lxml"
    except Exception as e:
        return f"Erro ao pesquisar: {e}"