"""Realiza requisições HTTP (GET, POST, PUT, DELETE) para APIs externas."""

REQUIREMENTS = ["requests"]

import json
import requests

def run(method='GET', url=None, headers=None, data=None, params=None, timeout=10):
    """
    method: método HTTP ('GET', 'POST', 'PUT', 'DELETE')
    url: URL de destino (obrigatória)
    headers: dicionário de cabeçalhos
    data: corpo da requisição — dict vira JSON automaticamente
    params: parâmetros de query string
    timeout: timeout em segundos (padrão: 10)
    """
    if not url:
        return "Erro: URL é obrigatória."

    try:
        is_json = isinstance(data, dict)
        response = requests.request(
            method=method.upper(),
            url=url,
            headers=dict(headers or {}),
            json=data if is_json else None,
            data=data if not is_json else None,
            params=params,
            timeout=timeout,
        )

        try:
            body = response.json()
        except ValueError:
            body = response.text

        return json.dumps({
            "status_code": response.status_code,
            "body": body,
            "headers": dict(response.headers),
        }, ensure_ascii=False)

    except Exception as e:
        return f"Erro: {e}"