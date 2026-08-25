# Docs Generator

description: Geração de documentação técnica a partir de código — docstrings, README, referência de API e guias de uso.

## Objetivo

Gerar documentação técnica clara, precisa e útil a partir do código recebido. A documentação deve ser escrita para quem vai **usar** o código, não para quem o escreveu. Não descreva o óbvio — documente intenção, comportamento e casos de uso.

---

## Tipos de documentação — identifique o que foi pedido

### Docstrings / comentários inline
Para funções, classes e módulos. Documente:
- O que faz (não como)
- Parâmetros: tipo, o que representa, valores válidos/inválidos
- Retorno: tipo e o que representa
- Exceções que pode lançar e em quais condições
- Exemplo de uso quando a assinatura não é autoexplicativa

Adapte o formato à linguagem:

**Python — Google style:**
```python
def calcular_desconto(preco: float, percentual: float) -> float:
    """Calcula o preço com desconto aplicado.

    Args:
        preco: Valor original em reais. Deve ser maior que zero.
        percentual: Percentual de desconto entre 0 e 100.

    Returns:
        Preço final após aplicação do desconto.

    Raises:
        ValueError: Se preco <= 0 ou percentual fora do intervalo [0, 100].

    Example:
        >>> calcular_desconto(100.0, 20)
        80.0
    """
```

**JavaScript/TypeScript — JSDoc:**
```javascript
/**
 * Calcula o preço com desconto aplicado.
 * @param {number} preco - Valor original em reais. Deve ser maior que zero.
 * @param {number} percentual - Percentual de desconto entre 0 e 100.
 * @returns {number} Preço final após aplicação do desconto.
 * @throws {Error} Se preco <= 0 ou percentual fora do intervalo [0, 100].
 * @example
 * calcularDesconto(100, 20); // 80
 */
```

**Outros:** adapte ao padrão da linguagem — Rustdoc, Javadoc, YARD (Ruby), etc.

---

### README
Estrutura padrão para projetos:

```markdown
# Nome do Projeto

Descrição em uma ou duas frases — o que é e para quem é.

## Instalação
Comandos mínimos pra rodar. Sem enrolação.

## Uso rápido
O exemplo mais comum de uso, logo de cara.

## Funcionalidades
Lista objetiva do que o projeto faz.

## Referência
Link para documentação completa se existir, ou sumário das principais funções/endpoints.

## Configuração
Variáveis de ambiente, arquivos de config, flags — só o necessário.

## Contribuindo
Se aplicável.
```

Regras para README:
- Primeiro exemplo de uso em no máximo 5 linhas de código
- Sem badges desnecessários
- Sem seção "Motivação" de 3 parágrafos — vá direto ao ponto
- Comandos copiáveis: sempre em bloco de código com a linguagem indicada

---

### Referência de API / funções
Para módulos, bibliotecas ou APIs HTTP. Para cada endpoint ou função pública:

```markdown
## `nome_da_funcao(param1, param2)`

O que faz em uma frase.

**Parâmetros**
| Nome | Tipo | Obrigatório | Descrição |
|------|------|-------------|-----------|
| param1 | str | sim | ... |
| param2 | int | não (padrão: 10) | ... |

**Retorno**
`dict` com campos `x` (str) e `y` (int).

**Erros**
- `ValueError` — se param1 estiver vazio
- `TimeoutError` — se a operação exceder 30s

**Exemplo**
\`\`\`python
resultado = nome_da_funcao("abc", param2=5)
\`\`\`
```

Para APIs HTTP, adicione: método, URL, headers necessários, body de exemplo, resposta de exemplo, códigos de erro.

---

### Guia de uso / tutorial
Para funcionalidades complexas que precisam de contexto:
- Começa com o caso mais simples possível
- Avança gradualmente para casos mais complexos
- Cada seção tem código executável completo
- Explica o porquê das decisões, não só o como
- Aponta armadilhas comuns no final

---

## Regras gerais

**Escreva para o leitor, não para o código**
"Retorna o usuário autenticado ou None se as credenciais forem inválidas" é melhor que "Verifica as credenciais e retorna o resultado".

**Documente o comportamento, não a implementação**
Se a implementação mudar mas o comportamento não, a documentação ainda deve ser válida.

**Seja específico sobre edge cases**
"Retorna lista vazia se não houver resultados" é informação útil. "Retorna resultado" não é.

**Exemplos são obrigatórios quando:**
- A função tem mais de 2 parâmetros
- O retorno é um objeto/dict com múltiplos campos
- O comportamento muda significativamente com diferentes inputs
- O nome da função não deixa claro o que ela faz

**Não documente o óbvio:**
```python
# MAU: incrementa i em 1
i += 1

# BOM: ausência de comentário — o código é autoexplicativo
i += 1

# BOM: comentário que adiciona contexto
i += 1  # próxima página (API usa índice base 1)
```

---

## Língua

Escreva na língua do código existente — se os comentários e nomes estão em português, documenta em português. Se em inglês, em inglês. Se misto, pergunte ao usuário ou use o que predomina.

---

## O que não fazer

- Não parafraseie o código linha a linha
- Não gere documentação para código privado/interno que não será usado por outros
- Não invente comportamentos que não estão no código
- Não omita parâmetros ou casos de erro por preguiça
- Não use "simplesmente", "apenas", "obviamente" — o que é óbvio para quem escreveu não é para quem lê
