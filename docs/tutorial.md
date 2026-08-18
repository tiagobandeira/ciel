# Tutorial — Do zero ao primeiro chat

Este guia leva você do zero até conversar com o agente pela primeira vez.  
Cada etapa tem uma seção recolhível com instruções detalhadas — se você já tem algo instalado, é só pular.

---

## O que você vai precisar

- **Python 3.10+**
- **Ollama** (para rodar o modelo de linguagem)
- **Git** *(ou baixar o projeto manualmente)*
- ~4 GB de espaço livre para o modelo recomendado

Tempo estimado: **10 a 20 minutos** dependendo da sua conexão.

---

## Passo 1 — Instalar o Python

<details>
<summary>Já tenho o Python instalado → pular</summary>

Verifique rodando no terminal:

```bash
python --version
# ou
python3 --version
```

Se aparecer `Python 3.10` ou superior, pode seguir para o Passo 2.

</details>

<details>
<summary>Como instalar o Python</summary>

Acesse **https://python.org/downloads** e baixe a versão mais recente para o seu sistema.

**Windows**
- Execute o instalador `.exe`
- ⚠️ Marque a opção **"Add Python to PATH"** antes de clicar em Install
- Abra o Prompt de Comando e confirme: `python --version`

**macOS**
- Execute o instalador `.pkg` baixado
- Ou, se tiver Homebrew: `brew install python`
- Confirme no terminal: `python3 --version`

**Linux (Ubuntu/Debian)**
```bash
sudo apt update
sudo apt install python3 python3-pip python3-venv
```

</details>

---

## Passo 2 — Instalar o Ollama

O Ollama é o serviço que roda os modelos de linguagem localmente na sua máquina.

<details>
<summary>Já tenho o Ollama instalado → pular</summary>

Confirme rodando:
```bash
ollama --version
```

Se retornar uma versão, pode seguir para o Passo 3.

</details>

<details>
<summary>Como instalar o Ollama</summary>

Acesse **https://ollama.com/download** e baixe para o seu sistema.

**Windows / macOS**
- Execute o instalador e siga as instruções
- O Ollama inicia automaticamente em background após a instalação

**Linux**
```bash
curl -fsSL https://ollama.com/install.sh | sh
```

Após instalar, confirme:
```bash
ollama --version
```

> O Ollama precisa estar **rodando em background** para o Ciel funcionar.  
> No Windows e macOS ele inicia automaticamente. No Linux, rode `ollama serve` em um terminal separado se necessário.

</details>

---

## Passo 3 — Baixar um modelo

O Ciel precisa de um modelo de linguagem para funcionar. Você tem duas opções:

<details>
<summary>Opção A — Modelo local (roda 100% offline)</summary>

Recomendado para testes: **gemma4:e2b-it-qat** (~3.5 GB, bom desempenho em máquinas comuns)

```bash
ollama pull gemma4:e2b-it-qat
```

Aguarde o download completar. Depois confirme que está disponível:

```bash
ollama list
```

Para usar esse modelo no Ciel:
```bash
python cli.py --model gemma4:e2b-it-qat
```

> Modelos locais não precisam de internet após o download e não têm limite de uso.  
> Requerem pelo menos 8 GB de RAM para rodar com conforto.

</details>

<details>
<summary>Opção B — gemma4:cloud (gratuito, via Ollama, requer cadastro)</summary>

O **gemma4:cloud** é o modelo Gemma 4 de 31B da Google, disponível gratuitamente via Ollama com cadastro. É o modelo padrão do Ciel e oferece desempenho superior sem precisar de hardware potente.

**Como ativar:**

1. Crie uma conta em **https://ollama.com** com seu e-mail
2. No terminal, tente rodar o modelo:
```bash
ollama run gemma4:cloud
```
3. O Ollama vai abrir uma página no navegador pedindo autorização — confirme
4. Pronto, o modelo estará disponível

O limite de requisições gratuitas se renova periodicamente e é generoso para uso agêntico — tarefas com ferramentas consomem bem menos do que parece.

