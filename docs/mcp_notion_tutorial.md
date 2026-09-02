# Integrando o Notion ao Ciel via MCP

Este tutorial documenta como conectar o Notion ao agente Ciel usando o protocolo MCP (Model Context Protocol). O processo usa `mcp-remote` como ponte entre o cliente stdio do Ciel e o servidor HTTP do Notion.

> **Nota:** Este tutorial serve como base para outras integrações semelhantes que usam `mcp-remote` ou pacotes equivalentes via `npx`.

---

## Pré-requisitos

- **Node.js** instalado na máquina
- Conta no Notion
- Ciel CLI funcionando

<details>
<summary>Como instalar o Node.js?</summary>

Baixe o instalador em [nodejs.org](https://nodejs.org) e siga o processo padrão.

Após instalar, verifique no terminal:

```bash
node --version
npm --version
```

O `npx` vem junto com o npm — não precisa instalar separado.

</details>

---

## Passo 1 — Criar a conexão no Notion

1. Acesse o Notion e vá em **Configurações → Ferramentas do desenvolvedor → Conexões**
2. Clique em **+ Nova conexão**
3. Preencha o nome (ex: `Ciel Connection`)
4. Em **Método de autenticação**, selecione **Token de acesso**
5. Clique em **Criar conexão**

Você será redirecionado para a página da conexão. Ela tem as seguintes abas:

- **Configuração** — exibe o token de acesso (guarde-o em local seguro ou numa variável de ambiente)
- **Acesso a conteúdo** — define quais páginas ou bases de dados o agente poderá acessar. Adicione aqui os espaços que o Ciel vai usar. Você pode criar um espaço dedicado exclusivamente ao agente.

> **Dica:** O token pode ser resetado a qualquer momento pela aba Configuração caso seja comprometido.

---

## Passo 2 — Encontrar o caminho do npx

O Ciel precisa do caminho absoluto do executável. No terminal:

```bash
# Windows
where npx
where node

# Linux / Mac
which npx
which node
```

Anote o caminho retornado. Exemplo no Windows:

```
C:\nvm4w\nodejs\npx.CMD
```

---

## Passo 3 — Conectar o servidor MCP no Ciel

Peça ao Ciel para adicionar o servidor. Você pode passar no formato da doc oficial (JSON do Claude Code / Codex):

```
Ciel, adiciona o notion mcp:
{
  "mcpServers": {
    "notion": {
      "command": "C:\nvm4w\nodejs\npx.CMD",
      "args": ["-y", "mcp-remote", "https://mcp.notion.com/mcp"]
    }
  }
}
```

O Ciel interpreta esse formato e internamente chama:

```python
mcp_add_server(
    name="notion",
    type="stdio",
    command="C:\\nvm4w\\nodejs\\npx.CMD",
    args="-y mcp-remote https://mcp.notion.com/mcp"
)
```

Você também pode passar diretamente nesse segundo formato se preferir.

---

## Passo 4 — Autenticação OAuth

Na primeira conexão, o `mcp-remote` abre uma URL de autenticação no terminal. Abra essa URL no navegador e confirme o acesso ao Notion.

Após confirmar, o token é salvo localmente e as próximas conexões são automáticas — mesmo que você deslogue do Notion no navegador.

<details>
<summary>Problema na autenticação?</summary>

Se a página não abrir ou a autenticação falhar, tente rodar o comando diretamente no terminal antes de pedir ao Ciel:

```bash
npx -y mcp-remote https://mcp.notion.com/mcp
```

Aguarde a URL aparecer, confirme no browser e depois adicione o servidor em uma nova sessão do Ciel. Foi exatamente assim que funcionou durante o desenvolvimento deste tutorial.

</details>

<details>
<summary>Precisa resetar a autenticação?</summary>

1. Abra o Notion e vá em **Configurações → Minhas conexões**
2. Localize a conexão criada (ex: `Ciel Connection`)
3. Clique nos três pontos `···` ao lado dela
4. Selecione **Revogar acesso**

Na próxima vez que o Ciel tentar usar o Notion, o `mcp-remote` vai disparar o fluxo de autenticação automaticamente — repita o Passo 4.

</details>

---

## Passo 5 — Verificar a conexão

No Ciel, execute:

```
/mcp -v
```

Se tudo estiver certo, você verá algo como:

```
● notion   conectado (41 tools)
    • mcp_notion__notion_search
    • mcp_notion__notion_fetch
    • mcp_notion__notion_create_pages
    • mcp_notion__notion_update_page
    • mcp_notion__notion_list_recent_pages
    ... (41 tools no total)
```

---

## Testando

Alguns exemplos simples para verificar que está funcionando:

```
# Listar páginas recentes
Ciel, lista minhas páginas recentes no Notion

# Buscar algo
Ciel, busca no Notion por "tarefas"

# Criar uma página
Ciel, cria uma página no Notion sobre o projeto X
```

O Notion funciona como memória externa do agente — você pode criar páginas, consultar bases de dados, registrar resultados de tarefas, etc.

---

## Persistência

A configuração é salva automaticamente em `mcp_servers.json` na raiz do projeto. Na próxima vez que iniciar o Ciel, o servidor reconecta sozinho sem nenhuma ação do usuário.

---

## Referências

- [Documentação oficial do Notion MCP](https://developers.notion.com/docs/mcp)
- [mcp-remote no npm](https://www.npmjs.com/package/mcp-remote)
