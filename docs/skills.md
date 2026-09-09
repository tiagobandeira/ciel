# Skills — CIEL

Skills são arquivos `.md` em `skills/` com instruções detalhadas, exemplos e contexto especializado injetados diretamente no system prompt do modelo secundário. Permitem configurar o secundário para domínios específicos sem sobrecarregar o orquestrador local.

→ Requer o modelo secundário configurado. Veja [docs/secondary-model.md](secondary-model.md).

---

## Como funciona

```
usuário / orquestrador
        │
        ▼
  secondary_model(skill="nome")
        │
        ▼
  lê skills/nome.md
        │
        ▼
  [system padrão do modo] + [conteúdo da skill]
        │
        ▼
  modelo secundário processa com contexto completo
        │
        ▼
  resultado salvo em data/user/<projeto>/
```

O orquestrador local **nunca lê o conteúdo da skill** — ela vai direto pro contexto do modelo grande, que tem janela suficiente pra absorver. O orquestrador só decide quando e qual skill usar.

---

## Estrutura de arquivos

```
skills/
  frontend-visual.md   skill para sites e jogos visuais
  django-api.md        skill para APIs Django REST Framework
  minha-skill.md       skill personalizada do usuário
```

Cada skill é um `.md` simples. Não há formato obrigatório, mas a convenção recomendada é:

```markdown
---
mode: code
---

# Título da Skill

description: Uma linha descrevendo o que a skill faz.

## Seção de contexto
...instruções, convenções, exemplos...
```

O campo `mode:` no frontmatter YAML informa ao orquestrador qual modo usar ao chamar `secondary_model` — sem precisar ler o arquivo inteiro. Valores aceitos: `code` ou `text`. Se omitido, o orquestrador decide pelo tipo de tarefa.

A linha `description:` é usada pela tool `list_skills` para exibir a descrição curta. Se ausente, ela usa o primeiro parágrafo após o título.

---

## Comandos da CLI

| Comando | Ação |
|---|---|
| `/skill` | lista todas as skills disponíveis em `skills/` |
| `/skill <nome>` | exibe o conteúdo da skill |
| `/skill <nome> <prompt>` | executa o prompt usando a skill no modelo secundário |
| `/analisar <caminho>` | absorve skill externa e a replica como primitivas nativas (Grande Sábio) |

### Exemplos

```bash
# listar skills disponíveis
/skill

# ver o conteúdo de uma skill
/skill frontend-visual

# executar com skill ativa
/skill frontend-visual cria um site de planetário interativo com animações e design futurista

/skill django-api cria uma API REST de gerenciamento de tarefas com autenticação JWT

# absorver skill externa do repositório oficial da Anthropic
/analisar ~/downloads/skills-main/skills/docx

# absorver skill simples em .md
/analisar ~/downloads/minha-skill.md
```

O autocompletar (Tab) sugere os nomes das skills disponíveis após `/skill `.

---

## Ativação automática pelo orquestrador

O orquestrador pode selecionar e usar uma skill sem intervenção do usuário:

1. Identifica que a tarefa se encaixa num domínio especializado
2. Chama `list_skills` para ver as disponíveis
3. Chama `secondary_model` com `skill="nome"` diretamente

Isso acontece quando o orquestrador reconhece que o problema exige o secundário e que existe uma skill adequada. O usuário pode simplesmente descrever o que quer normalmente — sem precisar usar `/skill`.

---

## Skills integradas ao agente

Skills podem ser vinculadas diretamente a uma persona em seu arquivo `.md` em `agents/`. Quando o agente é carregado, o bloco de skills é injetado automaticamente no system prompt do orquestrador — sem precisar de `/skill` ou `list_skills`.

### Definindo skills no agente

Adicione uma seção `## Skills` no `.md` do agente:

```markdown
## Skills
frontend-visual: obrigatoria
code-review: sugerida
data-analysis: opcional
```

Formato por linha: `<nome-da-skill>: <nível>`. Skill sem nível cai em `opcional`.

### Níveis de prioridade

| Nível | Comportamento do orquestrador |
|---|---|
| `obrigatoria` | chama `secondary_model` com essa skill automaticamente quando a tarefa se encaixar — não espera o usuário pedir |
| `sugerida` | avalia antes de responder se a skill se encaixa; usa se fizer sentido |
| `opcional` | disponível via comando `/skill` ou decisão própria do orquestrador |

### O que o orquestrador recebe

