# AI Code Agent

Agente de programação com IA que gera projetos completos a partir de uma descrição em texto. Interface estilo editor de código com chat, explorador de arquivos, visualizador com syntax highlight e integração direta com GitHub.

---

## O que o projeto faz

### Geração de projetos
Descreva a aplicação que quer criar no chat e a IA gera o projeto inteiro — estrutura de pastas, todos os arquivos e o código completo, pronto para uso.

Stacks suportadas:
- **React (JavaScript)** — Create React App / Vite, componentes funcionais, hooks, CSS Modules
- **React + TypeScript** — Vite + TSX, interfaces tipadas, Tailwind ou CSS Modules
- **Python** — detecta automaticamente o tipo de projeto (FastAPI, Flask, CLI, bot) e gera a estrutura correta

### Chat iterativo
Após criar o projeto, continue conversando para fazer alterações. A IA entende o contexto de tudo que já foi gerado e modifica, adiciona ou remove arquivos conforme necessário. O histórico da conversa é salvo.

### Explorador de arquivos
Painel lateral com a árvore de pastas do projeto gerado. Pastas podem ser expandidas e colapsadas. Arquivos modificados pela IA são destacados visualmente.

### Visualizador de código
- Syntax highlight para Python, JS, TS, TSX, JSX, JSON, CSS, HTML, YAML, Markdown, Bash
- Abas para navegar entre múltiplos arquivos abertos
- Numeração de linhas
- Breadcrumb com o caminho do arquivo atual
- Botão de copiar o conteúdo do arquivo

### Histórico de projetos
Todos os projetos são salvos no Firebase Firestore. No painel "Projetos" você vê os 50 mais recentes com nome, descrição, stack, número de arquivos e custo. Clique para reabrir qualquer projeto e continuar de onde parou. É possível deletar projetos.

### Integração com GitHub
Painel lateral que conecta na sua conta do GitHub via token. Funcionalidades:
- Lista todos os seus repositórios (públicos e privados)
- Busca repositórios por nome
- Seleciona arquivos específicos ou usa o projeto inteiro
- Envia uma instrução em texto para a IA
- A IA analisa os arquivos, faz as alterações e realiza o commit diretamente no repositório com uma mensagem seguindo Conventional Commits
- Exibe o link direto para o commit no GitHub

### Controle de uso e custo
A barra superior exibe em tempo real os tokens consumidos e o custo em reais do dia atual. Os dados são salvos por dia no Firestore.

---

## Atalhos de teclado

| Atalho | Ação |
|---|---|
| `Enter` | Enviar mensagem no chat |
| `Shift + Enter` | Quebra de linha no chat |
| `Ctrl + N` | Novo projeto |
| `Ctrl + P` | Focar no campo de chat |
| `Esc` | Fechar painel de projetos |

---

## Stack técnica

| Camada | Tecnologia |
|---|---|
| Backend | Flask (Python) |
| Frontend | HTML + CSS + JavaScript puro |
| Banco de dados | Firebase Firestore |
| Syntax highlight | Prism.js |
| IA | OpenAI API / Groq / Ollama (configurável) |

---

## Configuração de IA

O provedor de IA é definido no `.env` pela variável `AI_PROVIDER`:

### OpenAI (padrão)
```
AI_PROVIDER=openai
OPENAI_API_KEY=sk-...
```

### Groq (grátis, recomendado)
```
AI_PROVIDER=local
LOCAL_AI_URL=https://api.groq.com/openai/v1
LOCAL_AI_KEY=gsk_...
LOCAL_AI_MODEL=llama-3.3-70b-versatile
```

### Ollama (100% local, sem internet)
```
AI_PROVIDER=local
LOCAL_AI_URL=http://localhost:11434/v1
LOCAL_AI_KEY=ollama
LOCAL_AI_MODEL=qwen2.5-coder:7b
```

Veja [OLLAMA_SETUP.md](OLLAMA_SETUP.md) para instruções detalhadas de cada opção.

---

## Variáveis de ambiente

| Variável | Descrição |
|---|---|
| `OPENAI_API_KEY` | Chave da OpenAI (quando `AI_PROVIDER=openai`) |
| `AI_PROVIDER` | `openai` ou `local` |
| `LOCAL_AI_URL` | URL base da API local (Groq ou Ollama) |
| `LOCAL_AI_KEY` | Chave de autenticação da API local |
| `LOCAL_AI_MODEL` | Modelo a usar |
| `OPENAI_MODEL` | Modelo OpenAI (padrão: `o4-mini`) |
| `FIREBASE_CREDENTIALS` | Caminho para o JSON de credenciais do Firebase |
| `FLASK_SECRET_KEY` | Chave secreta do Flask |
| `GITHUB_TOKEN` | Token de acesso ao GitHub (para a integração) |

---

## Como rodar

```bash
# Instalar dependências
pip install -r requirements.txt

# Configurar o .env com as variáveis necessárias

# Iniciar o servidor
python main.py
```

Acesse `http://localhost:8000` no navegador.
