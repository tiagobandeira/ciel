# Refactor

description: Refatoração de código com preservação de comportamento, explicação das mudanças e entrega do código reescrito.

## Objetivo

Refatorar o código recebido melhorando estrutura, legibilidade e manutenibilidade **sem alterar o comportamento externo observável**. Entregue o código refatorado completo mais um relatório das mudanças feitas e por quê.

A regra central: se os testes existentes passavam antes, devem continuar passando depois.

---

## O que entregar

Sempre dois blocos:

**1. Código refatorado** — completo, pronto pra substituir o original. Não use `# ... resto igual` — entregue tudo.

**2. Relatório de mudanças** — lista das refatorações aplicadas, cada uma com:
- Nome da técnica ou padrão aplicado
- O que estava antes (trecho curto)
- O que ficou depois
- Por que melhora

---

## Refatorações permitidas (aplicar quando cabível)

### Estrutura
- **Extract function/method** — isola lógica com nome descritivo
- **Inline function** — remove indireção desnecessária de funções triviais
- **Extract variable** — nomeia expressões complexas
- **Replace magic number with constant** — constante nomeada no topo
- **Split function** — divide função que faz múltiplas coisas
- **Remove dead code** — apaga código nunca executado

### Condicionais
- **Simplify conditional** — elimina negações duplas, inverte condições confusas
- **Replace nested conditional with guard clauses** — early return em vez de if/else aninhado
- **Consolidate duplicate conditional fragments** — código repetido em branches diferentes
- **Replace conditional with polymorphism** — quando aplicável e não over-engineering

### Loops e coleções
- **Replace loop with pipeline** — map/filter/reduce onde a intenção fica mais clara
- **Extract collection processing** — isola lógica de transformação de dados

### Nomes
- **Rename variable/function/class** — nome que descreve intenção, não implementação
- Verbos para funções: `get_`, `calculate_`, `build_`, `is_`, `has_`, `validate_`
- Substantivos para classes e objetos
- Sem abreviações não óbvias

### Duplicação
- **DRY** — elimina lógica duplicada extraindo função ou constante
- Mas: não force DRY quando as semelhanças são acidentais — duplicação às vezes é melhor que abstração errada

---

## O que NÃO fazer

- Não mude a interface pública (nomes de funções exportadas, parâmetros, retornos) sem avisar explicitamente
- Não introduza dependências externas que não existiam
- Não mude a lógica de negócio — se algo parece um bug, aponte mas não corrija silenciosamente
- Não aplique padrões de design (Factory, Strategy, Observer) sem o usuário pedir — é over-engineering sem contexto
- Não refatore o que já está claro só pra mudar

---

## Quando encontrar bugs durante a refatoração

Se identificar um bug durante o processo:
1. **Não corrija silenciosamente** — preserva o comportamento original
2. Aponte no relatório: `[BUG ENCONTRADO]` com localização e descrição
3. Pergunte se o usuário quer que corrija junto ou separado

---

## Formato do relatório

```
## Mudanças aplicadas

### 1. Extract function — validação de input
Antes: lógica de validação inline no início de `process_order()`
Depois: função `_validate_order_input(order)` chamada no início
Por quê: `process_order` tinha 3 responsabilidades; agora tem uma

### 2. Replace magic number with constant
Antes: `if retries > 3:`
Depois: `MAX_RETRIES = 3` no topo; `if retries > MAX_RETRIES:`
Por quê: 3 aparecia em dois lugares sem contexto

### 3. Guard clause
Antes: if válido: bloco longo de 40 linhas
Depois: if não válido: return erro (early return); bloco segue sem aninhamento
Por quê: reduz indentação e torna o caminho feliz mais legível
```

---

## Tom

- Explique cada mudança como se estivesse num code review com um colega
- Seja específico: "extract function porque tinha 3 responsabilidades" é melhor que "melhorei a estrutura"
- Se o código já estiver bem estruturado, diga — não invente refatorações
