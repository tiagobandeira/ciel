# Fontes — Base de Conhecimento do Agente

Permite indexar arquivos locais e páginas web para que o agente consulte o conteúdo
de forma seletiva durante a conversa, sem precisar carregar tudo no contexto.

Inspirado no NotebookLM: fontes persistentes + recuperação por relevância + síntese contextual.

---

## Comandos disponíveis

```
/source <caminho>              indexa arquivo na sessão atual
/source <url>                  indexa página web na sessão atual
/source --global <caminho>     indexa como fonte compartilhada do agente
/source --global <url>         indexa página web como fonte compartilhada
/source --listar               lista fontes disponíveis com IDs
/source --remover <id>         remove uma fonte pelo ID
/source --limpar-orfas         remove fontes de sessões já deletadas
```

Formatos suportados: `.pdf`, `.txt`, `.md`, URLs (`http://`, `https://`)

Após indexar, o agente consulta as fontes automaticamente quando necessário.
Você também pode pedir explicitamente:

```
quais fontes você tem disponíveis?
o que o documento diz sobre X?
```

---

## Fontes via URL

O agente aceita URLs como fonte diretamente:

```
/source https://en.wikipedia.org/wiki/Ollama
/source --global https://docs.exemplo.com/referencia
```

O conteúdo da página é baixado, extraído e salvo localmente em
`knowledge/cache/<session_id>/` — assim o agente não precisa
refazer o fetch a cada consulta e o conteúdo fica disponível
mesmo que a página mude ou saia do ar.

**Limitação:** páginas que dependem de JavaScript para renderizar
o conteúdo (SPAs) podem retornar poucos dados. Páginas estáticas
como Wikipedia, documentação técnica, blogs e artigos funcionam bem.

### Cache por sessão

```
knowledge/cache/
  <session_id>/       → removido junto com a sessão
    a3f9c2b1.txt      → primeira linha = URL original
  _shared/            → fontes globais, remoção manual via --remover
```

A primeira linha de cada arquivo de cache é a URL original —
útil para identificar a origem e para limpeza manual se necessário.

---

## Escopos

As fontes seguem uma hierarquia de visibilidade:

```
_shared         → disponível em todas as sessões do agente
session_id      → disponível só na sessão atual e seus branches
```

### Por agente

Cada agente tem sua própria base de fontes — um agente não acessa as fontes de outro.

```
# no csv_manager
/source relatorio.txt
quais fontes você tem disponíveis?
# → mostra relatorio.txt

/agente general
quais fontes você tem disponíveis?
# → NÃO mostra relatorio.txt
```

### Por sessão

Fontes indexadas numa sessão não aparecem em sessões novas do mesmo agente.

```
# sessão A — csv_manager
/source dados.csv
quais fontes você tem disponíveis?
# → mostra dados.csv

/novo
quais fontes você tem disponíveis?
# → NÃO mostra dados.csv (pertence à sessão A)
```

### Fonte compartilhada (`--global`)

Fontes globais persistem entre todas as sessões do agente.
Use para documentação de referência que o agente sempre deve consultar —
manuais, esquemas, glossários, regras do projeto.

```
/source --global manual.txt
quais fontes você tem disponíveis?
# → mostra manual.txt

/novo
quais fontes você tem disponíveis?
# → ainda mostra manual.txt

/agente general
quais fontes você tem disponíveis?
# → NÃO mostra manual.txt (é _shared do csv_manager, não do general)
```

### Branch herda fontes do pai

Ao criar um branch de uma sessão, o agente tem acesso às fontes
indexadas em toda a cadeia de sessões ancestrais.

```
# sessão pai — csv_manager
/source contrato.pdf
/history salvar
/history → seleciona a sessão → b (branch)

quais fontes você tem disponíveis?
# → mostra contrato.pdf (herdado da sessão pai)
```

> **Nota:** branches herdam acesso às fontes do pai via banco, mas o cache
> de URLs fica na pasta da sessão original. O arquivo `.txt` continua
> acessível enquanto a sessão pai existir.

---

## Gerenciamento de fontes

### Listar fontes disponíveis

```
/source --listar
```

Exemplo de saída:
```
3 fonte(s):

  id=1   manual.txt                    (3 chunks · compartilhada)
    ↳ Guia de instalação do sistema...
  id=5   contrato.pdf                  (12 chunks · sessão 17)
    ↳ Contrato de prestação de serviços...
  id=10  en_wikipedia_org__Ollama.url  (12 chunks · sessão 41)
    ↳ Ollama  Developers  Ollama Inc. and contributors...
```

### Remover uma fonte

```
/source --remover <id>
```

Remove a fonte e todos os seus chunks do banco. Para fontes de URL,
também apaga o arquivo de cache local. Se for a última URL da sessão,
a pasta de cache da sessão é removida junto.

```
/source --listar
# id=10  en_wikipedia_org__Ollama.url  (12 chunks · sessão 41)

/source --remover 10
# ✓ fonte removida (id=10 · en_wikipedia_org__Ollama.url)
```

