# test_agent.py (Final Version for testing the refactored agent_graph.py)

import uuid
import pprint
import traceback

# This will import the NEW, refactored version of your agent_graph.py
from agent_graph import build_graph
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

# --- 1. Build the Agent Graph ---
# We build the graph with a fresh in-memory checkpointer for each test run.
print("--- Building the agent graph definition (blueprint) ---")
agent_graph_builder = build_graph()  # Step 1: Get the blueprint (no arguments passed)
print("--- Graph definition build complete ---")

# Step 2: Prepare the checkpointer (memory) for this specific test
memory = InMemorySaver() 

# Step 3: Compile the graph using the blueprint and the checkpointer
agent_graph = agent_graph_builder.compile(checkpointer=memory)
print("--- Graph compiled successfully for testing ---")


# --- 2. Define a Test Runner Function ---
def run_test_scenario(query: str, thread_id: str):
    """
    Simulates a full conversation turn with the agent for a given query.
    """
    print(f"\n\n=======================================================")
    print(f"--- STARTING TEST SCENARIO ---")
    print(f"Thread ID: {thread_id}")
    print(f"User Query: \"{query}\"")
    print(f"=======================================================")

    graph_input = {"messages": [HumanMessage(content=query)]}
    thread_config = {"configurable": {"thread_id": thread_id}}
    
    try:
        # Invoke the graph synchronously. This now uses the langchain-google-genai backed agent.
        final_state = agent_graph.invoke(graph_input, thread_config)
        
        print("\n--- FINAL STATE ---")
        pprint.pprint(final_state)

        # Safely extract and print the final reply
        messages = final_state.get('messages', [])
        if messages:
            last_message = messages[-1]
            print("\n--- FINAL AGENT REPLY ---")
            # Check if the last message has content. If it's a tool call, it might be empty.
            if last_message.content:
                print(last_message.content)
            else:
                print("(Agent ended with a tool call or non-text message)")
        else:
            print("\n--- No messages in final state. ---")
        
    except Exception as e:
        print("\n--- AN ERROR OCCURRED DURING GRAPH INVOCATION ---")
        traceback.print_exc()

# --- 3. Main Test Execution Block ---
if __name__ == "__main__":
    
    # --- Test Scenario 1: Information is missing ---
    # Expected Flow: extractor -> slot_filler -> END
    missing_info_query = "I want to go to Hawaii."
    thread_1_id = f"test_thread_{uuid.uuid4()}"
    run_test_scenario(missing_info_query, thread_1_id)
    
    # --- Test Scenario 2: All information is provided ---
    # Expected Flow: extractor -> tool_executor -> final_responder -> END
    complete_info_query = "I want to book a flight to Tokyo from 2025-12-20 to 2025-12-27."
    thread_2_id = f"test_thread_{uuid.uuid4()}"
    run_test_scenario(complete_info_query, thread_2_id)
    
    # --- Test Scenario 3: Follow-up in the same thread (to test memory) ---
    # We will use the same thread_id from scenario 1 to see if the agent remembers the context.
    print("\n\n--- CONTINUING CONVERSATION for Thread 1 ---")
    follow_up_query = "My travel dates are from December 20th to December 27th, 2025."
    run_test_scenario(follow_up_query, thread_1_id) # Using the SAME thread_1_id