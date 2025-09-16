# ===============================
# Importações necessárias
# ===============================
from flask import Flask, render_template, request, session, jsonify
import os
import openai

# ===============================
# Configuração da aplicação Flask
# ===============================
app = Flask(__name__)

# 🔑 Chave secreta usada para manter dados na sessão (cookies criptografados)
app.secret_key = "chave Open Ai"

# ===============================
# Configuração de uploads
# ===============================
UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)  # cria a pasta se não existir
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# ===============================
# Cliente da OpenAI
# ===============================
client = openai.OpenAI(api_key=app.secret_key)

# ===============================
# Controle de custos
# ===============================
PRICE_PER_1000_TOKENS_USD = 0.002   # preço médio por 1000 tokens do modelo
USD_TO_BRL = 5.0                    # taxa de conversão dólar -> real
TOTAL_CREDIT_BRL = 50.0             # crédito total disponível em reais (exemplo)

# ===============================
# Rota inicial (renderiza HTML)
# ===============================
@app.route('/')
def home():
    # Garante que a sessão tenha valores iniciais
    session.setdefault('tokens_used', 0)
    session.setdefault('cost_used', 0.0)

    # Renderiza a página inicial
    return render_template(
        'index.html',
        session_tokens=session['tokens_used'],
        session_cost=session['cost_used'],
        credit_remaining=TOTAL_CREDIT_BRL - session['cost_used']
    )

# ===============================
# Rota de Chat (JSON)
# ===============================
@app.route('/chat', methods=['POST'])
def chat():
    user_input = request.form.get('user_input', '').strip()
    uploaded_file = request.files.get('file')

    # Caso o usuário envie um arquivo
    if uploaded_file and uploaded_file.filename != '':
        try:
            ext = os.path.splitext(uploaded_file.filename)[1].lower()
            if ext in [".js", ".ts", ".tsx", ".jsx", ".txt"]:
                file_content = uploaded_file.read().decode('utf-8', errors='ignore')
                user_input = f"{user_input}\n\nArquivo `{uploaded_file.filename}`:\n```\n{file_content}\n```"
            else:
                return jsonify({"error": f"Formato {ext} não suportado. Envie .js, .ts, .tsx, .jsx ou .txt"})
        except Exception as e:
            return jsonify({"error": f"Erro ao ler o arquivo: {e}"})

    # Caso não haja entrada de texto nem arquivo
    if not user_input:
        return jsonify({"error": "Digite instruções ou envie um arquivo."})

    # ===============================
    # Interação com a OpenAI
    # ===============================
    try:
        prompt = (
            "Você é um especialista em programação frontend, altamente habilidoso em React, Next.js, TSX, JSX, JS e TS.\n\n"
            "Sua tarefa é receber instruções (fora das crazes ``) e um bloco completo de código (dentro das crazes).\n\n"
            "⚡ Regras:\n"
            "1. O texto fora das crazes contém instruções do que precisa ser alterado no código.\n"
            "2. O texto entre crazes conterá o código completo da tela ou componente.\n"
            "3. O código deve ser retornado dentro de blocos markdown com sintaxe (ex: ```tsx, ```js, ```ts, ```jsx) para destacar como no VS Code.\n"
            "4. Sempre retorne a tela inteira modificada, nunca apenas trechos.\n"
            "5. Mantenha o código limpo, legível e consistente.\n"
            "6. Não adicione explicações fora do código na resposta final — apenas retorne o código atualizado junto com comentarios desntro dele, explicando a logica do codigo adicionado e o que precisaria instalar.\n\n"
            f"{user_input}"
        )

        response = client.chat.completions.create(
            model="o4-mini",
            messages=[{"role": "user", "content": prompt}]
        )
        chat_response = response.choices[0].message.content

        # Atualiza tokens/custos
        usage = response.usage
        session['tokens_used'] += usage.total_tokens
        session['cost_used'] += (
            (usage.total_tokens / 1000)
            * PRICE_PER_1000_TOKENS_USD
            * USD_TO_BRL
        )

        return jsonify({
            "result": chat_response,
            "tokens": session['tokens_used'],
            "cost": round(session['cost_used'], 4),
            "credit_remaining": round(TOTAL_CREDIT_BRL - session['cost_used'], 4)
        })

    except Exception as e:
        return jsonify({"error": f"Erro ao chamar a OpenAI: {e}"})


# ===============================
# Inicialização do servidor
# ===============================
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=8000)
