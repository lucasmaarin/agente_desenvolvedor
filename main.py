from flask import Flask, render_template, request, jsonify, send_file, session, redirect, url_for
import os
from functools import wraps
import io
import zipfile
import pathlib
import json
import re
import base64
import openai
import requests as http
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime, date
from dotenv import load_dotenv

load_dotenv()

# ===============================
# Configuração Flask
# ===============================
app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'dev-secret-change-in-production')

ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', '')

# Rotas que não precisam de login
_PUBLIC_ENDPOINTS = {'login_page', 'login_post', 'logout', 'static', 'pwa_manifest', 'service_worker'}

@app.before_request
def require_login():
    if not ADMIN_PASSWORD:
        return
    if request.endpoint in _PUBLIC_ENDPOINTS:
        return
    if session.get('authenticated'):
        return
    # Rotas de API retornam JSON 401
    if request.is_json or request.path.startswith('/project') or \
       request.path.startswith('/chat') or request.path.startswith('/github') or \
       request.path.startswith('/settings') or request.path.startswith('/ai') or \
       request.path.startswith('/usage') or request.path.startswith('/debug'):
        return jsonify({"error": "Não autenticado. Faça login."}), 401
    return redirect(url_for('login_page'))


@app.route('/login', methods=['GET'])
def login_page():
    if session.get('authenticated'):
        return redirect(url_for('home'))
    return render_template('login.html')


@app.route('/login', methods=['POST'])
def login_post():
    password = request.form.get('password', '').strip()
    if password == ADMIN_PASSWORD:
        session['authenticated'] = True
        session.permanent = False
        return redirect(url_for('home'))
    return render_template('login.html', error='Senha incorreta.')

# ===============================
# Firebase / Firestore
# Suporta credenciais via arquivo (local) ou JSON em variável de ambiente (Render/cloud)
# ===============================
_fb_json_str = os.getenv('FIREBASE_CREDENTIALS_JSON')
if _fb_json_str:
    # Render / produção: JSON completo como variável de ambiente
    _fb_dict = json.loads(_fb_json_str)
    cred = credentials.Certificate(_fb_dict)
else:
    # Local: caminho para o arquivo JSON
    cred = credentials.Certificate(os.getenv('FIREBASE_CREDENTIALS', 'automacoes-royal-x.json'))

firebase_admin.initialize_app(cred)
db = firestore.client()

# Coleção principal para separar das outras automações
COLLECTION = "agente_programacao"

# ===============================
# AI Client (OpenAI API ou modelo local via Ollama)
# Defina AI_PROVIDER=local no .env para usar Ollama
# ===============================
AI_PROVIDER = os.getenv('AI_PROVIDER', 'openai').lower()

if AI_PROVIDER == 'local':
    client = openai.OpenAI(
        base_url=os.getenv('LOCAL_AI_URL', 'http://localhost:11434/v1'),
        api_key=os.getenv('LOCAL_AI_KEY', 'ollama')
    )
    AI_MODEL = os.getenv('LOCAL_AI_MODEL', 'qwen2.5-coder:7b')
else:
    client = openai.OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
    AI_MODEL = os.getenv('OPENAI_MODEL', 'o4-mini')

# ===============================
# GitHub
# ===============================
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')
GITHUB_API = 'https://api.github.com'

SKIP_EXTENSIONS = {
    '.png', '.jpg', '.jpeg', '.gif', '.svg', '.ico', '.woff', '.woff2',
    '.ttf', '.eot', '.pdf', '.zip', '.tar', '.gz', '.lock', '.map',
    '.pyc', '.pyo', '.exe', '.dll', '.so', '.bin'
}

GITHUB_EDIT_PROMPT = """You are a precise software engineer making targeted changes to a GitHub repository.

Analyze the provided files and the instruction carefully. Make exactly the changes needed — no more, no less.

Return ONLY a valid JSON object (no markdown, no extra text):
{
  "commit_message": "type(scope): concise description in imperative mood",
  "updated_files": {
    "path/to/file.ext": "complete new file content as string"
  }
}

Rules:
- Only include files that actually need to change. Do not touch unrelated files.
- Return the COMPLETE, working content of each changed file — not diffs, not partial content.
- Preserve the existing code style, naming conventions, and patterns of each file.
- If a change in one file requires a corresponding change in another, include both.
- Use conventional commits: feat / fix / refactor / style / docs / chore / test.
- Never introduce bugs, remove existing functionality, or add unrequested features.
- If no changes are needed, return updated_files as an empty object {}."""


def gh_headers():
    return {
        'Authorization': f'token {GITHUB_TOKEN}',
        'Accept': 'application/vnd.github.v3+json',
        'Content-Type': 'application/json'
    }

# ===============================
# Escrita de projetos em disco
# ===============================
_default_output = str(pathlib.Path.home() / "Desktop" / "projetos")
PROJECTS_OUTPUT_DIR = os.getenv("PROJECTS_OUTPUT_DIR", _default_output)

# Modelo de visão (usado quando o usuário envia uma imagem)
VISION_MODEL = os.getenv("VISION_MODEL", "llama-3.2-11b-vision-preview")


def _sanitize_name(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*]', '-', name).strip()


def write_project_to_disk(project_name: str, files: dict) -> str | None:
    if not PROJECTS_OUTPUT_DIR:
        return None
    try:
        base = pathlib.Path(PROJECTS_OUTPUT_DIR) / _sanitize_name(project_name)
        base.mkdir(parents=True, exist_ok=True)
        for rel_path, info in files.items():
            target = base / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(info.get("content", ""), encoding="utf-8")
        return str(base)
    except Exception:
        return None


