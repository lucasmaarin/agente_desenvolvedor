from flask import Flask, render_template, request, jsonify, send_file
import os
import io
import zipfile
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
app.secret_key = os.getenv('FLASK_SECRET_KEY', os.urandom(24).hex())

# ===============================
# Firebase / Firestore
# ===============================
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

GITHUB_EDIT_PROMPT = """You are an expert software engineer. The user wants to make changes to files in a GitHub repository.

Given the file contents and the user's instruction, return ONLY a valid JSON object (no markdown, no extra text):
{
  "commit_message": "type(scope): brief description of changes",
  "updated_files": {
    "path/to/file.ext": "complete new file content as string"
  }
}

Rules:
- Only include files that actually need to change.
- Return the COMPLETE content of each changed file (not diffs or partial content).
- Use conventional commits: feat / fix / refactor / style / docs / chore / test.
- If no changes are needed, return updated_files as an empty object {}."""


def gh_headers():
    return {
        'Authorization': f'token {GITHUB_TOKEN}',
        'Accept': 'application/vnd.github.v3+json',
        'Content-Type': 'application/json'
    }

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
- Use Create React App or Vite structure.
- Organize by feature/domain: components/, pages/, hooks/, services/, utils/, context/.
- Use functional components with React hooks (useState, useEffect, useContext, useCallback, useMemo).
- CSS Modules or styled-components for styling (prefer CSS Modules).
- Create a services/ folder for API calls using fetch or axios.
- Use React Context API for simple global state.
- File extensions: .js, .jsx for components, .css for styles.
- Include a proper package.json with react, react-dom, react-router-dom.
- Add ESLint and Prettier config files.
- Create reusable components in components/ and page-level components in pages/.
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
- File extensions: .tsx for components, .ts for logic/types, .css for styles.
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
Return your response as a single JSON object (no markdown fences, no extra text).

The JSON format MUST be:
{
  "project_name": "short-kebab-case-name",
  "folder_structure": "A visual tree string using unicode box-drawing characters (├──, └──, │)",
  "summary": "Resumo em português (4-6 frases) explicando: qual tipo de aplicação foi criada, a arquitetura escolhida e por quê, os arquivos mais importantes e o que cada um faz, e como rodar o projeto.",
  "files": {
    "relative/path/to/file.ext": {
      "content": "full file content as a string",
      "language": "programming language identifier"
    }
  }
}

Rules:
- Generate complete, working, production-quality code.
- Include ALL necessary config files.
- Include helpful comments in the code explaining the logic.
- The "language" field should be one of: python, javascript, typescript, tsx, jsx, json, css, html, markdown, yaml, text, bash.
- The "summary" field must always be in Brazilian Portuguese.
- Return ONLY the JSON. No explanation before or after."""

CHAT_JSON_FORMAT = """
Return a JSON object with ONLY the files that changed or were added:
{{
  "updated_files": {{
    "relative/path/to/changed_file.ext": {{
      "content": "full new content of the file",
      "language": "tsx"
    }}
  }},
  "deleted_files": ["path/to/removed/file.ext"],
  "folder_structure": "updated full visual tree string",
  "summary": "Resumo em português (3-5 frases) explicando: o que foi alterado e por quê, quais arquivos foram modificados/criados/removidos e o impacto da mudança, e se há algo importante que o desenvolvedor precisa saber (dependências, breaking changes, próximos passos sugeridos)."
}}

Rules:
- Return the COMPLETE content of each changed file, not diffs.
- If no files were deleted, use an empty array.
- Always include the updated folder_structure reflecting any structural changes.
- The "summary" field must always be in Brazilian Portuguese.
- Return ONLY valid JSON. No explanation before or after."""


def get_create_prompt(language):
    arch_guide = ARCHITECTURE_GUIDES.get(language, ARCHITECTURE_GUIDES["react"])
    return f"""You are an expert software architect and full-stack developer.
The user will describe an application they want to build. You must:

1. Design a complete project folder structure following professional software architecture patterns.
2. Generate the FULL source code for EVERY file in that structure.

{arch_guide}

{JSON_FORMAT_INSTRUCTION}"""


def get_chat_prompt(language, project_name, files_context, conversation):
    arch_guide = ARCHITECTURE_GUIDES.get(language, ARCHITECTURE_GUIDES["react"])
    return f"""You are an expert software architect modifying an existing project.

