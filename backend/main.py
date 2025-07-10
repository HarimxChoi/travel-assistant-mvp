# --- 1. Import Dependencies ---
from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, ValidationError
import uvicorn
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.sqlite import SqliteSaver 

# Import the graph builder *object* itself, not the compiled graph
from agent_graph import build_graph 

# --- 2. Initialize FastAPI App ---
app = FastAPI(title="Ascend Travel AI Assistant API (Pure Sync)")

# --- 3. Configure CORS ---
origins = [
           "http://localhost:3000",
           "https://uninterested-shrew-bowhouse-8870781b.koyeb.app"
           ]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# --- 4. Define Data Models (Pydantic V2) ---
class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000, description="User's query message.") 
    thread_id: str = Field(min_length=5, max_length=50, description="Unique identifier for the conversation thread.") # 길이 제한 추가

class ChatResponse(BaseModel):
    reply: str
    structured_data: dict
    thread_id: str

# --- 5. Global State: Compile Graph on Module Load  ---
agent_graph = build_graph()
print("AI Agent Graph compiled with default InMemorySaver.")

# --- 6. API Endpoints (All Synchronous) ---
@app.get("/", tags=["Status"])
def root():
    return {"status": "ok"}

def validate_chat_request(request: ChatRequest):
    """Dependency to validate incoming chat requests."""
    if not request.thread_id.startswith("session_"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid thread_id format. Must start with 'session_'.",
        )
    print(f"Validation successful for thread_id: {request.thread_id}")
    return request

@app.post("/chat", response_model=ChatResponse, tags=["AI Agent"])
def chat_with_agent(request: ChatRequest):
    """
    Main endpoint to process a user's message.
    It now compiles the graph dynamically for each request using a safe context.
    """
    try:
        thread_config = {"configurable": {"thread_id": request.thread_id}}
        graph_input = {"messages": [HumanMessage(content=request.message)]}
        
        print(f"Invoking graph for thread_id: {request.thread_id}")
        
        final_state = agent_graph.invoke(graph_input, thread_config)
        
        print("Graph invocation finished.")
        print(f"Final State: {final_state}")

        if not final_state or 'messages' not in final_state:
            raise HTTPException(status_code=500, detail="Agent did not produce a valid final state.")

        last_message = final_state['messages'][-1]
        reply_content = str(last_message.content) if last_message.content else ""
        structured_data = final_state.get('structured_data', {})
        
        return ChatResponse(
            reply=reply_content,
            structured_data=structured_data,
            thread_id=request.thread_id
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"An internal error occurred: {str(e)}")

# --- 7. Local Development Runner ---
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8008)