def update_files_on_disk(project_name: str, updated: dict, deleted: list) -> str | None:
    if not PROJECTS_OUTPUT_DIR:
        return None
    try:
        base = pathlib.Path(PROJECTS_OUTPUT_DIR) / _sanitize_name(project_name)
        if not base.exists():
            return None
        for rel_path, info in updated.items():
            target = base / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(info.get("content", ""), encoding="utf-8")
        for rel_path in deleted:
            target = base / rel_path
            if target.exists():
                target.unlink()
        return str(base)
    except Exception:
        return None


# ===============================
# Limites de contexto (evita erro 413 no Groq free tier)
# ===============================
MAX_FILES_GITHUB   = 12      # máx arquivos lidos no GitHub
MAX_FILE_CHARS     = 2500    # máx chars por arquivo
MAX_CONTEXT_CHARS  = 18000   # orçamento total de chars de contexto

# ===============================
# Controle de custos
# ===============================
PRICE_PER_1000_TOKENS_USD = 0.002
USD_TO_BRL = 5.0


def get_tokens_and_cost(usage):
    tokens = usage.total_tokens if usage else 0
    if AI_PROVIDER == 'local':
        return tokens, 0.0
    cost = round((tokens / 1000) * PRICE_PER_1000_TOKENS_USD * USD_TO_BRL, 4)
    return tokens, cost

# ===============================
# Prompts de arquitetura por stack
# ===============================
ARCHITECTURE_GUIDES = {
    "react": """Stack: React (JavaScript) with functional components and hooks.

Architecture guidelines:
- Use Vite structure (preferred) or Create React App.
- Organize by feature/domain: components/, pages/, hooks/, services/, utils/, context/.
- Use functional components with React hooks (useState, useEffect, useContext, useCallback, useMemo).
- CSS Modules (.module.css) for styling.
- Create a services/ folder for API calls using fetch or axios.
- Use React Context API for simple global state.
- File extensions: ALL components and files containing JSX must use .jsx extension. Pure JS utility files (no JSX) use .js. CSS files use .css.
- Entry point: main.jsx (not main.js). App component: App.jsx.
- Include a proper package.json with react, react-dom, react-router-dom.
- Add ESLint config.
- Create reusable components in components/ (*.jsx) and page-level components in pages/ (*.jsx).
- Use React Router for navigation with a central routes config.
- Add PropTypes for type checking.""",

    "react-ts": """Stack: React with TypeScript (TSX).

Architecture guidelines:
- Use Vite with React + TypeScript template structure.
- Organize by feature/domain: components/, pages/, hooks/, services/, utils/, context/, types/.
- Use functional components with typed props via interfaces.
- Create a types/ or interfaces/ folder for shared TypeScript types and interfaces.
- CSS Modules (.module.css) or Tailwind CSS for styling.
- Services layer in services/ using typed fetch/axios wrappers with generics.
- React Context API with typed contexts and providers.
- File extensions: ALL components and files containing JSX must use .tsx extension. Pure TypeScript files (no JSX) use .ts. CSS files use .css.
- Entry point: main.tsx. App component: App.tsx.
- Include tsconfig.json with strict mode enabled.
- Include package.json with react, react-dom, react-router-dom, typescript, @types/react, @types/react-dom.
- Use path aliases in tsconfig (e.g., @components/, @services/, @hooks/).
- Create custom hooks with proper TypeScript return types.
- Use enums or union types for constants.
- Add ESLint with @typescript-eslint plugin.""",

    "vanilla": """Stack: HTML, CSS e JavaScript puro (sem frameworks).

Architecture guidelines:
- Structure: index.html na raiz, css/style.css, js/main.js e pastas adicionais conforme necessidade.
- Use HTML5 semântico: header, main, section, article, footer, nav.
- CSS: variáveis CSS (custom properties) para cores e fontes, Flexbox e Grid para layout, media queries para responsividade mobile-first.
- JavaScript: ES6+ (const/let, arrow functions, template literals, destructuring, fetch API, async/await).
- Separe responsabilidades: HTML para estrutura, CSS para estilo, JS para comportamento.
- Organize o JS em módulos lógicos dentro do mesmo arquivo ou em arquivos separados em js/.
- Use fetch API para chamadas HTTP quando necessário.
- Inclua um arquivo README.md com instruções de como abrir o projeto.
- Não use dependências externas — apenas HTML, CSS e JS nativos do navegador.
- O projeto deve funcionar abrindo o index.html diretamente no navegador (sem servidor).""",

    "python": """Stack: Python.

Architecture guidelines:
- Detect the type of project from the description:
  - Web API: Use FastAPI with uvicorn. Structure: app/, app/routers/, app/models/, app/schemas/, app/services/, app/core/.
  - Web App: Use Flask with Blueprints. Structure: app/, app/routes/, app/models/, app/templates/, app/static/, app/services/.
  - CLI/Script: Use argparse or click. Structure: src/, src/commands/, src/utils/, src/core/.
  - Automation/Bot: Structure: bot/, bot/handlers/, bot/services/, bot/utils/, bot/config/.
- Use virtual environment (include requirements.txt with all dependencies).
- Follow PEP 8 conventions strictly.
- Use type hints (Python 3.10+ syntax: str | None instead of Optional[str]).
- Create a .env.example for environment variables.
- Separate business logic in services/ from route handlers.
- Use Pydantic models for data validation (FastAPI) or dataclasses.
- Include proper error handling with custom exceptions.
- Add __init__.py files for all packages.
- Include a main entry point (main.py or __main__.py).
- Use logging instead of print statements."""
}