Project: {project_name}
{arch_guide}

Current files:
{files_context}

Conversation history:
{conversation}

The user wants to make changes. Follow the same architecture patterns already established in the project.
{CHAT_JSON_FORMAT}"""


def parse_ai_json(text):
    cleaned = text.strip()
    cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
    cleaned = re.sub(r'\s*```$', '', cleaned)
    return json.loads(cleaned)


def call_ai(messages, max_retries=2):
    for attempt in range(max_retries + 1):
        response = client.chat.completions.create(
            model=AI_MODEL,
            messages=messages
        )
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
    for path, info in files.items():
        parts.append(f"--- {path} ---\n{info.get('content', '')}\n")
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
    return render_template('index.html')


@app.route('/usage/today', methods=['GET'])
def usage_today():
    return jsonify(get_daily_usage())


@app.route('/project/create', methods=['POST'])
def create_project():
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
    user_msg = f"Build this application using {lang_label}:\n\n{description}"

    system_prompt = get_create_prompt(language)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_msg}
    ]

    try:
        parsed, usage = call_ai(messages)
    except Exception as e:
        return jsonify({"error": f"Erro ao gerar projeto: {str(e)}"}), 500

    tokens_used, cost = get_tokens_and_cost(usage)

    # Tracking diário
    track_daily_usage(tokens_used, cost)

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

    # Salvar mensagens na subcoleção messages
    now = datetime.utcnow().isoformat()
    messages_ref = doc_ref.collection("messages")
    messages_ref.add({"role": "user", "content": description, "timestamp": now})
    messages_ref.add({"role": "assistant", "content": assistant_msg, "timestamp": now})

    conversation = [
        {"role": "user", "content": description},
        {"role": "assistant", "content": assistant_msg}
    ]

    daily = get_daily_usage()

    return jsonify({
        "project_id": doc_ref.id,
        "project_name": project_data["project_name"],
        "folder_structure": project_data["folder_structure"],
        "files": project_data["files"],
        "conversation": conversation,
        "assistant_msg": assistant_msg,
        "tokens_used": tokens_used,
        "cost_used": cost,
        "daily_tokens": daily["tokens"],
        "daily_cost": daily["cost"]
    })


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
    doc_ref = projects_collection().document(project_id)
    doc = doc_ref.get()
    if not doc.exists:
        return jsonify({"error": "Projeto não encontrado."}), 404

    project = doc.to_dict()
    req_data = request.get_json()
    user_message = req_data.get('message', '').strip()

    if not user_message:
        return jsonify({"error": "Digite uma mensagem."}), 400

    # Ler histórico de mensagens da subcoleção
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

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message}
    ]

    try:
        parsed, usage = call_ai(messages)
    except Exception as e:
        return jsonify({"error": f"Erro ao processar: {str(e)}"}), 500

    req_tokens, req_cost = get_tokens_and_cost(usage)

    # Tracking diário
    track_daily_usage(req_tokens, req_cost)

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

    # Salvar mensagens na subcoleção
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

    # Retornar conversa atualizada
    conversation_list.append({"role": "user", "content": user_message})
    conversation_list.append({"role": "assistant", "content": assistant_msg})

    daily = get_daily_usage()

    return jsonify({
        "folder_structure": new_structure,
        "updated_files": updated_files,
        "deleted_files": deleted_files,
        "files": current_files,
        "conversation": conversation_list,
        "assistant_msg": assistant_msg,
        "req_tokens": req_tokens,
        "req_cost": req_cost,
        "tokens_used": tokens_used,
        "cost_used": total_cost,
        "daily_tokens": daily["tokens"],
        "daily_cost": daily["cost"]
    })


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
        file_paths = file_paths[:30]

    # Busca conteúdo de cada arquivo
    files_content = {}
    for path in file_paths:
        file_res = http.get(
            f'{GITHUB_API}/repos/{owner}/{repo}/contents/{path}',
            params={'ref': branch},
            headers=gh_headers()
        )
        if file_res.status_code == 200:
            try:
                content = base64.b64decode(file_res.json()['content']).decode('utf-8', errors='replace')
                files_content[path] = content
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
        return jsonify({"error": f"Erro ao processar com IA: {str(e)}"}), 500

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


# ===============================
# Inicialização
# ===============================
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=8000)
