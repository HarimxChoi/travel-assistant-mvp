# --- 1. Import necessary libraries ---
import os
from dotenv import load_dotenv
from langgraph.graph import StateGraph, END
from typing import TypedDict, Annotated, List, Optional
import operator
from langchain_core.pydantic_v1 import BaseModel, Field
from langchain_core.messages import AnyMessage, HumanMessage, AIMessage, ToolMessage
from langchain_core.tools import tool
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.checkpoint.memory import InMemorySaver
from tavily import TavilyClient
import json
from datetime import datetime


# --- Load Environment Variables ---
load_dotenv(dotenv_path=os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
if not GOOGLE_API_KEY: raise ValueError("GOOGLE_API_KEY not found.")
print("Google API Key loaded successfully.")

TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
tavily_client = TavilyClient(api_key=TAVILY_API_KEY) if TAVILY_API_KEY else None
if tavily_client: print("Tavily Client initialized successfully.")





# --- 3. Define Tools ---
class FlightPriceArgs(BaseModel):
    destination: str = Field(description="The destination city for the flight search.")

@tool(args_schema=FlightPriceArgs)
def flight_price_search(destination: str) -> str:
    """Use this to get typical flight prices for a destination."""
    if not tavily_client: return "Search tool is not available."
    print(f"--- TOOL: Searching flight prices for {destination} with Tavily ---")
    query = f"typical round-trip flight prices to {destination}"
    response = tavily_client.search(query=query, search_depth="basic", max_results=3)
    return json.dumps(response['results'])

class LocalEventArgs(BaseModel):
    destination: str = Field(description="The destination city.")
    start_date: str = Field(description="The start date for the event search, in YYYY-MM-DD format.")

@tool(args_schema=LocalEventArgs)
def local_event_search(destination: str, start_date: str) -> str:
    """Use this to find local events and festivals at a destination around a specific date."""
    if not tavily_client: return "Search tool is not available."
    print(f"--- TOOL: Searching local events for {destination} around {start_date} with Tavily ---")
    query = f"events, festivals, and activities in {destination} around {start_date}"
    response = tavily_client.search(query=query, search_depth="advanced", max_results=3)
    return json.dumps(response['results'])

class UpdateTripInfoArgs(BaseModel):
    destination: Optional[str] = Field(description="The destination city.")
    start_date: Optional[str] = Field(description="The departure date in YYYY-MM-DD format.")
    end_date: Optional[str] = Field(description="The return date in YYYY-MM-DD format.")

@tool(args_schema=UpdateTripInfoArgs)
def get_trip_information(destination: str, start_date: str, end_date: str) -> str:
    """
    Use this FINAL tool to search for both flight prices and local events
    ONLY AFTER you have confirmed all three required pieces of information
    (destination, start_date, end_date) are stored in the state.
    """
    if not tavily_client: return "Search tool is not available."
    price_query = f"typical round-trip flight prices to {destination} from {start_date}"
    event_query = f"events and festivals in {destination} between {start_date} and {end_date}"
    price_results = tavily_client.search(query=price_query, max_results=2)
    event_results = tavily_client.search(query=event_query, max_results=3)
    combined = {"flight_info": price_results['results'], "local_events": event_results['results']}
    return json.dumps(combined)

# The final, definitive list of tools.
tools = [flight_price_search, local_event_search, get_trip_information]


# --- 4. Define LLM and State ---

class FinalHandoff(BaseModel):
    """The final structured data object for handoff to internal systems."""
    user_query: str = Field(description="The user's original, unmodified query.")
    inferred_destination: str = Field(description="The destination inferred from the conversation.")
    inferred_start_date: str = Field(description="The start date inferred and structured as YYYY-MM-DD.")
    inferred_end_date: str = Field(description="The end date inferred and structured as YYYY-MM-DD.")
    flight_price_info: List[dict] = Field(description="A list of dictionaries containing flight price information from the search tool.")
    local_event_info: List[dict] = Field(description="A list of dictionaries containing local event information from the search tool.")

class TravelAgentState(TypedDict):
    messages: Annotated[List[AnyMessage], operator.add]
    
    # --- These fields are CRUCIAL for the new tool_node to work ---
    destination: Optional[str]
    start_date: Optional[str]
    end_date: Optional[str]

    # This will hold the final structured output
    final_structured_data: Optional[FinalHandoff]


model_id = "gemini-2.5-flash"
llm = ChatGoogleGenerativeAI(model=model_id, google_api_key=GOOGLE_API_KEY)
# Bind the tools for the router
tool_llm = llm.bind_tools(tools)
# --- NEW: Create an LLM instance specifically for generating the final structured output ---
structured_llm = llm.with_structured_output(FinalHandoff)

# --- 4. Define Nodes (Using the standard .invoke() method) ---

# agent_graph.py

def call_router_node(state: TravelAgentState):
    """
    This is the MASTER router. It analyzes the conversation and decides the next action.
    It internally parses dates and decides whether to call tools or ask the user a question.
    """
    print("--- EXECUTING MASTER ROUTER NODE ---")
    today = datetime.now().strftime("%Y-%m-%d")

    # This is the new, all-in-one prompt that gives the LLM full reasoning capability.
    prompt = f"""
You are a master travel assistant. Your goal is to fill in the user's trip details (`destination`, `start_date`, `end_date`) by having a natural conversation.
there's no markdown available in this chatting. so just use emoji if you want.
**Today's Date is: {today}**

**Current Trip Information Stored in Memory:**
- Destination: {state.get('destination') or 'UNKNOWN'}
- Start Date: {state.get('start_date') or 'UNKNOWN'}
- End Date: {state.get('end_date') or 'UNKNOWN'}

**Available Tools:**
- `flight_price_search(destination)`
- `local_event_search(destination, start_date)`

**Your Logic Flow:**
1.  **Analyze the latest user message** in the context of the conversation history.
2.  **Extract new information** from the user's message.
3.  **If you found new information:** Your primary action is to call the `update_trip_information` tool to save it to memory. You can update multiple fields at once.
4.  **After updating, check if all three pieces of information are now known.** If they are, you should THEN call the `get_trip_information` tool as your final action.
5.  **If information is still missing:** Your only action is to ask the user a friendly, clarifying question.

**Conversation History:**
{state['messages']}

Based on this, decide on the single best next action.
"""
    
    response = tool_llm.invoke(prompt)
    return {"messages": [response]}


def tool_node(state: TravelAgentState):
    """
    This node executes tools AND updates the agent's internal state.
    It's the bridge between the LLM's decisions and the agent's memory.
    """
    print("--- EXECUTING TOOL NODE (with State Update) ---")
    last_message = state['messages'][-1]
    
    # This check is crucial, as the router might decide no tool is needed.
    if not hasattr(last_message, 'tool_calls') or not last_message.tool_calls:
        # If no tools are called, we can optionally add a message to indicate this.
        # For now, we just pass through.
        return {}
        
    tool_messages = []
    # Create a dictionary to hold the state updates for this turn.
    state_updates = {}

    for tool_call in last_message.tool_calls:
        tool_name = tool_call['name']
        args = tool_call['args']
        print(f"  > Executing tool: {tool_name} with args: {args}")
        
        # --- NEW: Special handling for the state update tool ---
        if tool_name == 'update_trip_information':
            # This tool is special. It doesn't call an external API.
            # Its only purpose is to update our state.
            print(f"    - Updating internal state with: {args}")
            for key, value in args.items():
                if value is not None: # Ensure we don't overwrite with None
                    state_updates[key] = value
            # The "output" of this tool is just a confirmation message.
            output = f"Successfully updated state with: {args}"
        else:
            # For all other tools (like search), execute them normally.
            tool_to_call = {t.name: t for t in tools}[tool_name]
            try:
                output = tool_to_call.invoke(args)
            except Exception as e:
                print(f"    ! Tool execution failed: {e}")
                output = f"Error executing tool {tool_name}: {e}"
        
        tool_messages.append(
            ToolMessage(content=str(output), name=tool_name, tool_call_id=tool_call['id'])
        )

    # After the loop, apply all collected updates to the state
    # This directly modifies the values in the TravelAgentState dictionary
    # for the next nodes in the graph to use.
    if state_updates:
        state.update(state_updates)
            
    return {"messages": tool_messages}

def final_response_node(state: TravelAgentState):
    """
    Node: Final Judge.
    This node synthesizes all information into two final outputs:
    1. A friendly natural language message for the user.
    2. A structured JSON object (FinalHandoff) for internal systems.
    """
    print("--- EXECUTING FINAL JUDGE NODE ---")
    
    # --- Part 1: Generate the structured JSON data ---
    structured_prompt = f"""
Based on the entire conversation history, extract all the necessary information and populate the `FinalHandoff` JSON object.

Conversation History:
{state['messages']}
"""
    # Call the LLM that is specifically bound to the FinalHandoff schema
    final_data_object = structured_llm.invoke(structured_prompt)

    # --- Part 2: Generate the natural language reply ---
    summary_prompt = f"""
You are a friendly travel assistant. Based on the following structured data, create a final, helpful summary for the user.
Do not just list the data; present it in an appealing, conversational way.

**Data to Summarize:**
{final_data_object.json(indent=2)}
"""
    # Use the standard LLM for text generation
    final_reply_message = llm.invoke(summary_prompt)

    # Return both the AI message and the structured data to the state
    return {
        "messages": [final_reply_message],
        "final_structured_data": final_data_object.dict() # Convert Pydantic model to dict
    }



# --- 6. Define the Graph and its Flow ---
def build_graph(checkpointer=None):
    """Assembles the final, robust agent graph."""
    if checkpointer is None:
        checkpointer = InMemorySaver()

    builder = StateGraph(TravelAgentState)

    builder.add_node("router", call_router_node)
    builder.add_node("tool_executor", tool_node)
    builder.add_node("final_responder", final_response_node) # Final summary node
    
    builder.set_entry_point("router")

    def decide_next_action(state: TravelAgentState):
        """This router checks if the LLM decided to call a tool or talk to the user."""
        last_message = state['messages'][-1]
        if hasattr(last_message, 'tool_calls') and last_message.tool_calls:
            return "tool_executor"
        else:
            # If the router asks a question, the turn ends.
            return END

    builder.add_conditional_edges("router", decide_next_action)
    
    # After executing tools, we generate a final summary for the user.
    builder.add_edge("tool_executor", "final_responder")
    builder.add_edge("final_responder", END)
    
    return builder.compile(checkpointer=checkpointer)