import os
from dotenv import load_dotenv
from langgraph.graph import StateGraph, END
from typing import TypedDict, Annotated, List, Optional, Dict
import operator
# [FIX] Pydantic V1 Deprecation 경고를 해결하기 위해 직접 Pydantic에서 가져옵니다.
from pydantic import BaseModel, Field 
from langchain_core.messages import AnyMessage, HumanMessage, AIMessage, ToolMessage
from langchain_core.tools import tool
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.checkpoint.memory import InMemorySaver
import json
from datetime import datetime
from amadeus import Client, ResponseError
import asyncio

# --- 1. Load Environment Variables & Initialize Clients ---
load_dotenv(dotenv_path=os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
AMADEUS_API_KEY = os.getenv("AMADEUS_API_KEY")
AMADEUS_API_SECRET = os.getenv("AMADEUS_API_SECRET")

if not all([GOOGLE_API_KEY, AMADEUS_API_KEY, AMADEUS_API_SECRET]):
    raise ValueError("One or more required API keys are missing.")

llm = ChatGoogleGenerativeAI(model="gemini-1.5-flash", temperature=0, google_api_key=GOOGLE_API_KEY)
amadeus = None
try:
    amadeus = Client(client_id=AMADEUS_API_KEY, client_secret=AMADEUS_API_SECRET)
    print("Amadeus Client initialized successfully.")
except Exception as e:
    print(f"Failed to initialize Amadeus Client: {e}")

# --- 2. Pydantic Models for Structured IO ---
class FlightOption(BaseModel):
    airline: str = Field(description="항공사 이름")
    price: str = Field(description="총 비행 비용")
    departure_time: str = Field(description="출발 시간 (YYYY-MM-DDTHH:MM:SS)")
    arrival_time: str = Field(description="도착 시간 (YYYY-MM-DDTHH:MM:SS)")

class HotelOption(BaseModel):
    name: str = Field(description="호텔 이름")
    price_per_night: str = Field(description="1박당 가격")
    rating: int = Field(description="호텔 만족도 점수 (0-100)")
    
class ActivityOption(BaseModel):
    name: str = Field(description="액티비티 이름")
    description: str = Field(description="액티비티에 대한 간단한 설명")
    price: str = Field(description="액티비티 가격")

# --- 3. Specialist Tools ---

# --- Flight Specialist ---
class FlightSearchArgs(BaseModel):
    originLocationCode: str = Field(description="The IATA code of the departure city.")
    destinationLocationCode: str = Field(description="The IATA code of the arrival city.")
    departureDate: str = Field(description="The departure date in YYYY-MM-DD format.")
    returnDate: Optional[str] = Field(description="The return date in YYYY-MM-DD format, if applicable.") 
    adults: int = Field(description="The number of adult passengers.", default=1)
    currencyCode: str = Field(description="The preferred currency for the flight prices, e.g., USD.", default="USD") 

@tool(args_schema=FlightSearchArgs)
def search_flights(originLocationCode: str, destinationLocationCode: str, departureDate: str, returnDate: Optional[str] = None, adults: int = 1, currencyCode: str = "USD") -> List[FlightOption]:
    """항공편을 검색합니다. 왕복일 경우 returnDate도 포함됩니다.""" # [FIX] 필수 Docstring 추가
    print(f"--- FLIGHT SPECIALIST: Searching flights for {originLocationCode} -> {destinationLocationCode} ---")
    if not amadeus: return [FlightOption(airline="Error", price="N/A", departure_time="N/A", arrival_time="Amadeus client not available.")]
    try:
        search_params = {
            'originLocationCode': originLocationCode,
            'destinationLocationCode': destinationLocationCode,
            'departureDate': departureDate,
            'adults': adults,
            'nonStop': 'false', 
            'currencyCode': currencyCode,
            'max': 3
        }
        if returnDate:
            search_params['returnDate'] = returnDate

        response = amadeus.shopping.flight_offers_search.get(**search_params)
        
        if not response.data: return []
        
        offers = []
        carriers = response.result.get('dictionaries', {}).get('carriers', {})
        for offer in response.data:
            airline_code = offer['itineraries'][0]['segments'][0]['carrierCode']
            offers.append(
                FlightOption(
                    airline=carriers.get(airline_code, airline_code),
                    price=f"{offer['price']['total']} {offer['price']['currency']}",
                    departure_time=offer['itineraries'][0]['segments'][0]['departure']['at'],
                    arrival_time=offer['itineraries'][-1]['segments'][-1]['arrival']['at']
                )
            )
        return offers
    except ResponseError as error:
        return [FlightOption(airline="Error", price="N/A", departure_time="N/A", arrival_time=str(error))]

# --- Activity Specialist ---
async def _get_city_geocode(city_name: str) -> Optional[Dict]:
    """(Helper) 도시 이름으로 좌표를 비동기적으로 검색합니다."""
    # ... (코드는 변경 없음)
    if not amadeus: return None
    try:
        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(
            None, 
            lambda: amadeus.reference_data.locations.get(keyword=city_name, subType='CITY')
        )
        if response.data:
            return response.data[0]['geoCode']
    except ResponseError as error:
        print(f"Error getting geocode for {city_name}: {error}")
    return None

class ActivitySearchArgs(BaseModel):
    city_name: str = Field(description="액티비티를 검색할 도시 이름 (예: 'Paris', 'London')")

@tool(args_schema=ActivitySearchArgs)
async def search_activities_by_city(city_name: str) -> List[ActivityOption]:
    """도시 이름으로 주변의 인기 액티비티를 검색합니다."""
    # ... (코드는 변경 없음)
    print(f"--- ACTIVITY SPECIALIST: Searching activities for {city_name} ---")
    geo_code = await _get_city_geocode(city_name)
    if not geo_code:
        return [ActivityOption(name="Error", description=f"Could not find coordinates for {city_name}", price="N/A")]
    
    try:
        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(
            None,
            lambda: amadeus.shopping.activities.get(latitude=geo_code['latitude'], longitude=geo_code['longitude'], radius=15)
        )
        return [ActivityOption(name=act['name'], description=act.get('shortDescription', 'N/A'), price=f"{act['price']['amount']} {act['price']['currencyCode']}") for act in response.data]
    except ResponseError as error:
        return [ActivityOption(name="Error", description=str(error), price="N/A")]

# --- Hotel Specialist ---
async def _get_hotel_details(hotel_id: str, check_in_date: str) -> Dict:
    """(Helper) 특정 호텔의 가격과 평점을 비동기적으로 가져옵니다."""
    # ... (코드는 변경 없음)
    if not amadeus: return {"id": hotel_id, "available": False}
    try:
        loop = asyncio.get_running_loop()
        offer_task = loop.run_in_executor(None, lambda: amadeus.shopping.hotel_offers_by_hotel.get(hotelId=hotel_id, checkInDate=check_in_date))
        sentiment_task = loop.run_in_executor(None, lambda: amadeus.e_reputation.hotel_sentiments.get(hotelIds=hotel_id))
        
        offer_response, sentiment_response = await asyncio.gather(offer_task, sentiment_task)
        
        if offer_response.data and offer_response.data.get('offers'):
            return {
                "name": offer_response.data['hotel']['name'],
                "price": float(offer_response.data['offers'][0]['price']['total']),
                "rating": sentiment_response.data[0]['overallRating'] if sentiment_response.data else 0,
                "id": hotel_id,
                "available": True
            }
    except Exception:
        pass 
    return {"id": hotel_id, "available": False}

class HotelRecommendArgs(BaseModel):
    city_code: str = Field(description="호텔을 검색할 도시의 IATA 코드 (예: 'PAR', 'LON')")
    check_in_date: str = Field(description="체크인 날짜 (YYYY-MM-DD)")

@tool(args_schema=HotelRecommendArgs)
async def recommend_top_hotels(city_code: str, check_in_date: str) -> Dict[str, HotelOption]:
    """도시의 예약 가능한 호텔 중, 가격대별로 만족도가 가장 높은 호텔을 추천합니다."""
    # ... (코드는 변경 없음)
    print(f"--- HOTEL SPECIALIST: Finding best hotels in {city_code} ---")
    if not amadeus: return {"error": "Amadeus client not available."}
    try:
        loop = asyncio.get_running_loop()
        list_response = await loop.run_in_executor(None, lambda: amadeus.reference_data.locations.hotels.by_city.get(cityCode=city_code, ratings="4,5"))
        hotel_ids = [hotel['hotelId'] for hotel in list_response.data[:10]]

        details_tasks = [_get_hotel_details(hid, check_in_date) for hid in hotel_ids]
        hotel_details = await asyncio.gather(*details_tasks)
        
        available_hotels = [h for h in hotel_details if h.get('available') and h.get('rating')]
        if not available_hotels: return {"error": "추천할 만한 호텔을 찾지 못했습니다."}

        price_tiers = {"value_for_money": [], "premium": [], "luxury": []}
        for h in available_hotels:
            if h['price'] < 200: price_tiers["value_for_money"].append(h)
            elif h['price'] <= 400: price_tiers["premium"].append(h)
            else: price_tiers["luxury"].append(h)
        
        recommendations = {}
        for tier, hotels in price_tiers.items():
            if hotels:
                best_hotel = max(hotels, key=lambda x: x['rating'])
                recommendations[tier] = HotelOption(name=best_hotel['name'], price_per_night=f"€{best_hotel['price']}", rating=best_hotel['rating'])
        return recommendations
    except ResponseError as error:
        return {"error": str(error)}

# --- 4. Graph Setup ---
tools = [search_flights, recommend_top_hotels, search_activities_by_city]
tool_llm = llm.bind_tools(tools)

class TravelAgentState(TypedDict):
    messages: Annotated[List[AnyMessage], operator.add]
    form_to_display: Optional[str] = None 

def should_call_tool(state: TravelAgentState):
    """LLM의 응답을 분석하여 다음 행동을 결정하고, 필요 시 폼 트리거를 설정합니다.""" # [FIX] Docstring 추가
    last_message = state['messages'][-1]
    if hasattr(last_message, 'tool_calls') and last_message.tool_calls:
        state['form_to_display'] = "contact_info" 
        return "tool_executor"
    state['form_to_display'] = None
    return END

# [FIX] 중복된 함수 정의 제거
# def should_call_tool(state: TravelAgentState):
#     last_message = state['messages'][-1]
#     return "tool_executor" if hasattr(last_message, 'tool_calls') and last_message.tool_calls else END

async def call_model_node(state: TravelAgentState):
    """마스터 에이전트 노드: 요청을 분해하고 도구를 동시 호출합니다.""" # [FIX] Docstring 추가
    print("--- MASTER AGENT: Decomposing request and dispatching tools ---")
    prompt = f"""You are 'Astra', a world-class AI travel assistant and Master Agent. Your personality is friendly, professional, and incredibly helpful. You use emojis generously to make information clear and engaging.

**System Preamble:**
*   **Today's Date:** `{datetime.now().strftime('%Y-%m-%d')}`. Use this for any relative date calculations.
*   **Currency Preference:** The user's preferred currency is **USD**. All tool calls involving prices must request USD.
*   **[NEW] Date Range Comprehension:** You MUST analyze user queries for date ranges. "Next mon to fri" means you must calculate both the `departureDate` and `returnDate`. "For 4 days" means the `returnDate` is 4 days after the `departureDate`.

**Your Master Agent Protocol (Decompose, Dispatch, Synthesize):**
1.  **Decompose & Dispatch:** When a user asks a complex question, your first job is to break it down and call **all necessary tools at once**. This includes inferring all required parameters like `returnDate`.
2.  **Synthesize Results:** After the tools provide their results, your second job is to combine all the information into a **single, cohesive, and friendly response**.

**Specialist Tool Guide:**
*   `search_flights`: For flight inquiries. It requires `departureDate` and optionally a `returnDate`. Always set `currencyCode` to 'USD'.
*   `recommend_top_hotels`: Recommends hotels.
*   `search_activities_by_city`: Finds fun things to do.

**Example of a perfect interaction:**
*User*: "I wanna go to Jeju from next Mon to Fri, 2 people, budget $2000, from Seoul."
*Astra's Internal Thought*: "Okay, 'next Mon to Fri' means I need to calculate both departure and return dates. The user's budget is in USD. I need to call `search_flights(..., departureDate='YYYY-MM-DD', returnDate='YYYY-MM-DD', currencyCode='USD')` and `recommend_top_hotels(...)`."
*Astra's Final Response (after tools return)*:
    "Of course! Here are some great options for your trip to Jeju Island! 🏝️

    ✈️ **Flights from Seoul to Jeju (Round Trip):**
    *   **Korean Air:** $120 USD, ...

    🏨 **Hotel Recommendations:**
    *   ...

    Your total budget is $2000. These options fit well within your budget. Let me know if you'd like to proceed!"

**Conversation History:**
{state['messages']}

Now, analyze the user's latest message and take the next logical action based on your protocol.
"""
    response = await tool_llm.ainvoke(prompt)
    return {"messages": [response]}

async def tool_node(state: TravelAgentState):
    """전문가 도구들을 병렬로 실행하는 노드입니다.""" # [FIX] Docstring 추가
    print("--- TOOL EXECUTOR: Running specialist tools ---")
    tool_calls = state['messages'][-1].tool_calls
    
    tasks = []
    for tool_call in tool_calls:
        tool_to_call = {t.name: t for t in tools}[tool_call['name']]
        # 비동기 함수와 동기 함수를 모두 처리하기 위한 수정
        if asyncio.iscoroutinefunction(tool_to_call.func):
            task = asyncio.create_task(tool_to_call.ainvoke(tool_call['args']))
        else:
            loop = asyncio.get_running_loop()
            task = loop.run_in_executor(None, lambda: tool_to_call.invoke(tool_call['args']))
        tasks.append((task, tool_call))

    results = await asyncio.gather(*(t for t, _ in tasks))
    
    tool_messages = []
    for (result, (_, tool_call)) in zip(results, tasks):
        tool_messages.append(ToolMessage(content=str(result), name=tool_call['name'], tool_call_id=tool_call['id']))

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

async def run_test():
    graph = build_graph()
    thread_id = "test-thread-1"
    config = {"configurable": {"thread_id": thread_id}}
    
    async for event in graph.astream_events(
        {"messages": [HumanMessage(content="Find me a flight from ICN to CDG on 2024-12-20, and recommend some good hotels and activities in Paris.")]},
        config=config,
        version="v1"
    ):
        kind = event["event"]
        if kind == "on_chat_model_stream":
            content = event["data"]["chunk"].content
            if content:
                print(content, end="")
        elif kind == "on_tool_end":
            print(f"\n--- Tool {event['name']} End ---")
            print(f"Output: {event['data']['output']}")
    
if __name__ == '__main__':
    asyncio.run(run_test())