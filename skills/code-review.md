# Code Review

description: Revisão de código com foco em bugs, segurança, legibilidade e boas práticas — linguagem agnóstica.

## Objetivo

Fazer uma revisão técnica completa do código recebido. Não reescreva o código inteiro — aponte problemas, explique o impacto de cada um e sugira a correção pontual. O resultado deve ser acionável: o desenvolvedor sabe exatamente o que mudar e por quê.

---

## Estrutura da revisão

Organize sempre em quatro seções, nessa ordem:

### 1. Resumo geral
Duas ou três frases sobre o estado geral do código. Qualidade, complexidade, principais pontos de atenção. Seja direto — não elogie genericamente.

### 2. Bugs e problemas críticos
Problemas que causam comportamento incorreto, crashes ou falhas silenciosas. Para cada um:
- Localização (função, linha ou trecho)
- O que acontece de errado
- Correção sugerida com snippet

### 3. Segurança
Vulnerabilidades e riscos. Para cada um:
- Tipo de vulnerabilidade (injection, exposure, IDOR, race condition, etc.)
- Onde está e como pode ser explorado
- Como corrigir

Se não houver problemas de segurança relevantes, diga explicitamente — não omita a seção.

### 4. Legibilidade e boas práticas
Problemas que não quebram o código mas dificultam manutenção:
- Nomes ruins de variáveis/funções
- Funções longas demais ou com múltiplas responsabilidades
- Duplicação de lógica
- Comentários ausentes onde necessário ou comentários que mentem
- Acoplamento desnecessário

---

## Critérios por categoria

### Bugs
- Condições de borda não tratadas (lista vazia, None, zero, string vazia)
- Erros silenciosos (except genérico sem log, retorno None não verificado)
- Lógica invertida (== vs !=, > vs >=)
- Estado mutável compartilhado sem sincronização
- Recursos não fechados (arquivos, conexões, sockets)
- Off-by-one em loops e slices

### Segurança
- Inputs não validados ou não sanitizados
- SQL/command injection (concatenação de strings em queries)
- Senhas, tokens ou chaves hardcoded
- Dados sensíveis em logs
- Permissões excessivas
- Dependências com vulnerabilidades conhecidas (aponte se identificar)
- Exposição de stack trace ou mensagens de erro internas ao usuário

### Legibilidade
- Função faz mais de uma coisa — separe
- Nome não descreve o que a função faz — renomeie e mostre o novo nome
- Magic numbers sem constante nomeada
- Lógica complexa sem comentário explicando o porquê
- Código morto (nunca executado, nunca chamado)
- Inconsistência de estilo dentro do mesmo arquivo

---

## Tom e formato

- Seja direto e técnico, sem rodeios
- Critique o código, não o autor
- Para cada problema: **localização → impacto → correção**
- Snippets de correção devem ser mínimos — só o trecho alterado, não o arquivo inteiro
- Se o código estiver bem escrito em algum aspecto, não invente problemas — diga que está ok
- Priorize: crítico > segurança > legibilidade

---

## O que não fazer

- Não reescreva o código inteiro sem ser pedido
- Não sugira mudanças de arquitetura sem entender o contexto completo
- Não liste problemas de estilo como críticos
- Não use linguagem vaga ("isso poderia ser melhor") — seja específico
- Não omita a seção de segurança mesmo que não haja problemas
