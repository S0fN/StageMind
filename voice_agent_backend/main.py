from fastapi import FastAPI, Body, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Dict, Any
import json
import asyncio
from modules.record_audio import record_audio_chunk
from modules.speech_to_text import transcribe_audio
from modules.handles_conversation import handle_conversation
from modules.evaluation import send_to_perplexity
from fastapi.responses import JSONResponse

# Initialize FastAPI app
app = FastAPI()

# Add CORS middleware to allow requests from the frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3001"],  # Explicitly allow your frontend origin
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],  # Explicitly list allowed methods
    allow_headers=["Content-Type", "Authorization", "Content-Length", "X-Requested-With"],  # Common headers
)

# Define request model
class ChatRequest(BaseModel):
    scenario: str
    AGENTS: List[Dict[str, Any]]
    knowledge: str

# WebSocket endpoint for real-time chat
@app.websocket("/ws/chat")
async def websocket_chat_endpoint(websocket: WebSocket):
    await websocket.accept()
    
    try:
        # Receive initial configuration
        config_data = await websocket.receive_text()
        config = json.loads(config_data)
        
        scenario = config.get("scenario", "")
        AGENTS = config.get("AGENTS", [])
        knowledge = config.get("knowledge", "")
        
        # Initialize conversation context
        routing_prompt = "You're a router.:\n"
        for agent in AGENTS:
            agent_name = agent["name"]
            agent_role = agent["role"]
            agent_description = agent["description"]
            routing_prompt += f"- {agent_name}({agent_role}): {agent_description}\n"

            agent["voice"] = "ash"
        
        conversation_log = []
        
        # Send confirmation that we're ready
        await websocket.send_json({"status": "ready", "message": "Voice agent is ready and listening"})
        
        # Start the conversation loop
        while True:
            # Check if there's a message from client (could be a hang-up signal)
            try:
                data = await asyncio.wait_for(websocket.receive_json(), timeout=0.1)
                if data.get("action") == "hang_up":
                    await websocket.send_json({"status": "ended", "message": "Call ended"})
                    break
            except asyncio.TimeoutError:
                # No message received, continue with recording
                pass
            
            # Record audio and process
            audio_path = record_audio_chunk(duration=5)
            user_input = transcribe_audio(audio_path)
            
            if user_input:
                # Send transcription to client
                await websocket.send_json({"status": "transcription", "text": user_input})
                
                # Add to conversation log
                conversation_log.append({"speaker": "User", "text": user_input})
                
                # Update routing prompt
                current_routing_prompt = routing_prompt + f"User said: {user_input}\nRespond with ONLY one name: {', '.join([a['name'] for a in AGENTS])}."
                
                # Process the conversation and get response
                await handle_conversation(AGENTS, user_input, scenario, knowledge, conversation_log, current_routing_prompt)
                
                # The response is handled inside handle_conversation which calls speak()
                # We can send a confirmation to the client
                await websocket.send_json({
                    "status": "processed",
                    "message": "Response processed"
                })
    
    except WebSocketDisconnect:
        print("Client disconnected")
    except Exception as e:
        print(f"Error in WebSocket: {str(e)}")
        await websocket.send_json({"status": "error", "message": str(e)})

# Endpoint to process speech and generate responses
@app.post("/api/chat")
async def process_speech_endpoint(request: ChatRequest = Body(...)):
    """
    Endpoint to process user speech and generate AI responses.
    
    Args:
        request: ChatRequest containing scenario, AGENTS, and knowledge
        
    Returns:
        Success message
    """
    
    # This endpoint is deprecated, clients should use the WebSocket endpoint
    return {"status": "deprecated", "message": "Please use the WebSocket endpoint /ws/chat for real-time communication"}

@app.get("/analyze")
def analyze(request:Request):
    data = request.json()
    scenario = data.get("scenario", "")
    agents = data.get("AGENTS", [])
    knowledge = data.get("knowledge", "")
        

    full_text = f"""
    scenario info:
    {scenario}

    Experts:
    {agents}

    Knowledge Base:
    {knowledge}

    Conversation:
    {}
    """

    result = send_to_perplexity(full_text)

    # Return result as JSON response
    if "error" in result:
        return JSONResponse(status_code=500, content=result)
    
    return JSONResponse(content=result)

# Run the FastAPI app with uvicorn when this file is executed directly
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)