from flask import Flask, render_template, request, jsonify
import os
import json
import re
import openai
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
# OpenAI
# ===============================
client = openai.OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

# ===============================
# Controle de custos
# ===============================
PRICE_PER_1000_TOKENS_USD = 0.002
USD_TO_BRL = 5.0

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
  "folder_structure": "updated full visual tree string"
}}

Rules:
- Return the COMPLETE content of each changed file, not diffs.
- If no files were deleted, use an empty array.
- Always include the updated folder_structure reflecting any structural changes.
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
            model="o4-mini",
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
        "python": "Python"
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

    tokens_used = usage.total_tokens
    cost = round((tokens_used / 1000) * PRICE_PER_1000_TOKENS_USD * USD_TO_BRL, 4)

    # Tracking diário
    track_daily_usage(tokens_used, cost)

    project_name = parsed.get("project_name", "meu-projeto")
    num_files = len(parsed.get("files", {}))
    assistant_msg = f"Projeto '{project_name}' criado com {num_files} arquivos usando {lang_label}."

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

    req_tokens = usage.total_tokens
    req_cost = round((req_tokens / 1000) * PRICE_PER_1000_TOKENS_USD * USD_TO_BRL, 4)

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

    assistant_msg = f"Atualizado {len(updated_files)} arquivo(s)."
    if deleted_files:
        assistant_msg += f" Removido {len(deleted_files)} arquivo(s)."

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
        "python": "Python"
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
# Inicialização
# ===============================
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=8000)
