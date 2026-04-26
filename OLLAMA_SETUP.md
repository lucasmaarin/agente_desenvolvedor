# Usando IA alternativa na aplicação (Groq ou Ollama)

A aplicação suporta dois modos de IA, escolhido pela variável `AI_PROVIDER` no `.env`:

| `AI_PROVIDER` | Descrição |
|---|---|
| `openai` | Usa a API da OpenAI (padrão) |
| `local` | Usa Groq, Ollama ou qualquer API compatível com OpenAI |

---

## Opção 1 — Groq (recomendado para nuvem)

Groq oferece Llama 3.1 70B **gratuitamente**, com velocidade muito alta.

### 1. Criar conta e obter a chave

Acesse **[console.groq.com](https://console.groq.com)**, crie uma conta gratuita e gere uma API Key em **API Keys**.

### 2. Configurar o `.env`

```
AI_PROVIDER=local
LOCAL_AI_URL=https://api.groq.com/openai/v1
LOCAL_AI_KEY=sua_chave_groq_aqui
LOCAL_AI_MODEL=llama-3.3-70b-versatile
```

### 3. Reiniciar a aplicação

```bash
python main.py
```

### Modelos disponíveis no Groq

| Modelo | Melhor para |
|---|---|
| `llama-3.3-70b-versatile` | Melhor qualidade geral (recomendado) |
| `llama-3.1-8b-instant` | Mais rápido, respostas simples |
| `deepseek-r1-distill-llama-70b` | Raciocínio e código complexo |
| `gemma2-9b-it` | Leve e rápido |

---

## Opção 2 — Ollama (local, sem internet)

Ollama roda o modelo diretamente na sua máquina. Não precisa de chave nem de internet.

### 1. Instalar o Ollama

Acesse **[ollama.com](https://ollama.com)** e baixe o instalador para Windows. Após instalar, o Ollama roda automaticamente na bandeja do sistema.

### 2. Baixar o modelo

```bash
ollama pull qwen2.5-coder:7b
```

Isso baixa ~4.7 GB. Para verificar:

```bash
ollama list
```

### 3. Verificar se o servidor está rodando

```bash
curl http://localhost:11434/api/tags
```

### 4. Configurar o `.env`

```
AI_PROVIDER=local
LOCAL_AI_URL=http://localhost:11434/v1
LOCAL_AI_KEY=ollama
LOCAL_AI_MODEL=qwen2.5-coder:7b
```

### 5. Testar o modelo direto no terminal

```bash
ollama run qwen2.5-coder:7b
```

---

## Comparativo

| | Groq | Ollama | OpenAI |
|---|---|---|---|
| Custo | Grátis (com limites) | Grátis | Pago |
| Velocidade | Muito rápida | Lenta sem GPU | Rápida |
| Internet | Necessária | Não precisa | Necessária |
| Qualidade | Alta (70B) | Boa (7B) | Alta |
| Privacidade | Dados vão para Groq | 100% local | Dados vão para OpenAI |

---

## Problemas comuns

| Problema | Solução |
|---|---|
| `401 Unauthorized` no Groq | Verifique se `LOCAL_AI_KEY` está correto no `.env` |
| `Connection refused` no Ollama | Rode `ollama serve` no terminal ou abra pelo ícone na bandeja |
| Resposta lenta no Ollama | Normal em CPU — considere usar Groq |
| JSON inválido | Tente um modelo maior (ex: `llama-3.3-70b-versatile` no Groq) |
