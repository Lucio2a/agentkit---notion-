import os
import base64
from typing import Optional, List
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import requests
import anthropic

app = FastAPI()

# Configuration
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID")

# Système de mémoire simple
conversation_history = []
uploaded_pdfs = {}

# Philosophie stoïque intégrée
SYSTEM_PROMPT = """Tu es un agent d'automation de vie inspiré par la philosophie stoïque de Marc Aurèle.

Principes que tu appliques :
- Discipline et action : tu agis concrètement, pas de procrastination
- Focus sur ce qui dépend de toi : tu te concentres sur les actions possibles
- Pragmatisme : solutions simples et efficaces
- Encouragement ferme : tu pousses l'utilisateur à l'action

Tu as accès à :
- Notion (gestion de tâches, projets, bases de données)
- Analyse de documents PDF
- Exécution de code Python pour analyses

Ton style :
- Direct et concis
- Encourage l'action immédiate
- Cite Marc Aurèle quand pertinent
- Zéro bullshit

Quand l'utilisateur te demande quelque chose, tu :
1. Confirmes que tu as compris
2. AGIS immédiatement (appel Notion, analyse, etc.)
3. Donnes le résultat
4. Proposes la prochaine action

Pas de questions inutiles, tu es là pour FAIRE."""


class Message(BaseModel):
    message: str
    action: Optional[str] = None
    notion_params: Optional[dict] = None


def call_claude(user_message: str, pdf_content: Optional[str] = None):
    """Appelle l'API Claude"""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    
    messages = []
    
    # Ajoute l'historique
    for msg in conversation_history[-10:]:  # Garde les 10 derniers messages
        messages.append(msg)
    
    # Ajoute le message actuel
    content = [{"type": "text", "text": user_message}]
    
    # Si PDF, l'ajoute
    if pdf_content:
        content.append({
            "type": "document",
            "source": {
                "type": "base64",
                "media_type": "application/pdf",
                "data": pdf_content
            }
        })
    
    messages.append({
        "role": "user",
        "content": content
    })
    
    # Appel API Claude
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4000,
        system=SYSTEM_PROMPT,
        messages=messages
    )
    
    assistant_message = response.content[0].text
    
    # Sauvegarde dans l'historique
    conversation_history.append({"role": "user", "content": user_message})
    conversation_history.append({"role": "assistant", "content": assistant_message})
    
    return assistant_message


def notion_action(action: str, params: dict):
    """Effectue une action Notion"""
    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json"
    }
    
    db_id = params.get("database_id") or NOTION_DATABASE_ID
    
    if action == "read":
        url = f"https://api.notion.com/v1/databases/{db_id}/query"
        response = requests.post(url, headers=headers, json={"page_size": params.get("limit", 10)})
        return response.json()
    
    elif action == "create":
        url = "https://api.notion.com/v1/pages"
        payload = {
            "parent": {"database_id": db_id},
            "properties": params.get("properties", {})
        }
        response = requests.post(url, headers=headers, json=payload)
        return response.json()
    
    elif action == "update":
        page_id = params.get("page_id")
        url = f"https://api.notion.com/v1/pages/{page_id}"
        payload = {"properties": params.get("properties", {})}
        response = requests.patch(url, headers=headers, json=payload)
        return response.json()
    
    return {"error": "Action non supportée"}