Para usar no Ciel (já é o padrão):
```bash
python cli.py
```

</details>

---

## Passo 4 — Baixar o Ciel

<details>
<summary>Opção A — Via Git (recomendado)</summary>

Se você tem o Git instalado:

```bash
git clone https://github.com/seu-usuario/ciel.git
cd ciel
```

> Não tem Git? Baixe em **https://git-scm.com/downloads**

</details>

<details>
<summary>Opção B — Baixar o ZIP manualmente</summary>

1. Acesse o repositório no GitHub
2. Clique em **Code → Download ZIP**
3. Extraia o arquivo em uma pasta de sua escolha
4. Abra o terminal nessa pasta

</details>

---

## Passo 5 — Criar o ambiente virtual e instalar dependências

Dentro da pasta do projeto, rode:

```bash
# Criar o ambiente virtual
python -m venv venv

# Ativar — Windows (Prompt de Comando)
venv\Scripts\activate.bat

# Ativar — Windows (PowerShell)
venv\Scripts\Activate.ps1

# Ativar — macOS / Linux
source venv/bin/activate
```

Com o venv ativo, instale as dependências:

```bash
pip install requests rich pymupdf
```

> O ambiente virtual isola as dependências do Ciel do seu Python global.  
> É especialmente importante aqui porque o agente pode instalar pacotes adicionais ao criar novas ferramentas.

---

## Passo 6 — Primeiro chat

Com o Ollama rodando e o venv ativo, inicie o Ciel:

```bash
python cli.py
```

Você verá o banner do Ciel e o prompt de entrada. Digite qualquer mensagem e pressione Enter.

**Variações úteis:**

```bash
# Usar um modelo local específico
python cli.py --model gemma4:e2b-it-qat

# Modo seguro (sem execução de scripts)
python cli.py --safe

# Usar uma persona específica
python cli.py --agent dev_helper

# Ver todos os agentes disponíveis
python cli.py --list-agents
```

---

## Deu algum problema?

<details>
<summary>Erro: "ollama: command not found"</summary>

O Ollama não está instalado ou não está no PATH.  
Volte ao **Passo 2** e confirme a instalação.

</details>

<details>
<summary>Erro: "connection refused" ao iniciar o Ciel</summary>

O serviço do Ollama não está rodando.

- **Windows/macOS:** procure o ícone do Ollama na bandeja do sistema e inicie
- **Linux:** abra um terminal separado e rode `ollama serve`

</details>

<details>
<summary>Erro ao instalar dependências com pip</summary>

Confirme que o venv está ativo — você deve ver `(venv)` no início do terminal.  
Se não estiver, volte ao **Passo 5** e ative novamente.

</details>

<details>
<summary>Erro ao ativar o venv no PowerShell (Windows)</summary>

Se aparecer um erro de permissão ao rodar `Activate.ps1`, é uma restrição de política de execução do Windows. Duas soluções:

**Opção 1 — Usar o Prompt de Comando (cmd) em vez do PowerShell:**
```bat
venv\Scripts\activate.bat
```

**Opção 2 — Liberar a política no PowerShell:**
```powershell
Set-ExecutionPolicy RemoteSigned -Scope CurrentUser
```
Execute esse comando uma vez e tente ativar novamente. O `-Scope CurrentUser` garante que a mudança afeta só seu usuário, não o sistema todo.

</details>

<details>
<summary>O modelo demora muito para responder</summary>

Modelos locais dependem do hardware da máquina. O `gemma4:e2b-it-qat` é otimizado para rodar em máquinas comuns, mas em hardware mais limitado pode ser lento.  
Nesse caso, considere usar o **gemma4:cloud** (Opção B do Passo 3) que roda nos servidores da Google gratuitamente.

</details>

---

Depois do primeiro chat, explore os comandos digitando `/ajuda` dentro do Ciel.  
Para funcionalidades avançadas como tasks, base de conhecimento e criação de ferramentas, consulte o [README](../README.md).
