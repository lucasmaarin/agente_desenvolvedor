# Arauto Code — Guia de Edição

Guia completo para editar, expandir e manter o projeto sem depender de IA.

---

## Índice

1. [Visão geral](#visão-geral)
2. [Estrutura de arquivos](#estrutura-de-arquivos)
3. [Rodar localmente](#rodar-localmente)
4. [Variáveis de ambiente (.env)](#variáveis-de-ambiente-env)
5. [Como editar os prompts da IA](#como-editar-os-prompts-da-ia)
6. [Como adicionar uma nova linguagem/stack](#como-adicionar-uma-nova-linguagemstack)
7. [Como editar o visual (cores e temas)](#como-editar-o-visual-cores-e-temas)
8. [Como adicionar uma rota no backend](#como-adicionar-uma-rota-no-backend)
9. [Como adicionar botão ou elemento no frontend](#como-adicionar-botão-ou-elemento-no-frontend)
10. [Deploy no Render](#deploy-no-render)
11. [Firebase — como funciona aqui](#firebase--como-funciona-aqui)
12. [Problemas comuns e soluções](#problemas-comuns-e-soluções)
13. [Referências rápidas](#referências-rápidas)

---

## Visão geral

O Arauto Code é um agente de programação que gera projetos completos a partir de uma descrição em texto. É uma aplicação Flask (Python) que usa a API da Groq para gerar código e o Firebase Firestore para salvar os projetos.

**Fluxo básico:**
```
Usuário descreve → Flask recebe → Monta prompt → Chama Groq → Recebe JSON com arquivos → Salva no Firestore → Exibe no frontend
```

**Stack:**
- Backend: Python + Flask
- IA: Groq API (Llama 3.3) via SDK OpenAI-compatível
- Banco de dados: Firebase Firestore
- Frontend: HTML + CSS + JavaScript puro (sem framework)

---

## Estrutura de arquivos

```
arauto-code/
├── main.py                   ← Todo o backend (rotas, lógica da IA, Firebase)
├── requirements.txt          ← Dependências Python
├── render.yaml               ← Configuração de deploy no Render
├── .env                      ← Variáveis de ambiente locais (nunca suba pro Git)
├── settings.json             ← Configurações do usuário (criado automaticamente)
├── automacoes-royal-x.json   ← Credenciais Firebase (nunca suba pro Git)
│
├── templates/
│   ├── index.html            ← Frontend completo (HTML + JavaScript)
│   └── login.html            ← Tela de login
│
└── static/
    ├── css/style.css         ← Todos os estilos
    ├── img/logo.png          ← Logo original
    ├── img/icon-192.png      ← Ícone PWA 192×192
    ├── img/icon-512.png      ← Ícone PWA 512×512
    ├── manifest.json         ← Configuração PWA
    └── sw.js                 ← Service Worker
```

---

## Rodar localmente

**Pré-requisito:** Python 3.10 ou superior.

```bash
# 1. Criar e ativar ambiente virtual
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # Mac/Linux

# 2. Instalar dependências
pip install -r requirements.txt

# 3. Rodar
python main.py
```

Acesse `http://localhost:8000` e entre com a senha definida em `ADMIN_PASSWORD` no `.env`.

---

## Variáveis de ambiente (.env)

| Variável | O que faz |
|---|---|
| `ADMIN_PASSWORD` | Senha de acesso ao app |
| `FLASK_SECRET_KEY` | Chave de criptografia das sessões — use uma string longa e aleatória |
| `AI_PROVIDER` | `local` para Groq/Ollama, `openai` para OpenAI |
| `LOCAL_AI_URL` | URL base da API de IA (`https://api.groq.com/openai/v1` para Groq) |
| `LOCAL_AI_KEY` | Chave da API de IA (começa com `gsk_` no Groq) |
| `LOCAL_AI_MODEL` | Modelo de texto (`llama-3.3-70b-versatile`) |
| `VISION_MODEL` | Modelo para análise de imagens (`llama-3.2-11b-vision-preview`) |
| `PROJECTS_OUTPUT_DIR` | Pasta onde projetos são salvos em disco. Vazio = não salva |
| `GITHUB_TOKEN` | Token do GitHub para a feature de editar repositórios |
| `FIREBASE_CREDENTIALS` | Caminho do JSON do Firebase (uso local) |
| `FIREBASE_CREDENTIALS_JSON` | Conteúdo completo do JSON do Firebase em string (uso em produção) |

**Gerar uma chave secreta segura:**
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

**Trocar o modelo de IA:** basta mudar `LOCAL_AI_MODEL`. Modelos disponíveis em [console.groq.com](https://console.groq.com).

---

## Como editar os prompts da IA

Tudo fica em `main.py`. Existem três áreas principais:

### 1. Comportamento geral do agente (criação de projeto)

**Função:** `get_create_prompt()` — busque por `def get_create_prompt`

```python
return f"""You are an elite software engineer...
# Edite o texto aqui para mudar como o agente pensa e age
{arch_guide}              # guia de arquitetura da linguagem escolhida
{extra}                   # instruções do painel Config do usuário
{JSON_FORMAT_INSTRUCTION} # formato obrigatório da resposta (não mexa)
"""
```

### 2. Comportamento ao modificar projetos (chat)

**Função:** `get_chat_prompt()` — busque por `def get_chat_prompt`

Usado quando o usuário já tem um projeto e pede alterações.

### 3. Guias de arquitetura por linguagem

**Variável:** `ARCHITECTURE_GUIDES` — busque por `ARCHITECTURE_GUIDES = {`

Cada chave é uma linguagem e o valor é o conjunto de regras que a IA segue para aquela stack:

```python
ARCHITECTURE_GUIDES = {
    "react":    "Stack: React... use .jsx para componentes...",
    "react-ts": "Stack: React + TypeScript... use .tsx para componentes...",
    "vanilla":  "Stack: HTML, CSS e JavaScript puro...",
    "python":   "Stack: Python..."
}
```

Para mudar como o agente estrutura um projeto React, edite o valor de `"react"`.

---

## Como adicionar uma nova linguagem/stack

**Exemplo: adicionar Vue.js**

**Passo 1** — Adicionar o guia em `ARCHITECTURE_GUIDES` no `main.py`:
```python
"vue": """Stack: Vue.js 3 with Composition API.

Architecture guidelines:
- Use Vite + Vue 3.
- File extensions: .vue for components, .ts for utilities.
- Organize in: components/, views/, composables/, stores/, services/.
- Use Vue Router for navigation.
- Use Pinia for state management.""",
```

**Passo 2** — Adicionar o label em `lang_labels` dentro de `create_project()`:
```python
lang_labels = {
    ...
    "vue": "Vue.js 3",
}
```

**Passo 3** — Adicionar a opção no `<select>` do `index.html` (busque por `languageSelect`):
```html
<option value="vue">Vue.js</option>
```

**Passo 4** — Adicionar o label no dicionário `LANG_LABELS` do JavaScript em `index.html` (busque por `LANG_LABELS`):
```javascript
'vue': 'Vue.js',
```

---

## Como editar o visual (cores e temas)

### Cores globais

**Arquivo:** `static/css/style.css` — início do arquivo, variáveis CSS dentro de `:root { }`:

```css
:root {
    --accent-green: #5dd62c;    /* verde principal (botões, destaques) */
    --bg-primary:   #0f0f0f;    /* fundo mais escuro */
    --bg-secondary: #1a1a1a;    /* fundo dos painéis */
    --text-primary: #f8f8f8;    /* texto principal */
}
```

Altere os valores hexadecimais para mudar as cores em todo o app.

### Temas

Cada tema sobrescreve as variáveis CSS. Estão no final do `style.css`:

```css
[data-theme="dracula"] {
    --bg-primary: #282a36;
    --accent-green: #bd93f9;
    ...
}
```

**Para criar um novo tema:**

1. Adicione o bloco no `style.css`:
```css
[data-theme="solarized"] {
    --bg-primary: #002b36;
    --bg-secondary: #073642;
    --accent-green: #859900;
    --text-primary: #fdf6e3;
}
```

2. Adicione o botão no painel de configurações do `index.html` (busque por `theme-grid`):
```html
<div class="theme-option" data-theme="solarized" onclick="applyTheme('solarized')">
    <div class="theme-preview" style="background:#002b36; border:2px solid #859900;"></div>
    <span>Solarized</span>
</div>
```

### Tamanho da logo (topbar)
No `style.css`, busque por `.copilot-icon` e mude `width` e `height`.

---

## Como adicionar uma rota no backend

**Arquivo:** `main.py`

Modelo padrão:

```python
@app.route('/minha-rota', methods=['POST'])
def minha_rota():
    try:
        data = request.get_json()
        valor = data.get('campo', '')

        # lógica aqui

        return jsonify({"resultado": valor})
    except Exception as e:
        app.logger.error(f"minha_rota error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500
```

**Regras:**
- Sempre use `try/except` e retorne `jsonify({"error": ...}), 500` no erro
- Sempre retorne `jsonify(...)` — nunca texto puro em rotas de API
- Login é protegido automaticamente pelo `before_request` — não precisa de decorator extra

---

## Como adicionar botão ou elemento no frontend

### Adicionar botão no topbar
**Arquivo:** `templates/index.html` — busque por `<div class="topbar-right">`

```html
<button class="topbar-btn" onclick="minhaFuncao()">Meu Botão</button>
```

### Chamar uma rota do backend

```javascript
async function minhaFuncao() {
    try {
        const res = await fetch('/minha-rota', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ campo: 'valor' })
        });
        let data;
        try { data = await res.json(); } catch { data = { error: `HTTP ${res.status}` }; }

        if (!res.ok || data.error) {
            showToast('Erro: ' + data.error, 'error');
            return;
        }

        // usar data.resultado aqui
        showToast('Sucesso!');
    } catch (err) {
        showToast('Erro: ' + err.message, 'error');
    }
}
```

### Funções utilitárias disponíveis no frontend

| Função | O que faz |
|---|---|
| `showToast(msg, tipo)` | Notificação flutuante. tipo: `'success'` (padrão) ou `'error'` |
| `setStatus(texto, loading)` | Atualiza a barra de status inferior |
| `addChatMessage(role, content, meta)` | Adiciona mensagem no chat |
| `escapeHtml(str)` | Escapa HTML para exibição segura |
| `isMobile()` | Retorna `true` se dispositivo for mobile |
| `renderFileTree(files)` | Renderiza a árvore de arquivos no explorador |
| `displayFile(path)` | Abre um arquivo no visualizador de código |

---

## Deploy no Render

### Primeira vez
1. Suba o código para o GitHub
2. Crie conta em [render.com](https://render.com) → New → Web Service → conecte o repositório
3. O Render lê o `render.yaml` automaticamente

### Variáveis obrigatórias no painel do Render
(Em **Environment** → **Add Environment Variable**)

| Variável | Como obter |
|---|---|
| `LOCAL_AI_KEY` | [console.groq.com](https://console.groq.com) → API Keys |
| `FLASK_SECRET_KEY` | `python -c "import secrets; print(secrets.token_hex(32))"` |
| `FIREBASE_CREDENTIALS_JSON` | Abra `automacoes-royal-x.json`, copie o conteúdo inteiro e cole |
| `ADMIN_PASSWORD` | Escolha uma senha forte |
| `GITHUB_TOKEN` | GitHub → Settings → Developer Settings → Personal Access Tokens |

### Atualizar o deploy
Qualquer `git push` na branch `main` aciona um novo deploy automaticamente.

---

## Firebase — como funciona aqui

O Firestore salva todos os projetos gerados e o histórico de mensagens.

**Estrutura no banco:**
```
agente_programacao/
  _data/projects/
    <project_id>/
      project_name, language, files, folder_structure, ...
      messages/
        <msg_id>: { role, content, timestamp }
  _usage/daily/
    <YYYY-MM-DD>: { tokens, cost, requests }
```

Você não precisa criar nada no Firebase — o app cria as coleções automaticamente na primeira execução.

**Para ver os dados:** [console.firebase.google.com](https://console.firebase.google.com) → Firestore Database.

---

## Problemas comuns e soluções

### "Connection error" ao chamar a IA
Teste a conexão direto no terminal:
```bash
python -c "
import openai, os
from dotenv import load_dotenv
load_dotenv()
c = openai.OpenAI(base_url=os.getenv('LOCAL_AI_URL'), api_key=os.getenv('LOCAL_AI_KEY'))
r = c.chat.completions.create(model=os.getenv('LOCAL_AI_MODEL'), messages=[{'role':'user','content':'ok'}], max_tokens=3)
print('OK:', r.choices[0].message.content)
"
```

### Erro JavaScript no frontend
Faça **Ctrl+Shift+R** (hard refresh) para limpar o cache do navegador.

### A IA retornou JSON inválido
O app tenta até 3 vezes automaticamente. Se persistir: simplifique a descrição, ou troque o modelo em `LOCAL_AI_MODEL`.

### Sessão expira ao reiniciar o servidor
Defina um `FLASK_SECRET_KEY` fixo no `.env`. Se estiver usando `os.urandom()`, a chave muda a cada restart.

### Ver logs em produção
Render Dashboard → seu serviço → aba **Logs**.

### Projetos não aparecem na lista
Confirme que as credenciais do Firebase estão corretas. Em produção, verifique se `FIREBASE_CREDENTIALS_JSON` contém o JSON completo (não o caminho do arquivo).

---

## Referências rápidas

| O que quero mudar | Onde fica |
|---|---|
| Comportamento geral do agente | `main.py` → `get_create_prompt()` |
| Comportamento ao modificar projetos | `main.py` → `get_chat_prompt()` |
| Regras de arquitetura por linguagem | `main.py` → `ARCHITECTURE_GUIDES` |
| Cores e temas | `static/css/style.css` |
| Layout e estrutura HTML | `templates/index.html` |
| Tela de login | `templates/login.html` |
| Logo e ícones | `static/img/` |
| Variáveis de ambiente | `.env` (local) ou painel do Render (produção) |
| Configuração PWA | `static/manifest.json` |
| Nome do app | `templates/index.html` → `<title>` e topbar; `static/manifest.json` → `"name"` |
