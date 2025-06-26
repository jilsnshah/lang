# server.py
# Example of how to use the refactored workflow logic.

# --- Import the functions from your logic file ---
import production_workflow as wf

# ==============================================================================
# OPTION 1: RUNNING THE INTERACTIVE TEST
# You can call this function from an admin dashboard, a command-line tool,
# or simply run this file to test the full flow interactively.
# ==============================================================================
def run_test():
    """A simple wrapper to run the imported test function."""
    print("About to run the interactive test from production_workflow.py")
    wf.run_interactive_test()
    print("Test finished.")


# ==============================================================================
# OPTION 2: USING THE LOGIC IN YOUR PRODUCTION SERVER
# This is how you would use the functions in your actual webhook handler.
# ==============================================================================

# In your actual server, you would initialize your real LLM instance once
# and your real database connection/functions.
LLM_INSTANCE_PROD = wf.CustomOpenRouterLLM(n=1)

FIT_CONFIRM_PROMPT = wf.PromptTemplate(
    input_variables=["user_response"], 
    template="A dentist was asked if a training aligner fits correctly. Classify their response as 'Yes', 'No', or 'Unknown'. Respond with only one word.\n\nResponse: '{user_response}'\nClassification:"
)
FIT_CONFIRM_CHAIN_PROD = wf.LLMChain(llm=LLM_INSTANCE_PROD, prompt=FIT_CONFIRM_PROMPT)


def your_webhook_handler(request_data):
    """
    This is a conceptual example of your server's webhook endpoint
    (e.g., for Twilio, in a Flask/FastAPI app).
    """
    user_id = request_data.get("from") # e.g., 'whatsapp:+14155238886'
    message_body = request_data.get("body")
    
    # 1. Get the user's current session from the REAL database
    session = wf.get_user_session_from_db_real(user_id) # Calling the real DB function
    current_stage = session.get("current_stage")

    # 2. Route the message based on the user's stage
    if current_stage == "awaiting_fit_confirmation":
        wf.handle_dentist_reply(
            user_id,
            message_body,
            llm_chain=FIT_CONFIRM_CHAIN_PROD,
            # Pass your REAL database functions to the logic
            get_user_session_from_db=wf.get_user_session_from_db_real,
            update_user_session_in_db=wf.update_user_session_in_db_real,
            update_case_in_db=wf.update_case_in_db_real
        )
    elif current_stage == "awaiting_dispatch_choice":
        wf.handle_dispatch_choice_reply(
            user_id,
            message_body,
            llm=LLM_INSTANCE_PROD,
            # Pass your REAL database functions to the logic
            get_user_session_from_db=wf.get_user_session_from_db_real,
            update_user_session_in_db=wf.update_user_session_in_db_real,
            get_case_from_db=wf.get_case_from_db_real,
            update_case_in_db=wf.update_case_in_db_real
        )
    else:
        # Handle general conversation, or ignore
        print("Received message for user in 'general' stage.")
        # ... your other chatbot logic here ...

# --- Main execution block for this example file ---
if __name__ == "__main__":
    # To run the interactive test, simply call the function.
    run_test()

    # You would not typically call your_webhook_handler directly here.
    # It would be part of a running web server (like Flask) that receives HTTP requests.