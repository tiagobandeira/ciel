"""
Guard contra SSRF (Server-Side Request Forgery) para as tools de rede do Ciel.

Bloqueia URLs que apontam para a rede local, loopback ou link-local —
endereços que o modelo não deveria conseguir alcançar via http_request,
read_url ou web_search_extended, pois isso permitiria sondar serviços
internos (Ollama, roteador, painéis de admin, metadados de cloud, etc).

Uso:
    from tools._ssrf_guard import check_url
    err = check_url(url)
    if err:
        return err
    # segue com o request
"""

import ipaddress
import socket
from urllib.parse import urlparse

# Ranges bloqueados — privados, loopback, link-local e cloud metadata
_BLOCKED_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),       # loopback IPv4
    ipaddress.ip_network("10.0.0.0/8"),        # privado classe A
    ipaddress.ip_network("172.16.0.0/12"),     # privado classe B
    ipaddress.ip_network("192.168.0.0/16"),    # privado classe C
    ipaddress.ip_network("169.254.0.0/16"),    # link-local (inclui 169.254.169.254 — metadata AWS/GCP)
    ipaddress.ip_network("0.0.0.0/8"),         # rede "this" (não roteável)
    ipaddress.ip_network("::1/128"),           # loopback IPv6
    ipaddress.ip_network("fc00::/7"),          # ULA IPv6 (privado)
    ipaddress.ip_network("fe80::/10"),         # link-local IPv6
]

_ALLOWED_SCHEMES = {"http", "https"}


def check_url(url: str) -> str | None:
    """
    Verifica se a URL é segura para fazer uma requisição de rede.
    Retorna None se for segura, ou uma string de erro se for bloqueada.

    Resolve o hostname pra IP antes de checar — evita bypass via
    subdomínio que aponta pra 127.0.0.1 (ex: localtest.me).
    """
    if not url:
        return "Erro: URL vazia."

    try:
        parsed = urlparse(url)
    except Exception:
        return f"Erro: URL inválida: {url!r}"

    scheme = (parsed.scheme or "").lower()
    if scheme not in _ALLOWED_SCHEMES:
        return f"Erro: scheme '{scheme}' não permitido. Use http:// ou https://"

    hostname = parsed.hostname
    if not hostname:
        return "Erro: URL sem hostname."

    # rejeita diretamente se for localhost ou variantes comuns
    if hostname.lower() in ("localhost", "ip6-localhost", "ip6-loopback"):
        return f"Acesso bloqueado: '{hostname}' aponta para a rede local."

    # resolve o hostname pra IP e verifica contra os ranges bloqueados
    try:
        _, _, ip_list = socket.gethostbyname_ex(hostname)
    except socket.gaierror as e:
        return f"Erro: não foi possível resolver '{hostname}': {e}"

    for ip_str in ip_list:
        try:
            addr = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        for network in _BLOCKED_NETWORKS:
            if addr in network:
                return (
                    f"Acesso bloqueado: '{hostname}' resolve para {ip_str}, "
                    f"que é um endereço de rede local ({network}). "
                    f"Apenas URLs públicas são permitidas."
                )

    return None  # URL segura
