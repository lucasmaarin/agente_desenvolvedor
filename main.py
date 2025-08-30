from flask import Flask, render_template, request, session
import os
import openai

app = Flask(__name__)
app.secret_key = "uma_chave_secreta"  # necessário para sessão

UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

client = openai.OpenAI(api_key="")

# Preço aproximado por 1.000 tokens para gpt-3.5-turbo
PRICE_PER_1000_TOKENS_USD = 0.002
USD_TO_BRL = 5.0
TOTAL_CREDIT_BRL = 50.0  # crédito total disponível (exemplo)

@app.route('/')
def home():
    # Inicializa sessão
    session.setdefault('tokens_used', 0)
    session.setdefault('cost_used', 0.0)
    return render_template('index.html', session_tokens=session['tokens_used'], 
                           session_cost=session['cost_used'], credit_remaining=TOTAL_CREDIT_BRL - session['cost_used'])

@app.route('/chat', methods=['POST'])
def chat():
    user_input = request.form.get('user_input', '').strip()
    uploaded_file = request.files.get('file')

    if uploaded_file and uploaded_file.filename != '':
        try:
            file_content = uploaded_file.read().decode('utf-8')
            user_input = file_content
        except Exception as e:
            return render_template('index.html', result=f"Erro ao ler o arquivo: {e}")

    if not user_input:
        return render_template('index.html', result="Digite algo ou envie um arquivo.",
                               session_tokens=session['tokens_used'], 
                               session_cost=session['cost_used'],
                               credit_remaining=TOTAL_CREDIT_BRL - session['cost_used'])

    try:
        prompt = f"Você é um especialista em React/JSX. Analise o seguinte código e explique, corrija erros ou sugira melhorias:\n\n{user_input}"

        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5
        )

        chat_response = response.choices[0].message.content

        # Atualiza tokens usados
        usage = response.usage
        session['tokens_used'] += usage.total_tokens
        session['cost_used'] += (usage.total_tokens / 1000) * PRICE_PER_1000_TOKENS_USD * USD_TO_BRL

    except Exception as e:
        chat_response = f"Erro ao chamar a OpenAI: {e}"

    return render_template('index.html', result=chat_response, user_input=user_input,
                           session_tokens=session['tokens_used'], 
                           session_cost=round(session['cost_used'], 4),
                           credit_remaining=round(TOTAL_CREDIT_BRL - session['cost_used'], 4))

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=8000)