JSON_FORMAT_INSTRUCTION = """
OUTPUT: a single raw JSON object. No markdown fences, no text before or after, no explanation.

{
  "project_name": "short-kebab-case-name",
  "folder_structure": "Visual tree using ├──, └──, │",
  "summary": "Resumo em português (4-6 frases): tipo de aplicação, decisões arquiteturais e motivação, arquivos mais importantes e seus papéis, como instalar e rodar.",
  "files": {
    "relative/path/file.ext": {
      "content": "complete file content",
      "language": "identifier"
    }
  }
}

CODE QUALITY RULES — these are non-negotiable:
- Every function, method, and handler must be FULLY IMPLEMENTED. No `// TODO`, no `pass`, no `raise NotImplementedError`, no placeholder logic, no "add your code here" comments.
- Write code that runs immediately after `npm install` / `pip install -r requirements.txt` / opening index.html — zero manual edits required.
- Well-named identifiers communicate what the code does. Only add a comment when the WHY is genuinely non-obvious: a hidden constraint, a workaround for a specific bug, a subtle invariant. Never comment the obvious.
- No multi-line docstrings that just restate the function name.
- Validate at system boundaries (user input, external API responses, file I/O). Do not add defensive checks for things internal code guarantees.
- Security by default: parameterized queries, output escaping, no secrets in code, descriptive-but-safe error messages.
- Include every required config file: package.json, tsconfig.json, requirements.txt, .env.example, .gitignore, etc.
- "language" values: python, javascript, typescript, tsx, jsx, json, css, html, markdown, yaml, bash, text.
- FILE EXTENSION RULE: React components → .jsx (JS) or .tsx (TS). Never .js for a file that contains JSX. Never .ts for a file that contains JSX.
- "summary" must always be in Brazilian Portuguese."""

CHAT_JSON_FORMAT = """
OUTPUT: a single raw JSON object. No markdown, no text before or after.

{{
  "updated_files": {{
    "relative/path/file.ext": {{
      "content": "complete new file content",
      "language": "identifier"
    }}
  }},
  "deleted_files": ["path/to/removed.ext"],
  "folder_structure": "updated visual tree",
  "summary": "Resumo em português (3-5 frases): o que mudou e por quê, quais arquivos foram afetados, impacto no projeto, e qualquer passo que o dev precisa executar (instalar dependência, variável de ambiente nova, etc.)."
}}

RULES:
- Include ONLY files that actually changed. Do not re-send unchanged files.
- Return the COMPLETE content of every changed file — not a diff, not a partial snippet.
- If a change in one file requires updating another (e.g., you rename a function, update all its callers), include both files.
- Fully implement every change. No stubs, no TODOs, no placeholder bodies.
- Maintain the existing code style, naming conventions, and patterns of the project.
- deleted_files: empty array [] if nothing was deleted.
- summary must always be in Brazilian Portuguese."""


def get_create_prompt(language):
    arch_guide = ARCHITECTURE_GUIDES.get(language, ARCHITECTURE_GUIDES["react"])
    custom = load_settings().get('agent_instructions', '').strip()
    extra = f"\n\nDeveloper custom instructions (apply to every project, without exception):\n{custom}" if custom else ""
    return f"""You are an elite software engineer. Your job is to build complete, production-ready applications from a description — not prototypes, not demos, not templates.

## How you work

You think like a senior engineer who has shipped this exact type of app before:
1. Read the description carefully and identify what the user actually needs.
2. Choose the right architecture for the scale and complexity implied — not over-engineered, not under-built.
3. Generate every file in the project with complete, working code.

## What "complete" means

Every file you generate must be immediately runnable. This means:
- Every function has a real implementation. No `// TODO`, no `pass`, no `throw new Error("not implemented")`.
- All imports are correct and point to real modules.
- All environment variables have corresponding `.env.example` entries.
- Configuration files (package.json, tsconfig.json, requirements.txt, .gitignore) are included and correct.
- The project works right after `npm install && npm run dev`, or `pip install -r requirements.txt && python main.py`, or opening index.html — no manual edits required.

## Code quality

- Name things clearly. The name explains what it does; a comment only explains why when it's non-obvious.
- No comment blocks restating what the code does. No "// This function handles authentication" above `function handleAuth()`.
- Error handling at the edges: HTTP handlers, file I/O, external API calls. Don't wrap internal calls that can't fail.
- Security: validate user input, escape outputs, use parameterized queries, never expose stack traces to clients.
- Build exactly what was described. No hypothetical future features, no premature abstractions.

{arch_guide}{extra}

{JSON_FORMAT_INSTRUCTION}"""


def get_chat_prompt(language, project_name, files_context, conversation):
    arch_guide = ARCHITECTURE_GUIDES.get(language, ARCHITECTURE_GUIDES["react"])
    custom = load_settings().get('agent_instructions', '').strip()
    extra = f"\n\nDeveloper custom instructions (apply to every change, without exception):\n{custom}" if custom else ""
    return f"""You are operating as a code editor with full knowledge of an existing project. Your task is to apply the requested changes — precisely and completely.

## Project: {project_name}

## How you work

1. Read the existing files carefully. Understand every pattern, naming convention, and architectural decision already in place.
2. Identify the minimal set of changes needed to fulfill the request.
3. Make those changes — nothing more. Don't refactor code you weren't asked to change.

## Rules for every change

- **Targeted**: only modify files that must change. Don't re-send files that are identical to what's already there.
- **Complete**: return the full content of every file you touch — not a diff, not a partial snippet, not pseudocode.
- **Consistent**: match the existing naming conventions, import style, file structure, and code patterns exactly.
- **Coherent**: if you change a function signature, update every caller. If you add a route, wire it into the router. If you add a component, import it where needed. Incomplete changes that would break the build are not acceptable.
- **Fully implemented**: every new or modified function has a real body. No stubs, no TODOs, no placeholder returns.
- **Non-destructive**: never silently remove existing functionality while adding new functionality.

{arch_guide}{extra}

## Current codebase
{files_context}

## Conversation so far
{conversation}

{CHAT_JSON_FORMAT}"""


