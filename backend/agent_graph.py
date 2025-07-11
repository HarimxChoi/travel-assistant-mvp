import os
from dotenv import load_dotenv
from langgraph.graph import StateGraph, END
from typing import TypedDict, Annotated, List, Optional
import operator
from pydantic import BaseModel, Field
from langchain_core.messages import AnyMessage, HumanMessage, AIMessage, ToolMessage
from langchain_core.tools import tool
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.checkpoint.memory import InMemorySaver
import json
from datetime import datetime
from amadeus import Client, ResponseError
from tavily import TavilyClient

# --- 1. Load Environment Variables & Initialize Clients ---
load_dotenv(dotenv_path=os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
AMADEUS_API_KEY = os.getenv("AMADEUS_API_KEY")
AMADEUS_API_SECRET = os.getenv("AMADEUS_API_SECRET")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")

if not all([GOOGLE_API_KEY, AMADEUS_API_KEY, AMADEUS_API_SECRET, TAVILY_API_KEY]):
    raise ValueError("One or more required API keys are missing.")

llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", google_api_key=GOOGLE_API_KEY)
tavily_client = TavilyClient(api_key=TAVILY_API_KEY)
amadeus = None
try:
    amadeus = Client(client_id=AMADEUS_API_KEY, client_secret=AMADEUS_API_SECRET)
    print("Amadeus and Tavily Clients initialized successfully.")
except Exception as e:
    print(f"Failed to initialize Amadeus Client: {e}")

# --- 2. Define Tools ---

# Amadeus Tool for Flights
class FlightSearchArgs(BaseModel):
    originLocationCode: str = Field(description="The IATA code of the departure city.")
    destinationLocationCode: str = Field(description="The IATA code of the arrival city.")
    departureDate: str = Field(description="The departure date in YYYY-MM-DD format.")
    returnDate: Optional[str] = Field(description="The return date for round-trip flights.")
    adults: int = Field(description="The number of adult passengers.", default=1)

@tool(args_schema=FlightSearchArgs)
def search_flights(originLocationCode: str, destinationLocationCode: str, departureDate: str, returnDate: Optional[str] = None, adults: int = 1) -> str:
    """Use this tool to search for specific flight offers. This is for flights ONLY."""
    if not amadeus: return "Amadeus API client is not available."
    print(f"--- TOOL: Searching flights with Amadeus: {originLocationCode} -> {destinationLocationCode} ---")
    
    try:
        params = {
            'originLocationCode': originLocationCode,
            'destinationLocationCode': destinationLocationCode,
            'departureDate': departureDate,
            'adults': adults,
            'nonStop': 'false',
            'max': 3, 
            'currencyCode': 'USD'
        }
        if returnDate:
            params['returnDate'] = returnDate

        response = amadeus.shopping.flight_offers_search.get(**params)
        
        if not response.data:
            return "No flight offers found for the given criteria. Please inform the user."

        simplified_offers = []
        carriers = response.result.get('dictionaries', {}).get('carriers', {})

        for offer in response.data:
            itineraries_details = []
            for itinerary in offer['itineraries']:
                segments_details = []
                for segment in itinerary['segments']:
                    segments_details.append({
                        "departure_airport": segment['departure']['iataCode'],
                        "departure_time": segment['departure']['at'],
                        "arrival_airport": segment['arrival']['iataCode'],
                        "arrival_time": segment['arrival']['at'],
                        "flight_number": f"{segment['carrierCode']} {segment['number']}",
                        "duration": segment['duration']
                    })
                itineraries_details.append({"segments": segments_details})

            airline_code = offer['itineraries'][0]['segments'][0]['carrierCode']
            airline_name = carriers.get(airline_code, airline_code)
            
            simplified_offers.append({
                "airline": airline_name,
                "total_price": f"{offer['price']['total']} USD",
                "itineraries": itineraries_details
            })
        
        return json.dumps(simplified_offers)
    except ResponseError as error:
        return f"Amadeus API Error: {error.description}"
    except Exception as e:
        return f"An unexpected error occurred: {e}"


# Tavily Tool for General Info
class WebSearchArgs(BaseModel):
    query: str = Field(description="A specific, detailed search query for the web.")

@tool(args_schema=WebSearchArgs)
def general_web_search(query: str) -> str:
    """Use this tool to search the internet for general travel information, such as local events, weather, restaurant recommendations, or other questions that are NOT about specific flight prices."""
    print(f"--- TOOL: Searching web with Tavily for: {query} ---")
    try:
        response = tavily_client.search(query=query, search_depth="basic", max_results=3)
        return json.dumps(response['results'])
    except Exception as e:
        return f"An error occurred during web search: {e}"
    
tools = [search_flights, general_web_search]
tool_llm = llm.bind_tools(tools)

# --- 3. Define State and Graph ---
class TravelAgentState(TypedDict):
    messages: Annotated[List[AnyMessage], operator.add]

def should_call_tool(state: TravelAgentState):
    last_message = state['messages'][-1]
    if hasattr(last_message, 'tool_calls') and last_message.tool_calls:
        return "tool_executor"
    return END

def call_model_node(state: TravelAgentState):
    print("--- ROUTER ---")
    prompt = f"""You are 'Astra', a world-class AI travel assistant. Your personality is friendly, professional, and helpful. You use emojis to make information clear and engaging, but you don't over-saturate your messages.

**System Preamble:**
*   **Today's Date:** `{datetime.now().strftime('%Y-%m-%d')}`. Use this as a reference for all relative date calculations (e.g., "next Monday", "in 3 days").
*   **Primary Goal:** Your main job is to help users find flights. Secondary tasks include finding related travel information like local events.
*   **Formatting Rule:** Use emojis and ***newlines*** (`\n`) to structure your responses for clarity.

**Your 2-Step Response Protocol for Flights:**
1.  **Step 1 (Flight Info):** When a user asks for flights, your first response should ONLY contain the flight details. Use the `search_flights` tool. After presenting the flight options, ALWAYS end your message by promising to look for more information. (e.g., "I'm now checking for some interesting local events during your stay. I'll be right back!")
2.  **Step 2 (Enrichment Info):** The system will then automatically trigger a search for local events using the `general_web_search` tool. Your second response should present this information.

**Tool Guide:**
*   `search_flights`: Use for specific flight price and schedule inquiries. Requires origin, destination, and dates.
*   `general_web_search`: Use for all other informational queries (events, weather, activities).

**Example of a perfect Step 1 response:**

    I've found some flight options for you! 📄
    
    Here is your flight summary:
    ✈️ Itinerary: NYC to SFO
    
    Option 1: JetBlue
    💸 Price: $296.98 USD
    🛫 Departs: 2025-10-09 14:00 from JFK
    🛬 Arrives: 2025-10-09 17:30 at SFO
    
    I'm now checking for some interesting local events during your stay. I'll be right back! ✨

**Conversation History:**
{state['messages']}

Analyze the user's latest message, considering today's date, and determine the next logical action based on your protocol.
"""
    response = tool_llm.invoke(prompt)
    return {"messages": [response]}
    

def tool_node(state: TravelAgentState):
    print("--- EXECUTING TOOL ---")
    last_message = state['messages'][-1]
    tool_messages = []
    for tool_call in last_message.tool_calls:
        tool_to_call = {t.name: t for t in tools}[tool_call['name']]
        try:
            output = tool_to_call.invoke(tool_call['args'])
        except Exception as e:
            output = f"Error executing tool {tool_call['name']}: {e}"
        tool_messages.append(ToolMessage(content=str(output), name=tool_call['name'], tool_call_id=tool_call['id']))
    return {"messages": tool_messages}

def build_graph(checkpointer=None):
    if checkpointer is None:
        checkpointer = InMemorySaver()
    
    builder = StateGraph(TravelAgentState)
    builder.add_node("model", call_model_node) 
    builder.add_node("tool_executor", tool_node)
    
    builder.set_entry_point("model")
    
    builder.add_conditional_edges("model", should_call_tool)
    
    builder.add_edge("tool_executor", "model")
    
    return builder.compile(checkpointer=checkpointer)