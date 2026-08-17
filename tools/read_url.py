"""Baixa uma página web e retorna o texto limpo (sem HTML)."""

REQUIREMENTS = ["requests", "beautifulsoup4"]

def run(url: str, max_chars: int = 20000) -> str:
    """
    url: URL completa da página (deve começar com http:// ou https://)
    max_chars: limite de caracteres retornados (padrão 20000)
    """
    try:
        import requests
        from bs4 import BeautifulSoup

        if not url.startswith(("http://", "https://")):
            return "Erro: URL deve começar com http:// ou https://"

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        }

        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()

        # detecta encoding pelo header ou meta tag
        resp.encoding = resp.apparent_encoding

        soup = BeautifulSoup(resp.text, "html.parser")

        # remove ruído: scripts, estilos, nav, footer, ads
        for tag in soup(["script", "style", "nav", "footer", "header",
                          "aside", "form", "noscript", "iframe"]):
            tag.decompose()

        # tenta pegar o conteúdo principal primeiro
        main = (
            soup.find("article")
            or soup.find("main")
            or soup.find(id="content")
            or soup.find(class_="content")
            or soup.find(class_="post-content")
            or soup.find(class_="entry-content")
            or soup.body
        )

        if main is None:
            return "Erro: não foi possível extrair conteúdo da página."

        # extrai texto com separação de blocos
        lines = []
        for elem in main.find_all(
            ["h1", "h2", "h3", "h4", "p", "li", "td", "th", "pre", "code", "blockquote"]
        ):
            text = elem.get_text(separator=" ", strip=True)
            if text:
                lines.append(text)

        if not lines:
            # fallback: texto bruto do body
            lines = [main.get_text(separator="\n", strip=True)]

        result = "\n\n".join(lines)

        if len(result) > max_chars:
            result = result[:max_chars] + f"\n\n[... truncado em {max_chars} chars]"

        return result if result.strip() else "Erro: página não retornou conteúdo legível."

    except requests.exceptions.Timeout:
        return "Erro: timeout ao acessar a URL (>15s)."
    except requests.exceptions.ConnectionError:
        return "Erro: não foi possível conectar à URL."
    except requests.exceptions.HTTPError as e:
        return f"Erro HTTP {e.response.status_code}: {e}"
    except Exception as e:
        return f"Erro: {e}"