@app.get("/", response_class=HTMLResponse)
def interface():
    """Interface web simple"""
    return """
<!DOCTYPE html>
<html>
<head>
    <title>Agent Claude - Automation de Vie</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }
        .container {
            max-width: 800px;
            margin: 0 auto;
            background: white;
            border-radius: 20px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            overflow: hidden;
        }
        .header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 30px;
            text-align: center;
        }
        .header h1 { font-size: 28px; margin-bottom: 10px; }
        .header p { opacity: 0.9; font-size: 14px; }
        .chat {
            height: 500px;
            overflow-y: auto;
            padding: 20px;
            background: #f8f9fa;
        }
        .message {
            margin-bottom: 15px;
            padding: 15px;
            border-radius: 12px;
            max-width: 80%;
            animation: slideIn 0.3s ease;
        }
        @keyframes slideIn {
            from { opacity: 0; transform: translateY(10px); }
            to { opacity: 1; transform: translateY(0); }
        }
        .user { background: #667eea; color: white; margin-left: auto; }
        .assistant { background: white; border: 2px solid #e9ecef; }
        .input-area {
            padding: 20px;
            background: white;
            border-top: 2px solid #e9ecef;
        }
        .input-group {
            display: flex;
            gap: 10px;
        }
        input[type="text"] {
            flex: 1;
            padding: 15px;
            border: 2px solid #e9ecef;
            border-radius: 12px;
            font-size: 16px;
            outline: none;
            transition: border 0.3s;
        }
        input[type="text"]:focus {
            border-color: #667eea;
        }
        button {
            padding: 15px 30px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            border-radius: 12px;
            font-size: 16px;
            font-weight: bold;
            cursor: pointer;
            transition: transform 0.2s;
        }
        button:hover {
            transform: scale(1.05);
        }
        button:active {
            transform: scale(0.95);
        }
        .pdf-upload {
            margin-top: 10px;
            padding: 10px;
            background: #f8f9fa;
            border-radius: 8px;
        }
        .pdf-upload input[type="file"] {
            font-size: 14px;
        }
        .loading {
            display: none;
            text-align: center;
            padding: 20px;
            color: #667eea;
        }
        .commands {
            padding: 15px;
            background: #e3f2fd;
            margin: 10px 20px;
            border-radius: 8px;
            font-size: 14px;
        }
        .commands strong { display: block; margin-bottom: 5px; color: #1565c0; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🤖 Agent Claude</h1>
            <p>Ton assistant d'automation de vie - Inspiré par Marc Aurèle</p>
        </div>
        
        <div class="commands">
            <strong>Commandes rapides :</strong>
            • "Lis mes tâches Notion" • "Crée une tâche : [nom]" • "Analyse ce PDF" • "Aide-moi à organiser ma journée"
        </div>
        
        <div class="chat" id="chat"></div>
        
        <div class="loading" id="loading">⏳ L'agent réfléchit...</div>
        
        <div class="input-area">
            <div class="pdf-upload">
                📎 <input type="file" id="pdfFile" accept=".pdf" />
            </div>
            <div class="input-group">
                <input type="text" id="messageInput" placeholder="Dis-moi ce que tu veux automatiser..." />
                <button onclick="sendMessage()">Envoyer</button>
            </div>
        </div>
    </div>

    <script>
        const chat = document.getElementById('chat');
        const input = document.getElementById('messageInput');
        const loading = document.getElementById('loading');
        const pdfFile = document.getElementById('pdfFile');
        
        function addMessage(text, isUser) {
            const div = document.createElement('div');
            div.className = 'message ' + (isUser ? 'user' : 'assistant');
            div.textContent = text;
            chat.appendChild(div);
            chat.scrollTop = chat.scrollHeight;
        }
        
        async function sendMessage() {
            const message = input.value.trim();
            if (!message) return;
            
            addMessage(message, true);
            input.value = '';
            loading.style.display = 'block';
            
            const formData = new FormData();
            formData.append('message', message);
            
            if (pdfFile.files[0]) {
                formData.append('pdf', pdfFile.files[0]);
            }
            
            try {
                const response = await fetch('/chat', {
                    method: 'POST',
                    body: formData
                });
                const data = await response.json();
                addMessage(data.response, false);
            } catch (error) {
                addMessage('❌ Erreur : ' + error.message, false);
            }
            
            loading.style.display = 'none';
            pdfFile.value = '';
        }
        
        input.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') sendMessage();
        });
        
        // Message de bienvenue
        addMessage("Salut ! Je suis ton agent d'automation. Dis-moi ce que tu veux faire : gérer Notion, analyser un document, organiser ta journée... Je m'occupe du reste. 💪", false);
    </script>
</body>
</html>
    """


@app.post("/chat")
async def chat(
    message: str = Form(...),
    pdf: Optional[UploadFile] = File(None)
):
    """Endpoint de chat principal"""
    try:
        pdf_content = None
        
        # Traite le PDF si présent
        if pdf:
            pdf_bytes = await pdf.read()
            pdf_content = base64.b64encode(pdf_bytes).decode('utf-8')
            uploaded_pdfs[pdf.filename] = pdf_content
        
        # Détecte si c'est une action Notion
        if any(word in message.lower() for word in ["notion", "tâche", "task", "lis", "crée", "modifie"]):
            # Demande à Claude ce qu'il faut faire
            claude_response = call_claude(
                f"{message}\n\nSi tu dois interagir avec Notion, réponds EXACTEMENT au format JSON:\n{{'action': 'read|create|update', 'params': {{...}}}}\nSinon, réponds normalement."
            )
            
            # Essaie de parser une action Notion
            try:
                import json
                if "{" in claude_response and "}" in claude_response:
                    json_str = claude_response[claude_response.find("{"):claude_response.rfind("}")+1]
                    action_data = json.loads(json_str)
                    
                    if "action" in action_data:
                        notion_result = notion_action(action_data["action"], action_data.get("params", {}))
                        claude_response = call_claude(f"Voici le résultat de Notion : {notion_result}\n\nRésume ça de façon claire pour l'utilisateur.")
            except:
                pass
        else:
            # Conversation normale
            claude_response = call_claude(message, pdf_content)
        
        return {"response": claude_response}
    
    except Exception as e:
        return {"response": f"❌ Erreur : {str(e)}"}


@app.get("/health")
def health():
    """Check si l'agent est opérationnel"""
    return {
        "status": "✅ Agent opérationnel",
        "anthropic_key": "✅" if ANTHROPIC_API_KEY else "❌",
        "notion_token": "✅" if NOTION_TOKEN else "❌",
        "conversation_history": len(conversation_history)
    }


@app.post("/reset")
def reset():
    """Reset la conversation"""
    conversation_history.clear()
    uploaded_pdfs.clear()
    return {"status": "Conversation réinitialisée"}