Ao carregar o agente, o system prompt inclui automaticamente:

```
## Skills desta persona
Você tem as seguintes skills disponíveis. Respeite o nível de cada uma:

- **frontend-visual** [obrigatoria]: use sempre que a tarefa se encaixar — não espere o usuário pedir
- **code-review** [sugerida]: considere usar quando a tarefa se encaixar — você decide se é necessário
```

### Exemplo de agente com skills

```markdown
# Frontend Dev

## Persona
Você é um desenvolvedor frontend especializado em interfaces visuais ricas...

## Skills
frontend-visual: obrigatoria
code-review: sugerida

## Comportamento
- Sempre que a tarefa envolver criação de UI, use secondary_model com skill="frontend-visual" e mode="code"
- Após qualquer chamada com mode="code", use list_directory no caminho retornado
```

> **Atenção ao contexto:** cada skill adicionada aumenta os tokens enviados ao modelo secundário. Com agentes que têm várias skills `obrigatoria`, considere aumentar `max_tokens` em `ciel_config.json`.

---

## Modos de execução

Skills funcionam com os dois modos do modelo secundário:

**`mode="text"`** — análise, documentação, resumo, texto longo. A skill adiciona contexto ao system prompt e a resposta é salva em `.md` em `data/user/`.

**`mode="code"`** — geração de código com arquivos separados. A skill instrui convenções, estrutura e padrões. O secundário retorna JSON com `files[]` e a tool salva cada arquivo na pasta do projeto em `data/user/<projeto>_<ts>/`.

O modo é definido pelo campo `mode:` no frontmatter da skill. Se ausente, o orquestrador decide pelo tipo de tarefa.

### Fase build (mode=code)

Ao usar `mode="code"`, o terminal exibe o progresso em tempo real:

```
  ⠋ gerando... index.html
  ⠋ gerando... style.css
  ⠋ gerando... script.js
  ✔ stream concluído · 214s · 16,643 chars

 ──────────── index.html ────────────
   1 <!DOCTYPE html>
   2 <html lang="pt-BR">
   ...

 ──────────────────────────────────
  index.html (4,231c)  style.css (3,892c)  script.js (2,108c)
```

Se o modelo atingir o limite de tokens antes de concluir:

```
  ⚠ resposta incompleta — o modelo pode ter atingido o limite de tokens
  dica: aumente max_tokens em ciel_config.json (atual: 32,768)
```

O valor padrão recomendado para projetos maiores é `32768`. Verifique o limite máximo do seu provider.

---

## Criando uma skill

Crie um arquivo `.md` em `skills/` com o nome em `kebab-case`:

```bash
# exemplo
skills/minha-skill.md
```

### O que colocar numa skill

Skills são eficazes quando incluem:

- **Filosofia ou objetivo** — o que o modelo deve priorizar nesse domínio
- **Estrutura esperada** — como organizar arquivos, pastas, componentes
- **Convenções obrigatórias** — padrões de código, nomenclatura, segurança
- **Exemplos curtos** — snippets de referência que o modelo pode adaptar
- **O que evitar** — antipadrões comuns que o modelo tende a usar

Quanto mais contexto e exemplos, melhor — o secundário tem janela grande e vai usar tudo.

### Template mínimo

```markdown
---
mode: code
---

# Nome da Skill

description: O que essa skill faz em uma linha.

## Objetivo

Descreva o que o modelo deve entregar e com qual qualidade.

## Estrutura

Como organizar os arquivos ou componentes do resultado.

## Convenções

- Regra 1
- Regra 2
- Regra 3

## Exemplos

\`\`\`linguagem
// snippet de referência
\`\`\`

## O que evitar

- Antipadrão 1
- Antipadrão 2

## Formato de Output Obrigatório

Se mode=code e o formato de output não for HTML/CSS/JS padrão,
especifique aqui as extensões e estrutura do JSON esperado.
Isso evita que o modelo use o template padrão incorretamente.
```

---

## Compatibilidade com o padrão da comunidade

O Ciel suporta absorção de skills externas que seguem o padrão Agent Skills — o formato aberto adotado pela Anthropic e pela comunidade em geral. Isso permite usar skills do repositório oficial ou de terceiros diretamente no Ciel.

### O padrão Agent Skills

