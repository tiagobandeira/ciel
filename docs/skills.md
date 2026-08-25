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
# Título da Skill

description: Uma linha descrevendo o que a skill faz.

## Seção de contexto
...instruções, convenções, exemplos...
```

A linha `description:` é usada pela tool `list_skills` para exibir a descrição curta. Se ausente, ela usa o primeiro parágrafo após o título.

---

## Comandos da CLI

| Comando | Ação |
|---|---|
| `/skill` | lista todas as skills disponíveis em `skills/` |
| `/skill <nome>` | exibe o conteúdo da skill |
| `/skill <nome> <prompt>` | executa o prompt usando a skill no modelo secundário |

### Exemplos

```bash
# listar skills disponíveis
/skill

# ver o conteúdo de uma skill
/skill frontend-visual

# executar com skill ativa
/skill frontend-visual cria um site de planetário interativo com animações e design futurista

/skill django-api cria uma API REST de gerenciamento de tarefas com autenticação JWT
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

## Modos de execução

Skills funcionam com os dois modos do modelo secundário:

**`mode="text"`** — análise, documentação, resumo, texto longo. A skill adiciona contexto ao system prompt e a resposta é salva em `.md` em `data/user/`.

**`mode="code"`** — geração de código com arquivos separados. A skill instrui convenções, estrutura e padrões. O secundário retorna JSON com `files[]` e a tool salva cada arquivo na pasta do projeto em `data/user/<projeto>_<ts>/`.

O modo é decidido pelo orquestrador com base no tipo de tarefa, independente da skill usada.

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
```

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

## Dicas de uso

**Skills longas funcionam melhor** — não se preocupe com o tamanho. O secundário foi escolhido justamente pela janela grande. Exemplos detalhados e convenções explícitas melhoram significativamente o resultado.

**Combine com o modo correto** — para código use `/skill nome prompt` e deixe o orquestrador escolher `mode="code"`. Para análise e documentação o orquestrador vai para `mode="text"` naturalmente.

**Skills pessoais não precisam ser genéricas** — crie skills específicas pro seu stack, suas convenções de projeto, seu estilo de código. Elas ficam em `skills/` e não são versionadas se você preferir manter no `.gitignore` pessoal.

**O orquestrador aprende a usar** — com o tempo de uso numa sessão, o orquestrador passa a associar tipos de tarefa com skills disponíveis e aciona automaticamente sem precisar do comando `/skill`.