def parse_ai_json(text):
    cleaned = text.strip()
    cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
    cleaned = re.sub(r'\s*```$', '', cleaned)
    return json.loads(cleaned)


def _build_attached_files_block(attached_files: list) -> str:
    if not attached_files:
        return ""
    parts = ["\n\nArquivos enviados pelo usuário (use como referência ou contexto para a tarefa):"]
    budget = MAX_CONTEXT_CHARS
    for f in attached_files:
        if budget <= 0:
            parts.append(f"\n--- {f.get('name', 'arquivo')} --- [omitido: limite de contexto]")
            continue
        content = f.get('content', '')[:MAX_FILE_CHARS]
        entry = f"\n--- {f.get('name', 'arquivo')} ---\n{content}\n--- fim ---"
        parts.append(entry)
        budget -= len(entry)
    return "\n".join(parts)


def build_vision_message(text: str, image_b64: str, image_mime: str = "image/jpeg") -> dict:
    return {
        "role": "user",
        "content": [
            {"type": "text", "text": text},
            {"type": "image_url", "image_url": {"url": f"data:{image_mime};base64,{image_b64}"}}
        ]
    }


def call_ai(messages, max_retries=2, model: str | None = None):
    use_model = model or AI_MODEL
    for attempt in range(max_retries + 1):
        try:
            response = client.chat.completions.create(
                model=use_model,
                messages=messages
            )
        except openai.APIConnectionError as e:
            url = os.getenv('LOCAL_AI_URL', 'não definido')
            raise ValueError(f"Não foi possível conectar à API ({url}). Verifique LOCAL_AI_URL e LOCAL_AI_KEY no Render. Detalhe: {e.__cause__ or e}")
        except openai.AuthenticationError:
            raise ValueError("Chave de API inválida ou não definida. Verifique LOCAL_AI_KEY no painel do Render.")
        except openai.RateLimitError as e:
            raise ValueError(f"Limite de requisições atingido (rate limit): {e}")
        except openai.APIStatusError as e:
            raise ValueError(f"Erro da API [{e.status_code}]: {e.message}")
        except Exception as e:
            raise ValueError(f"Erro inesperado ao chamar a IA ({type(e).__name__}): {e}")

        content = response.choices[0].message.content
        usage = response.usage
        try:
            parsed = parse_ai_json(content)
            return parsed, usage
        except json.JSONDecodeError:
            if attempt == max_retries:
                raise ValueError(f"A IA retornou JSON inválido após {max_retries + 1} tentativas. Resposta: {content[:500]}")
            messages.append({"role": "assistant", "content": content})
            messages.append({"role": "user", "content": "Your response was not valid JSON. Please return ONLY a valid JSON object with no text before or after."})


def build_files_context(files):
    parts = []
    budget = MAX_CONTEXT_CHARS
    for path, info in files.items():
        if budget <= 0:
            parts.append(f"--- {path} --- [omitido: limite de contexto atingido]\n")
            continue
        content = info.get('content', '')[:MAX_FILE_CHARS]
        entry = f"--- {path} ---\n{content}\n"
        parts.append(entry)
        budget -= len(entry)
    return "\n".join(parts)


def build_conversation_context(conversation):
    parts = []
    for msg in conversation:
        role = msg.get('role', 'user')
        content = msg.get('content', '')
        parts.append(f"[{role}]: {content}")
    return "\n".join(parts)


# ===============================
# Tracking de uso diário
# ===============================
def get_today_key():
    return date.today().isoformat()


def track_daily_usage(tokens, cost):
    today = get_today_key()
    usage_ref = db.collection(COLLECTION).document("_usage").collection("daily").document(today)
    usage_doc = usage_ref.get()

    if usage_doc.exists:
        data = usage_doc.to_dict()
        usage_ref.update({
            "tokens": data.get("tokens", 0) + tokens,
            "cost": round(data.get("cost", 0) + cost, 4),
            "requests": data.get("requests", 0) + 1,
            "updated_at": datetime.utcnow().isoformat()
        })
    else:
        usage_ref.set({
            "date": today,
            "tokens": tokens,
            "cost": round(cost, 4),
            "requests": 1,
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat()
        })


def get_daily_usage():
    today = get_today_key()
    usage_ref = db.collection(COLLECTION).document("_usage").collection("daily").document(today)
    usage_doc = usage_ref.get()

    if usage_doc.exists:
        data = usage_doc.to_dict()
        return {
            "date": today,
            "tokens": data.get("tokens", 0),
            "cost": round(data.get("cost", 0), 4),
            "requests": data.get("requests", 0)
        }
    return {"date": today, "tokens": 0, "cost": 0, "requests": 0}


# ===============================
# Helper: coleção de projetos
# ===============================
def projects_collection():
    return db.collection(COLLECTION).document("_data").collection("projects")


# ===============================
# Rotas
# ===============================
@app.route('/')
def home():
    resp = app.make_response(render_template('index.html'))
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate'
    resp.headers['Pragma'] = 'no-cache'
    return resp


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login_page'))


@app.route('/manifest.json')
def pwa_manifest():
    return send_file('static/manifest.json', mimetype='application/manifest+json')


@app.route('/sw.js')
def service_worker():
    resp = send_file('static/sw.js', mimetype='application/javascript')
    resp.headers['Service-Worker-Allowed'] = '/'
    return resp


@app.route('/usage/today', methods=['GET'])
def usage_today():
    return jsonify(get_daily_usage())