### Limpar fontes órfãs

```
/source --limpar-orfas
```

Remove fontes cujo `session_id` não existe mais no histórico de conversas.
Útil para limpar inconsistências após deleção manual do banco de histórico
ou outros casos atípicos.

---

## Como o agente usa as fontes

O agente tem três tools internas para consultar a base de conhecimento:

| Tool | O que faz |
|---|---|
| `list_sources` | lista fontes disponíveis com ID e resumo |
| `search_knowledge` | busca trechos relevantes por query |
| `read_source` | lê o conteúdo completo de uma fonte pelo ID |

O fluxo típico numa consulta:

```
você: o que o contrato diz sobre rescisão?

step 1 › list_sources       → descobre que contrato.pdf está disponível
step 2 › search_knowledge   → busca "rescisão" nos chunks
step 3 › done               → responde com base nos trechos encontrados
```

O arquivo completo nunca entra no contexto — só os trechos relevantes.
Isso mantém o consumo de tokens mínimo, compatível com modelos locais de janela pequena.

---

## Ciclo de vida das fontes

```
/source arquivo.txt          → indexada na sessão atual
/source https://url.com      → baixada, cache salvo, indexada na sessão atual
/history deletar sessão      → fonte removida automaticamente (cascade)
                               cache de URLs da sessão removido junto

/source --global ref.txt     → indexada como _shared
/source --global https://... → cache salvo em knowledge/cache/_shared/
/source --remover <id>       → remoção manual necessária (+ cache se for URL)

/source --limpar-orfas       → limpeza de inconsistências
```

---

## Testes de validação

### 1. Escopo por agente
```
# no csv_manager
/source arquivo_a.txt
quais fontes você tem disponíveis?
# ✓ deve mostrar arquivo_a

/agente general
quais fontes você tem disponíveis?
# ✓ NÃO deve mostrar arquivo_a
```

### 2. Escopo por sessão
```
# no csv_manager
/source arquivo_b.txt
quais fontes você tem disponíveis?
# ✓ deve mostrar arquivo_b

/novo
quais fontes você tem disponíveis?
# ✓ NÃO deve mostrar arquivo_b
```

### 3. Fonte compartilhada
```
# no csv_manager
/source --global manual.txt
quais fontes você tem disponíveis?
# ✓ deve mostrar manual.txt

/novo
quais fontes você tem disponíveis?
# ✓ deve mostrar manual.txt

/agente general
quais fontes você tem disponíveis?
# ✓ NÃO deve mostrar manual.txt
```

### 4. Busca no conteúdo
```
/source documento.txt
o que o documento diz sobre [tema do arquivo]?
# ✓ deve chamar search_knowledge e responder com base nos chunks
```

### 5. Indexação de URL
```
/source https://en.wikipedia.org/wiki/Python_(programming_language)
/source --listar
# ✓ deve aparecer como en_wikipedia_org__Python_.url com N chunks

o que a fonte diz sobre tipagem em Python?
# ✓ deve buscar nos chunks e responder
```

### 6. Cache de URL
```
/source https://exemplo.com/artigo
# ✓ deve criar knowledge/cache/<session_id>/<hash>.txt
# ✓ primeira linha do arquivo deve ser a URL
```

### 7. Remoção de URL com cache
```
/source --listar
# anota o id da fonte .url

/source --remover <id>
# ✓ fonte removida do banco
# ✓ arquivo .txt de cache removido
# ✓ pasta da sessão removida se ficou vazia
```

### 8. Branch herda fontes
```
/source arquivo_c.txt
/history salvar
/history → seleciona a sessão → b (branch)

quais fontes você tem disponíveis?
# ✓ deve mostrar arquivo_c herdado da sessão pai
```

### 9. Cascade ao deletar sessão
```
/source https://exemplo.com/artigo
# anota o session_id criado

/history → seleciona a sessão → d (deletar)
# ✓ fonte removida do banco
# ✓ pasta knowledge/cache/<session_id>/ removida
```

### 10. Limpeza de órfãs
```
# deleta uma sessão que tinha fontes via /history → d
/source --limpar-orfas
# ✓ deve reportar fontes removidas (ou nenhuma, se cascade já limpou)
```

---

## Arquitetura interna

```
knowledge/
  db.py          schema SQLite + FTS5, cadeia de sessões ancestrais
  ingest.py      extração de texto de arquivos locais, chunking, indexação
  ingest_url.py  fetch de URLs, cache local, chunking, indexação
  retriever.py   busca FTS5 com escopo por agente/sessão/branch
  cache/         arquivos de texto extraídos de URLs
    <session_id>/
    _shared/

tools/
  list_sources.py
  search_knowledge.py
  read_source.py
  read_url.py    baixa página web e retorna texto limpo (usável pelo agente)
```

Banco de dados: `knowledge/knowledge.db` (separado do histórico de conversas)

---

## Roadmap

Ver `docs/KNOWLEDGE_ROADMAP.md` para otimizações planejadas:
expansão de query via LLM, resumo automático na ingestão,
suporte a DOCX, embeddings.