from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import uvicorn
from langchain_core.messages import HumanMessage
import uuid
from .agent_graph import build_graph
import asyncio

# --- App & State Initialization ---
app = FastAPI(title="Ascend Travel AI Assistant API (Async)")
agent_graph = build_graph()
jobs = {} # In-memory job store. Use Redis for production.

# --- CORS Configuration ---
origins = [
    "http://localhost:3000",
    "https://uninterested-shrew-bowhouse-8870781b.koyeb.app"
]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# --- Pydantic Models ---
class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    thread_id: str = Field(min_length=5)

class TaskResponse(BaseModel):
    task_id: str

class StatusResponse(BaseModel):
    status: str
    result: dict | None = None

# --- Background Task Function ---
async def run_agent_in_background(task_id: str, thread_id: str, message: str):
    print(f"--- BG Task {task_id} Started ---")
    try:
        config = {"configurable": {"thread_id": thread_id}}
        # Use the asynchronous invoke method
        final_state = await agent_graph.ainvoke({"messages": [HumanMessage(content=message)]}, config)
        
        last_message = final_state['messages'][-1]
        reply = str(last_message.content) if last_message.content else "I've processed the information."
        
        jobs[task_id] = {"status": "completed", "result": {"reply": reply}}
        print(f"--- BG Task {task_id} Completed ---")
    except Exception as e:
        import traceback
        traceback.print_exc()
        jobs[task_id] = {"status": "failed", "result": {"error": str(e)}}
        print(f"--- BG Task {task_id} Failed ---")

# --- API Endpoints ---
@app.get("/", tags=["Status"])
def root():
    return {"status": "ok", "architecture": "async"}

@app.post("/chat", response_model=TaskResponse, tags=["AI Agent"])
async def start_chat_task(request: ChatRequest, background_tasks: BackgroundTasks):
    task_id = str(uuid.uuid4())
    jobs[task_id] = {"status": "running"}
    background_tasks.add_task(run_agent_in_background, task_id, request.thread_id, request.message)
    return TaskResponse(task_id=task_id)

@app.get("/chat/status/{task_id}", response_model=StatusResponse, tags=["AI Agent"])
async def get_task_status(task_id: str):
    job = jobs.get(task_id)
    if not job:
        raise HTTPException(status_code=404, detail="Task not found")
    return StatusResponse(**job)

""" # --- Local Runner ---
if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8008, reload=True) """