# test_agent.py (for Hybrid Tool Agent)

import uuid
import pprint
import traceback

# This will import the NEW, refactored version of your agent_graph.py
from agent_graph import build_graph
from langchain_core.messages import HumanMessage, AIMessage

# --- 1. Build the Agent Graph ---
# The new build_graph function returns a compiled, ready-to-use graph.
# The checkpointer (memory) is handled internally for simplicity.
agent_graph = build_graph()
print("--- Hybrid Agent Graph is ready for testing ---")

# --- 2. Define a Test Runner Function ---
def run_test_conversation(turns: list, thread_id: str):
    """
    Simulates a multi-turn conversation with the agent.
    'turns' should be a list of user query strings.
    """
    print(f"\n\n=======================================================")
    print(f"--- STARTING NEW TEST CONVERSATION ---")
    print(f"Thread ID: {thread_id}")
    print(f"=======================================================")

    # The config is set once for the entire conversation thread
    thread_config = {"configurable": {"thread_id": thread_id}}
    
    for i, query in enumerate(turns):
        print(f"\n--- Turn {i+1}: User Query ---")
        print(f"> \"{query}\"")
        
        # The input is always a list containing a single new HumanMessage
        graph_input = {"messages": [HumanMessage(content=query)]}
        
        try:
            # Invoke the graph. It will automatically load the history for the given thread_id.
            final_state = agent_graph.invoke(graph_input, thread_config)
            
            # Extract and print the agent's last response
            last_message = final_state.get('messages', [])[-1]
            
            print("\n--- Agent's Response ---")
            if isinstance(last_message, AIMessage) and last_message.content:
                print(last_message.content)
            else:
                # This could be a tool call result or other non-text message
                print("(Agent's turn ended. See full state below for details.)")

            # Optionally, print the full final state for detailed debugging
            # print("\n--- Full State after Turn ---")
            # pprint.pprint(final_state)
            
        except Exception as e:
            print("\n--- AN ERROR OCCURRED ---")
            traceback.print_exc()
            break # Stop the conversation if an error occurs

# --- 3. Main Test Execution Block ---
if __name__ == "__main__":
    
    # --- Test Scenario 1: Flight Search (Amadeus Tool) ---
    # Goal: Test if the agent correctly identifies the need for flight search
    # and calls the amadeus_flight_search tool.
    thread_1_id = f"test_thread_{uuid.uuid4()}"
    test_scenario_1 = [
        # Note: Amadeus test environment requires future dates.
        "Hi, I need to book a flight to SFO from NYC for 2 people, from September 10th to September 15th, 2025."
    ]
    run_test_conversation(test_scenario_1, thread_1_id)
    
    # --- Test Scenario 2: General Info Search (Tavily Tool) ---
    # Goal: Test if the agent correctly identifies a general question
    # and calls the general_web_search tool.
    thread_2_id = f"test_thread_{uuid.uuid4()}"
    test_scenario_2 = [
        "What are some popular tourist attractions in Paris?"
    ]
    run_test_conversation(test_scenario_2, thread_2_id)
    
    # --- Test Scenario 3: Multi-Turn Conversation (Memory Test) ---
    # Goal: Test if the agent can handle a conversation, ask clarifying questions,
    # and use memory to call the right tool.
    thread_3_id = f"test_thread_{uuid.uuid4()}"
    test_scenario_3 = [
        "I want to go to London.", # Initial, incomplete query
        "I'll be traveling next year, from March 5th to March 10th.", # Providing more info
        "Also, are there any good musical shows happening during that time?" # Follow-up general question
    ]
    run_test_conversation(test_scenario_3, thread_3_id)
    from datetime import date, timedelta
    
    # Set dates for 3 months from now to ensure they are in the future
    departure_date = date.today() + timedelta(days=90)
    return_date = departure_date + timedelta(days=3)

    query = f"I want to find a flight from New York to San Francisco, departing on {departure_date.strftime('%Y-%m-%d')} for 3 days."
    
    thread_4_id = f"test_thread_{uuid.uuid4()}"
    run_test_conversation([query], thread_4_id)