O padrão é definido em [agentskills.io](http://agentskills.io) e adotado pelo repositório oficial da Anthropic:

→ **[github.com/anthropics/skills](https://github.com/anthropics/skills)** — skills de referência cobrindo criação de documentos, análise de dados, design, desenvolvimento e automações enterprise.

→ **[Como criar skills personalizadas](https://support.claude.com/pt/articles/12512198-como-criar-habilidades-personalizadas)** — guia oficial da Anthropic com estrutura, campos obrigatórios e boas práticas.

Uma skill no padrão da comunidade é um diretório com pelo menos:

```
minha-skill/
  SKILL.md       ← instruções + frontmatter YAML (name, description)
  script.py      ← opcional: código executável
  resources/     ← opcional: arquivos de referência
```

O `SKILL.md` segue este formato mínimo:

```markdown
---
name: nome-da-skill
description: O que a skill faz e quando usá-la (até 200 chars)
dependencies: pacote1>=1.0, pacote2  # opcional
---

# Nome da Skill

Instruções, exemplos e convenções que o modelo deve seguir.
```

### Como o Ciel absorve skills externas — o Grande Sábio

O Ciel não executa skills externas diretamente. Em vez disso, o comando `/analisar` aciona o **Grande Sábio** (modelo secundário), que lê todos os arquivos da skill e a replica como primitivas nativas:

```
skill externa (SKILL.md + scripts + resources)
        │
        ▼
  /analisar <caminho>
        │
        ▼
  Grande Sábio analisa e classifica
        │
        ├── plugin   → gera tools em tools/
        ├── pipeline → gera tasks em tasks/
        └── context  → salva instrução em skills/
        │
        ▼
  manifesto skills/<nome>_meta.json
  registry recarregado automaticamente
```

A absorção é feita uma vez. Depois disso, as primitivas geradas rodam localmente sem custo adicional de tokens.

### Tipos de absorção

| Tipo | Quando ocorre | O que o Ciel gera |
|---|---|---|
| **plugin** | skill traz capacidades independentes (tools/scripts) | tools nativas em `tools/` |
| **pipeline** | skill define processo sequencial com etapas | tasks em `tasks/` + tools |
| **context** | skill é instrução pura sem código executável | `.md` em `skills/` para uso via `/skill` |

### O que é compatível e o que não é

Skills do padrão da comunidade que contêm apenas `SKILL.md` com instruções são absorvidas como **context** ou **plugin** de forma transparente. A maioria das skills disponíveis no repositório oficial se encaixa aqui.

Skills com scripts Python ou Node.js são absorvidas como **plugin** — o Grande Sábio analisa o código e gera tools equivalentes no formato Ciel. A lógica é preservada; a interface (`def run(...)`) é adaptada.

O que não é portado automaticamente: dependências de ambiente muito específicas, chamadas a APIs proprietárias sem equivalente local, ou scripts que assumem o runtime do Claude.ai. Nesses casos, o Grande Sábio salva o contexto como instrução residual e informa o que não foi possível replicar.

### Exemplo prático

A skill `docx` do repositório oficial da Anthropic foi absorvida pelo Ciel via `/analisar`:

```bash
/analisar C:\...\skills-main\skills\docx
# Grande Sábio analisou 17 arquivos · 87,405 chars
# → 6 tools geradas: docx_criar, docx_ler, docx_substituir_texto,
#                    docx_aceitar_mudancas, docx_comentar, docx_converter_pdf
# → contexto residual: skills/docx.md (notas de limitações)
# → manifesto: skills/docx_meta.json
```

Depois da absorção, as tools ficam disponíveis nativamente — o orquestrador local as usa sem precisar chamar o modelo secundário.

---

## Skills incluídas

### `frontend-visual`

Sites, landing pages e jogos com design robusto e animações fluidas. Cobre:

- Dark themes com profundidade visual (glassmorphism, glow, parallax)
- Canvas com `requestAnimationFrame` para partículas e estrelas
- Animações CSS via `@keyframes` e `IntersectionObserver` para entrada de elementos
- Parallax com mouse via `mousemove`
- Separação obrigatória em `index.html`, `style.css` e `script.js`
- Fontes recomendadas por tema (espacial, tecnologia, luxo, natureza)
- Checklist de qualidade antes de entregar

Funciona com qualquer tema visual — espacial, hacking, luxo, natureza, etc. O modelo deriva paleta e estilo a partir do prompt.

### `code-review`

Revisão técnica de código com foco em bugs, segurança e legibilidade. Cobre:

- Estrutura fixa em 4 seções: resumo geral, bugs críticos, segurança, legibilidade
- Formato `localização → impacto → correção` para cada problema
- Critérios explícitos por categoria (condições de borda, injection, magic numbers, etc.)
- Priorização: crítico > segurança > legibilidade

Linguagem agnóstica. Passa o arquivo ou trecho de código no prompt.

### `refactor`

Refatoração com preservação de comportamento e relatório das mudanças. Cobre:

- Entrega do código refatorado completo + relatório nomeando cada técnica aplicada
- Catálogo de refatorações permitidas (extract function, guard clause, DRY, etc.)
- Instrução explícita de não corrigir bugs silenciosamente — aponta e pergunta
- Regras sobre quando não refatorar (over-engineering, DRY forçado)

### `docs-generator`

Geração de documentação técnica a partir de código. Cobre:

- Docstrings em Google style (Python), JSDoc (JS/TS) e outros formatos por linguagem
- README com estrutura padronizada e regras de objetividade
- Referência de API com tabela de parâmetros, retorno, erros e exemplos
- Guias de uso com progressão do simples ao complexo
- Regras do que não documentar (óbvio, implementação, linha a linha)

### `data-analysis`

Análise exploratória de dados com Python e pandas. Cobre:

- Sequência completa de EDA: inspeção → nulos → duplicatas → distribuições → correlações → temporal → achados
- Código de referência para cada etapa com `matplotlib` e `seaborn`
- Critérios de decisão para tratamento de nulos por percentual
- Testes estatísticos e quando aplicar cada um
- Padrões de limpeza de dados (tipos, strings, datas, valores numéricos)
- Instrução de sempre interpretar resultados em texto, não só entregar código

---

## Diferença entre skills e tasks

| | Tasks | Skills |
|---|---|---|
| **Onde fica** | `tasks/*.md` | `skills/*.md` |
| **Quem executa** | orquestrador local | modelo secundário |
| **Tamanho** | curto — ações em linguagem natural | longo — instruções detalhadas com exemplos |
| **Propósito** | definir um fluxo de ações | definir um domínio de conhecimento |
| **Contexto** | limitado à janela do orquestrador | absorvido pelo modelo grande |
| **Ativação** | `/task <nome>` | `/skill <nome> <prompt>` ou automático |

Tasks orquestram **o que fazer**. Skills instruem **como fazer**, com contexto que o orquestrador local não conseguiria carregar.

---

## Testando sem provider (mock)

Para testar o fluxo do orquestrador sem depender de um provider externo, ative o modo mock em `ciel_config.json`:

```json
"mock_secondary": true,
"mock_type": "code"
```

Tipos disponíveis:

| `mock_type` | O que simula |
|---|---|
| `"code"` | JSON válido com `files[]` — testa salvamento e `list_directory` |
| `"text"` | resposta markdown curta |
| `"text_long"` | resposta longa — testa fallback de salvamento em `.md` |
| `"invalid"` | JSON malformado — testa fallback do `mode=code` |
| `"error"` | HTTP 503 — testa retry/backoff |
| `"quota"` | simula cota esgotada |

Respostas customizadas podem ser definidas em `data/mock/mock_responses.json` — editável sem tocar no código. Para voltar ao modo real: `"mock_secondary": false`.

---

## Dicas de uso

**Skills longas funcionam melhor** — não se preocupe com o tamanho. O secundário foi escolhido justamente pela janela grande. Exemplos detalhados e convenções explícitas melhoram significativamente o resultado.

**Declare `mode:` no frontmatter** — evita que o orquestrador adivinhe e use o modo errado. Para skills que geram código, sempre declare `mode: code`.

**Para formatos não-padrão, adicione "Formato de Output Obrigatório"** — se a skill gera `.ipynb`, `.py` ou qualquer coisa diferente de HTML/CSS/JS, a seção de formato sobrescreve o template padrão do `_SYSTEM_CODE` e evita que o modelo gere um site quando devia gerar um notebook.

**Aumente `max_tokens` para projetos maiores** — o valor padrão de `16384` pode não ser suficiente para projetos com múltiplos arquivos grandes. Use `32768` como base e ajuste conforme o provider.

**Skills pessoais não precisam ser genéricas** — crie skills específicas pro seu stack, suas convenções de projeto, seu estilo de código. Elas ficam em `skills/` e não são versionadas se você preferir manter no `.gitignore` pessoal.

**Vincule skills ao agente para não precisar do comando `/skill`** — com `obrigatoria` no agente certo, o orquestrador aciona automaticamente sem intervenção.