@app.route('/project/create', methods=['POST'])
def create_project():
    try:
        data = request.get_json()
        description = data.get('description', '').strip()
        language = data.get('language', 'react')

        if not description:
            return jsonify({"error": "Descreva a aplicação que deseja criar."}), 400

        lang_labels = {
            "react": "React (JavaScript)",
            "react-ts": "React with TypeScript",
            "python": "Python",
            "vanilla": "HTML + CSS + JavaScript"
        }
        lang_label = lang_labels.get(language, language)
        image_b64 = data.get('image_b64')
        image_mime = data.get('image_mime', 'image/jpeg')
        attached_files = data.get('attached_files', [])

        image_instruction = "\n\nThe user provided a reference image. Replicate the visual design, layout and structure shown in the image as closely as possible." if image_b64 else ""
        files_block = _build_attached_files_block(attached_files)
        user_msg = f"Build this application using {lang_label}:\n\n{description}{image_instruction}{files_block}"

        system_prompt = get_create_prompt(language)

        if image_b64:
            user_content = build_vision_message(user_msg, image_b64, image_mime)
            messages = [{"role": "system", "content": system_prompt}, user_content]
            use_model = VISION_MODEL
        else:
            messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_msg}]
            use_model = None

        parsed, usage = call_ai(messages, model=use_model)

        tokens_used, cost = get_tokens_and_cost(usage)
        try:
            track_daily_usage(tokens_used, cost)
        except Exception:
            pass

        project_name = parsed.get("project_name", "meu-projeto")
        num_files = len(parsed.get("files", {}))
        default_msg = f"Projeto '{project_name}' criado com {num_files} arquivos usando {lang_label}."
        assistant_msg = parsed.get("summary") or default_msg

        project_data = {
            "project_name": project_name,
            "description": description,
            "language": language,
            "folder_structure": parsed.get("folder_structure", ""),
            "files": parsed.get("files", {}),
            "tokens_used": tokens_used,
            "cost_used": cost,
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat()
        }

        doc_ref = projects_collection().document()
        doc_ref.set(project_data)

        output_path = write_project_to_disk(project_name, parsed.get("files", {}))

        now = datetime.utcnow().isoformat()
        messages_ref = doc_ref.collection("messages")
        messages_ref.add({"role": "user", "content": description, "timestamp": now})
        messages_ref.add({"role": "assistant", "content": assistant_msg, "timestamp": now})

        conversation = [
            {"role": "user", "content": description},
            {"role": "assistant", "content": assistant_msg}
        ]

        try:
            daily = get_daily_usage()
        except Exception:
            daily = {"tokens": 0, "cost": 0}

        return jsonify({
            "project_id": doc_ref.id,
            "project_name": project_data["project_name"],
            "folder_structure": project_data["folder_structure"],
            "files": project_data["files"],
            "conversation": conversation,
            "assistant_msg": assistant_msg,
            "output_path": output_path,
            "tokens_used": tokens_used,
            "cost_used": cost,
            "daily_tokens": daily["tokens"],
            "daily_cost": daily["cost"]
        })

    except Exception as e:
        app.logger.error(f"create_project error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route('/project/<project_id>', methods=['GET'])
def get_project(project_id):
    doc_ref = projects_collection().document(project_id)
    doc = doc_ref.get()
    if not doc.exists:
        return jsonify({"error": "Projeto não encontrado."}), 404

    data = doc.to_dict()

    # Ler mensagens da subcoleção ordenadas por timestamp
    messages_docs = doc_ref.collection("messages").order_by("timestamp").stream()
    conversation = []
    for msg_doc in messages_docs:
        msg = msg_doc.to_dict()
        conversation.append({"role": msg.get("role", "user"), "content": msg.get("content", "")})

    daily = get_daily_usage()

    return jsonify({
        "project_id": project_id,
        "project_name": data.get("project_name", ""),
        "description": data.get("description", ""),
        "language": data.get("language", ""),
        "folder_structure": data.get("folder_structure", ""),
        "files": data.get("files", {}),
        "conversation": conversation,
        "tokens_used": data.get("tokens_used", 0),
        "cost_used": data.get("cost_used", 0),
        "daily_tokens": daily["tokens"],
        "daily_cost": daily["cost"]
    })


@app.route('/project/<project_id>/chat', methods=['POST'])
def chat_project(project_id):
    try:
        doc_ref = projects_collection().document(project_id)
        doc = doc_ref.get()
        if not doc.exists:
            return jsonify({"error": "Projeto não encontrado."}), 404

        project = doc.to_dict()
        req_data = request.get_json()
        user_message = req_data.get('message', '').strip()
        image_b64 = req_data.get('image_b64')
        image_mime = req_data.get('image_mime', 'image/jpeg')
        attached_files = req_data.get('attached_files', [])

        if not user_message:
            return jsonify({"error": "Digite uma mensagem."}), 400

        messages_docs = doc_ref.collection("messages").order_by("timestamp").stream()
        conversation_list = []
        for msg_doc in messages_docs:
            msg = msg_doc.to_dict()
            conversation_list.append({"role": msg.get("role", "user"), "content": msg.get("content", "")})

        files_context = build_files_context(project.get("files", {}))
        conversation_context = build_conversation_context(conversation_list)

        language = project.get("language", "react")
        system_prompt = get_chat_prompt(
            language=language,
            project_name=project.get("project_name", ""),
            files_context=files_context,
            conversation=conversation_context
        )

        files_block = _build_attached_files_block(attached_files)
        full_message = user_message + files_block

        if image_b64:
            image_note = "\n\nThe user provided a reference image. Apply the visual design/layout shown in the image to the relevant files."
            user_content = build_vision_message(full_message + image_note, image_b64, image_mime)
            messages = [{"role": "system", "content": system_prompt}, user_content]
            use_model = VISION_MODEL
        else:
            messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": full_message}]
            use_model = None

        parsed, usage = call_ai(messages, model=use_model)

        req_tokens, req_cost = get_tokens_and_cost(usage)
        try:
            track_daily_usage(req_tokens, req_cost)
        except Exception:
            pass

        tokens_used = project.get("tokens_used", 0) + req_tokens
        total_cost = round(project.get("cost_used", 0) + req_cost, 4)

        current_files = project.get("files", {})
        updated_files = parsed.get("updated_files", {})
        deleted_files = parsed.get("deleted_files", [])

        for path, file_info in updated_files.items():
            current_files[path] = file_info
        for path in deleted_files:
            current_files.pop(path, None)

        new_structure = parsed.get("folder_structure", project.get("folder_structure", ""))

        default_msg = f"Atualizado {len(updated_files)} arquivo(s)."
        if deleted_files:
            default_msg += f" Removido {len(deleted_files)} arquivo(s)."
        assistant_msg = parsed.get("summary") or default_msg

        project_name_disk = project.get("project_name", "projeto")
        output_path = update_files_on_disk(project_name_disk, updated_files, deleted_files)

        now = datetime.utcnow().isoformat()
        messages_ref = doc_ref.collection("messages")
        messages_ref.add({"role": "user", "content": user_message, "timestamp": now})
        messages_ref.add({"role": "assistant", "content": assistant_msg, "timestamp": now})

        doc_ref.update({
            "files": current_files,
            "folder_structure": new_structure,
            "tokens_used": tokens_used,
            "cost_used": total_cost,
            "updated_at": now
        })

        conversation_list.append({"role": "user", "content": user_message})
        conversation_list.append({"role": "assistant", "content": assistant_msg})

        try:
            daily = get_daily_usage()
        except Exception:
            daily = {"tokens": 0, "cost": 0}

        return jsonify({
            "folder_structure": new_structure,
            "updated_files": updated_files,
            "deleted_files": deleted_files,
            "files": current_files,
            "conversation": conversation_list,
            "assistant_msg": assistant_msg,
            "output_path": output_path,
            "req_tokens": req_tokens,
            "req_cost": req_cost,
            "tokens_used": tokens_used,
            "cost_used": total_cost,
            "daily_tokens": daily["tokens"],
            "daily_cost": daily["cost"]
        })

    except Exception as e:
        app.logger.error(f"chat_project error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route('/projects', methods=['GET'])
def list_projects():
    docs = projects_collection().order_by("updated_at", direction=firestore.Query.DESCENDING).limit(50).stream()
    lang_labels = {
        "react": "React",
        "react-ts": "React + TS",
        "python": "Python",
        "vanilla": "HTML + CSS + JS"
    }
    projects = []
    for doc in docs:
        data = doc.to_dict()
        language = data.get("language", "")
        num_files = len(data.get("files", {}))
        projects.append({
            "project_id": doc.id,
            "project_name": data.get("project_name", ""),
            "description": data.get("description", "")[:100],
            "language": language,
            "language_label": lang_labels.get(language, language),
            "num_files": num_files,
            "tokens_used": data.get("tokens_used", 0),
            "cost_used": data.get("cost_used", 0),
            "created_at": data.get("created_at", ""),
            "updated_at": data.get("updated_at", "")
        })
    return jsonify({"projects": projects})


@app.route('/project/<project_id>', methods=['DELETE'])
def delete_project(project_id):
    doc_ref = projects_collection().document(project_id)
    doc = doc_ref.get()
    if not doc.exists:
        return jsonify({"error": "Projeto não encontrado."}), 404

    # Deletar subcoleção de mensagens
    messages = doc_ref.collection("messages").stream()
    for msg in messages:
        msg.reference.delete()

    doc_ref.delete()
    return jsonify({"success": True, "message": "Projeto deletado."})


# ===============================
# GitHub Routes
# ===============================
@app.route('/github/repos', methods=['GET'])
def github_repos():
    if not GITHUB_TOKEN:
        return jsonify({"error": "GITHUB_TOKEN não configurado no .env"}), 400
    res = http.get(
        f'{GITHUB_API}/user/repos',
        params={'per_page': 100, 'sort': 'updated', 'affiliation': 'owner,collaborator'},
        headers=gh_headers()
    )
    if res.status_code != 200:
        msg = res.json().get('message', 'Erro desconhecido')
        return jsonify({"error": f"Erro ao buscar repositórios: {msg}"}), 400

    repos = [{
        "name": r["name"],
        "full_name": r["full_name"],
        "private": r["private"],
        "default_branch": r["default_branch"],
        "description": r.get("description") or ""
    } for r in res.json()]
    return jsonify({"repos": repos})


@app.route('/github/repo/<owner>/<repo>/tree', methods=['GET'])
def github_tree(owner, repo):
    if not GITHUB_TOKEN:
        return jsonify({"error": "GITHUB_TOKEN não configurado no .env"}), 400

    branch = request.args.get('branch', '')
    if not branch:
        repo_res = http.get(f'{GITHUB_API}/repos/{owner}/{repo}', headers=gh_headers())
        if repo_res.status_code != 200:
            return jsonify({"error": "Repositório não encontrado."}), 404
        branch = repo_res.json().get('default_branch', 'main')

    tree_res = http.get(
        f'{GITHUB_API}/repos/{owner}/{repo}/git/trees/{branch}',
        params={'recursive': '1'},
        headers=gh_headers()
    )
    if tree_res.status_code != 200:
        return jsonify({"error": "Erro ao buscar arquivos do repositório."}), 400

    all_files = [
        item["path"] for item in tree_res.json().get("tree", [])
        if item["type"] == "blob"
        and not any(item["path"].lower().endswith(ext) for ext in SKIP_EXTENSIONS)
        and 'node_modules/' not in item["path"]
        and '.git/' not in item["path"]
    ]
    return jsonify({"files": all_files, "branch": branch})


@app.route('/github/repo/<owner>/<repo>/ai-edit', methods=['POST'])
def github_ai_edit(owner, repo):
    if not GITHUB_TOKEN:
        return jsonify({"error": "GITHUB_TOKEN não configurado no .env"}), 400

    data = request.get_json()
    instruction = data.get('instruction', '').strip()
    file_paths = data.get('files', [])
    branch = data.get('branch', 'main')

    if not instruction:
        return jsonify({"error": "Forneça uma instrução para a IA."}), 400

    # Se nenhum arquivo foi especificado, busca todos (até 30)
    if not file_paths:
        tree_res = http.get(
            f'{GITHUB_API}/repos/{owner}/{repo}/git/trees/{branch}',
            params={'recursive': '1'},
            headers=gh_headers()
        )
        if tree_res.status_code != 200:
            return jsonify({"error": "Erro ao buscar arquivos."}), 400
        file_paths = [
            item["path"] for item in tree_res.json().get("tree", [])
            if item["type"] == "blob"
            and not any(item["path"].lower().endswith(ext) for ext in SKIP_EXTENSIONS)
            and 'node_modules/' not in item["path"]
        ]
        file_paths = file_paths[:MAX_FILES_GITHUB]

    # Busca conteúdo de cada arquivo com limite de chars
    files_content = {}
    budget = MAX_CONTEXT_CHARS
    for path in file_paths:
        if budget <= 0:
            break
        file_res = http.get(
            f'{GITHUB_API}/repos/{owner}/{repo}/contents/{path}',
            params={'ref': branch},
            headers=gh_headers()
        )
        if file_res.status_code == 200:
            try:
                raw = base64.b64decode(file_res.json()['content']).decode('utf-8', errors='replace')
                content = raw[:MAX_FILE_CHARS]
                files_content[path] = content
                budget -= len(content)
            except Exception:
                pass

    if not files_content:
        return jsonify({"error": "Nenhum arquivo encontrado para editar."}), 400

    files_text = "\n".join(f"--- {p} ---\n{c}\n" for p, c in files_content.items())

    messages = [
        {"role": "system", "content": GITHUB_EDIT_PROMPT},
        {"role": "user", "content": f"Repository: {owner}/{repo}\n\nFiles:\n{files_text}\n\nInstruction: {instruction}"}
    ]

    try:
        parsed, usage = call_ai(messages)
    except Exception as e:
        err = str(e)
        if '413' in err or 'too large' in err.lower() or 'rate_limit' in err.lower():
            return jsonify({"error": "Contexto muito grande para o modelo. Selecione menos arquivos ou arquivos menores e tente novamente."}), 413
        return jsonify({"error": f"Erro ao processar com IA: {err}"}), 500

    tokens_used, cost = get_tokens_and_cost(usage)
    track_daily_usage(tokens_used, cost)

    updated_files = parsed.get("updated_files", {})
    commit_message = parsed.get("commit_message", f"ai: {instruction[:72]}")

    if not updated_files:
        return jsonify({"error": "A IA não identificou nenhuma alteração necessária.", "commit_message": commit_message}), 400

    # Commita via GitHub Git Data API (suporta múltiplos arquivos num único commit)
    try:
        ref_res = http.get(
            f'{GITHUB_API}/repos/{owner}/{repo}/git/refs/heads/{branch}',
            headers=gh_headers()
        )
        if ref_res.status_code != 200:
            return jsonify({"error": f"Branch '{branch}' não encontrada."}), 400

        latest_sha = ref_res.json()["object"]["sha"]

        commit_res = http.get(
            f'{GITHUB_API}/repos/{owner}/{repo}/git/commits/{latest_sha}',
            headers=gh_headers()
        )
        base_tree_sha = commit_res.json()["tree"]["sha"]

        # Cria blobs para cada arquivo alterado
        new_tree = []
        for file_path, new_content in updated_files.items():
            blob_res = http.post(
                f'{GITHUB_API}/repos/{owner}/{repo}/git/blobs',
                headers=gh_headers(),
                json={"content": new_content, "encoding": "utf-8"}
            )
            if blob_res.status_code == 201:
                new_tree.append({
                    "path": file_path,
                    "mode": "100644",
                    "type": "blob",
                    "sha": blob_res.json()["sha"]
                })

        if not new_tree:
            return jsonify({"error": "Falha ao criar blobs no GitHub."}), 500

        # Cria nova tree
        tree_res = http.post(
            f'{GITHUB_API}/repos/{owner}/{repo}/git/trees',
            headers=gh_headers(),
            json={"base_tree": base_tree_sha, "tree": new_tree}
        )
        if tree_res.status_code != 201:
            return jsonify({"error": "Erro ao criar tree no GitHub."}), 500

        # Cria o commit
        new_commit_res = http.post(
            f'{GITHUB_API}/repos/{owner}/{repo}/git/commits',
            headers=gh_headers(),
            json={"message": commit_message, "tree": tree_res.json()["sha"], "parents": [latest_sha]}
        )
        if new_commit_res.status_code != 201:
            return jsonify({"error": "Erro ao criar commit no GitHub."}), 500

        new_commit_sha = new_commit_res.json()["sha"]

        # Atualiza a referência da branch
        update_res = http.patch(
            f'{GITHUB_API}/repos/{owner}/{repo}/git/refs/heads/{branch}',
            headers=gh_headers(),
            json={"sha": new_commit_sha}
        )
        if update_res.status_code != 200:
            return jsonify({"error": "Erro ao atualizar branch no GitHub."}), 500

    except Exception as e:
        return jsonify({"error": f"Erro ao commitar no GitHub: {str(e)}"}), 500

    daily = get_daily_usage()

    return jsonify({
        "commit_sha": new_commit_sha,
        "commit_url": f"https://github.com/{owner}/{repo}/commit/{new_commit_sha}",
        "commit_message": commit_message,
        "files_changed": list(updated_files.keys()),
        "tokens_used": tokens_used,
        "cost_used": cost,
        "daily_tokens": daily["tokens"],
        "daily_cost": daily["cost"]
    })


# ===============================
# Chat Geral (sem contexto de projeto)
# ===============================
GENERAL_CHAT_SYSTEM = """Você é um assistente direto e experiente para um desenvolvedor autônomo brasileiro. Responda sempre em português.

Seu interlocutor: dev que usa IA para acelerar entregas, atende clientes, vive de código. Não precisa de introduções longas nem de ressalvas óbvias.

Você ajuda com qualquer coisa relevante:
- Decisões técnicas e arquitetura — dê uma recomendação concreta, não uma lista de opções sem conclusão
- Negócios freelancer — precificação real, como estruturar proposta, como negociar, como posicionar serviço
- Escolha de ferramentas — diga qual usar e por quê, sem ficar listando todas as alternativas
- Produtividade — o que realmente funciona para dev solo com entregas constantes
- Qualquer outra dúvida técnica, comercial ou estratégica

Como responder:
- Seja direto: dê a resposta primeiro, explique depois se necessário
- Seja concreto: números, exemplos reais, não generalidades
- Seja breve: se cabe em 3 linhas, não use 10
- Dê uma opinião quando perguntado — "depende" sem sugerir o caminho mais provável não ajuda ninguém
- Quando a pergunta for técnica e tiver uma resposta objetivamente melhor, dê essa resposta"""


@app.route('/chat/general', methods=['POST'])
def chat_general():
    data = request.get_json()
    history = data.get('messages', [])

    if not history:
        return jsonify({"error": "Sem mensagens."}), 400

    memory = load_settings().get('assistant_memory', '').strip()
    system_content = GENERAL_CHAT_SYSTEM
    if memory:
        system_content += f"\n\nContexto do desenvolvedor (sempre leve em conta):\n{memory}"

    try:
        response = client.chat.completions.create(
            model=AI_MODEL,
            messages=[{"role": "system", "content": system_content}] + history
        )
        reply = response.choices[0].message.content
        tokens, cost = get_tokens_and_cost(response.usage)
        track_daily_usage(tokens, cost)
        return jsonify({"response": reply, "tokens": tokens, "cost": cost})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ===============================
# Download do projeto como ZIP
# ===============================
@app.route('/project/<project_id>/download', methods=['GET'])
def download_project(project_id):
    doc_ref = projects_collection().document(project_id)
    doc = doc_ref.get()
    if not doc.exists:
        return jsonify({"error": "Projeto não encontrado."}), 404

    data = doc.to_dict()
    files = data.get("files", {})
    project_name = data.get("project_name", "projeto")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for path, file_info in files.items():
            zf.writestr(f"{project_name}/{path}", file_info.get("content", ""))
    buf.seek(0)

    return send_file(
        buf,
        mimetype='application/zip',
        as_attachment=True,
        download_name=f"{project_name}.zip"
    )


# ===============================
# Configurações do usuário (salvas em settings.json)
# ===============================
SETTINGS_FILE = pathlib.Path(__file__).parent / 'settings.json'


def load_settings() -> dict:
    if SETTINGS_FILE.exists():
        try:
            with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_settings(settings: dict):
    with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
        json.dump(settings, f, indent=2, ensure_ascii=False)


@app.route('/settings', methods=['GET'])
def get_settings():
    return jsonify(load_settings())


@app.route('/settings', methods=['POST'])
def post_settings():
    data = request.get_json()
    settings = load_settings()
    settings.update(data)
    _save_settings(settings)
    return jsonify({'success': True})


# ===============================
# Configuração de diretório de saída (mantido para compatibilidade)
# ===============================
@app.route('/settings/output-dir', methods=['GET'])
def get_output_dir():
    return jsonify({"dir": PROJECTS_OUTPUT_DIR})


# ===============================
# Info do provedor de IA ativo
# ===============================
@app.route('/ai/info', methods=['GET'])
def ai_info():
    local_url = os.getenv('LOCAL_AI_URL', '')
    if AI_PROVIDER == 'openai':
        provider_label = 'OpenAI'
    elif 'groq.com' in local_url:
        provider_label = 'Groq'
    else:
        provider_label = 'Ollama'
    return jsonify({"provider_label": provider_label, "model": AI_MODEL})


@app.route('/debug/ai', methods=['GET'])
def debug_ai():
    key = os.getenv('LOCAL_AI_KEY', '')
    return jsonify({
        "AI_PROVIDER": AI_PROVIDER,
        "LOCAL_AI_URL": os.getenv('LOCAL_AI_URL', 'NÃO DEFINIDO'),
        "LOCAL_AI_MODEL": AI_MODEL,
        "VISION_MODEL": VISION_MODEL,
        "LOCAL_AI_KEY_set": bool(key and key != 'ollama'),
        "LOCAL_AI_KEY_preview": (key[:8] + '...') if len(key) > 8 else ('NÃO DEFINIDO' if not key else key),
    })


# ===============================
# Inicialização
# ===============================
if __name__ == '__main__':
    port = int(os.getenv('PORT', 8000))
    debug = os.getenv('FLASK_ENV') != 'production'
    app.run(debug=debug, host='0.0.0.0', port=port)
