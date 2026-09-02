# Integrando Google Sheets e Docs ao Ciel via MCP

Este tutorial cobre a criação das credenciais no Google Cloud Console e a conexão dos servidores `google_sheets` e `google_docs` ao Ciel.

> **Nota:** Diferente do Notion, o Google não oferece um servidor MCP hospedado — os servidores rodam localmente em `mcp/google/`. A autenticação OAuth é gerenciada pelo `auth.py`, que abre o browser uma vez e salva o token automaticamente.

---

## Pré-requisitos

- Conta Google
- Ciel CLI funcionando
- Arquivos `mcp/google/auth.py`, `mcp/google/sheets_server.py` e `mcp/google/docs_server.py` na raiz do projeto

---

## Passo 1 — Criar o projeto no Google Cloud Console

1. Acesse [console.cloud.google.com](https://console.cloud.google.com)
2. No topo da página, clique no seletor de projetos → **Novo projeto**
3. Dê um nome (ex: `Ciel MCP`) e clique em **Criar**
4. Aguarde a criação e certifique-se de que o novo projeto está selecionado no topo

---

## Passo 2 — Ativar as APIs necessárias

Você vai ativar as APIs dos serviços que quer usar. Faça isso para cada um:

**Google Sheets API:**
1. No menu lateral, vá em **APIs e serviços → Biblioteca**
2. Busque por `Google Sheets API`
3. Clique no resultado e depois em **Ativar**

**Google Docs API** (se for usar o `google_docs`):
1. Volte à Biblioteca
2. Busque por `Google Docs API`
3. Clique em **Ativar**

**Google Drive API** (necessária para `sheets_list` e `docs_list`):
1. Volte à Biblioteca
2. Busque por `Google Drive API`
3. Clique em **Ativar**

---

## Passo 3 — Configurar a tela de consentimento OAuth

Este passo define como o Google identifica o app que está pedindo acesso.

1. No menu lateral, vá em **APIs e serviços → Tela de permissão OAuth**
2. Em **Tipo de usuário**, selecione **Externo** e clique em **Criar**
3. Preencha os campos obrigatórios:
   - **Nome do app:** `Ciel MCP`
   - **E-mail de suporte ao usuário:** seu e-mail
   - **Informações de contato do desenvolvedor:** seu e-mail
4. Clique em **Salvar e continuar**
5. Na tela de **Escopos**, clique em **Salvar e continuar** sem adicionar nada (os escopos são definidos pelo servidor)
6. Na tela de **Usuários de teste**, clique em **+ Add users** e adicione **obrigatoriamente** o e-mail da conta Google que você vai usar para autenticar
7. Clique em **Salvar e continuar** e depois em **Voltar ao painel**

> **Por que "Externo" com usuário de teste?** Projetos pessoais ficam em modo de teste indefinidamente — você não precisa verificar o app com o Google. Só você (e quem você adicionar) consegue autenticar.

> ⚠️ **Erro 403: access_denied?** Significa que a conta usada na tela de consentimento não está na lista de usuários de teste. Volte em **APIs e serviços → Tela de permissão OAuth → Audience → Usuários de teste**, adicione o e-mail correto e tente autenticar novamente.

---

## Passo 4 — Criar as credenciais OAuth

1. No menu lateral, vá em **APIs e serviços → Credenciais**
2. Clique em **+ Criar credenciais → ID do cliente OAuth**
3. Em **Tipo de aplicativo**, selecione **App para computador**
4. Dê um nome (ex: `Ciel Desktop`) e clique em **Criar**
5. Na janela que aparecer, clique em **Baixar JSON**
6. Salve o arquivo em um local seguro — por exemplo:
   ```
   C:\Users\voce\.ciel\client_secret.json     # Windows
   ~/.ciel/client_secret.json                  # Linux / Mac
   ```

> **Dica:** O arquivo contém `client_id` e `client_secret`. Não compartilhe nem versionei com git — adicione ao `.gitignore` se necessário.

<details>
<summary>O que é esse JSON?</summary>

O arquivo tem uma estrutura parecida com:

```json
{
  "installed": {
    "client_id": "123456-abc.apps.googleusercontent.com",
    "client_secret": "GOCSPX-...",
    "redirect_uris": ["http://localhost"]
  }
}
```

O `auth.py` lê `client_id` e `client_secret` desse arquivo para montar o fluxo OAuth.

</details>

---

## Passo 5 — Conectar o Google Sheets no Ciel

Peça ao Ciel para adicionar o servidor:

```
Ciel, adiciona o google_sheets:

mcp_add_server(
    name="google_sheets",
    type="stdio",
    command="python",
    args="mcp/google/sheets_server.py",
    env="GOOGLE_CLIENT_SECRET=C:\Users\voce\.ciel\client_secret.json"
)
```

No Linux/Mac:

```
mcp_add_server(
    name="google_sheets",
    type="stdio",
    command="python",
    args="mcp/google/sheets_server.py",
    env="GOOGLE_CLIENT_SECRET=/home/voce/.ciel/client_secret.json"
)
```

---

## Passo 6 — Autenticação OAuth (primeira vez)

Assim que o servidor iniciar, o browser vai abrir automaticamente com a tela de consentimento do Google.

1. Selecione a conta Google que adicionou como usuário de teste no Passo 3
2. Clique em **Continuar** (pode aparecer um aviso de "app não verificado" — é esperado)
3. Autorize os acessos solicitados
4. A aba vai mostrar **"Autenticado! Pode fechar esta aba."**

O token é salvo em `~/.ciel/google_token.json`. As próximas conexões são automáticas, mesmo que você feche e reabra o Ciel.

> Ative a biblioteca Google Drive no console Google Cloud, como você já está autenticado não precisa gerar uma chave de api. Busque Google Drive nas bibliotecas e clique em ativiar.

<details>
<summary>O browser não abriu?</summary>

O `auth.py` tenta abrir via `webbrowser.open()`. Se não funcionar, o link é impresso no terminal — copie e cole manualmente no browser.

</details>

<details>
<summary>Precisa resetar a autenticação?</summary>

Delete o arquivo de token salvo:

```bash
# Windows
del "%USERPROFILE%\.ciel\google_token.json"

# Linux / Mac
rm ~/.ciel/google_token.json
```

Na próxima conexão, o fluxo de autenticação vai abrir novamente.

Se quiser revogar o acesso pelo lado do Google também:

1. Acesse [myaccount.google.com/permissions](https://myaccount.google.com/permissions)
2. Localize **Ciel MCP** na lista
3. Clique em **Remover acesso**

</details>

---

## Passo 7 — Conectar o Google Docs no Ciel (opcional)

O processo é idêntico ao Sheets, mas usa um servidor separado:

```
mcp_add_server(
    name="google_docs",
    type="stdio",
    command="python",
    args="mcp/google/docs_server.py",
    env="GOOGLE_CLIENT_SECRET=C:\Users\voce\.ciel\client_secret.json"
)
```

O Docs pede uma autenticação separada na primeira vez (token salvo em `~/.ciel/google_docs_token.json`).

> **Dica:** Para compartilhar o mesmo token entre Sheets e Docs, adicione `GOOGLE_TOKEN_STORE=/caminho/token.json` no `env` dos dois servidores com o mesmo caminho. Na primeira conexão o token vai cobrir os escopos dos dois e não vai pedir autenticação de novo.

---

## Passo 8 — Verificar a conexão

```
/mcp -v
```

Resultado esperado:

```
● google_sheets   conectado (6 tools)
    • mcp_google_sheets__sheets_list
    • mcp_google_sheets__sheets_info
    • mcp_google_sheets__sheets_read
    • mcp_google_sheets__sheets_write
    • mcp_google_sheets__sheets_append
    • mcp_google_sheets__sheets_clear

● google_docs   conectado (5 tools)
    • mcp_google_docs__docs_list
    • mcp_google_docs__docs_read
    • mcp_google_docs__docs_create
    • mcp_google_docs__docs_append
    • mcp_google_docs__docs_replace
```

---

## Testando

```
# Listar planilhas
Ciel, lista minhas planilhas do Google Sheets

# Ler uma planilha
Ciel, lê a planilha [id] aba "Plan1" intervalo A1:E20

# Escrever numa célula
Ciel, escreve "concluído" na célula B3 da planilha [id]

# Adicionar linhas
Ciel, adiciona uma linha com ["2026-09-01", "tarefa X", "feito"] na planilha [id]

# Criar um doc
Ciel, cria um documento chamado "Relatório setembro" com o conteúdo: ...

# Ler um doc
Ciel, lê o documento [id]

# Preencher template
Ciel, no documento [id] substitui "{{data}}" por "01/09/2026"
```

---

## Persistência

A configuração é salva em `mcp_servers.json` na raiz do projeto. Os servidores reconectam automaticamente na próxima sessão do Ciel — e como os tokens OAuth persistem em `~/.ciel/`, nenhuma ação adicional é necessária.

---

## Referências

- [Google Cloud Console](https://console.cloud.google.com)
- [Google Sheets API — Referência](https://developers.google.com/sheets/api/reference/rest)
- [Google Docs API — Referência](https://developers.google.com/docs/api/reference/rest)
- [Gerenciar permissões de apps Google](https://myaccount.google.com/permissions)
