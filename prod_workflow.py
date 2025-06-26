# production_workflow.py
# FINAL, REFACTORED VERSION
# A clean, single-file implementation of the production workflow,
# refactored to be easily importable and testable.

import time
import json
import os
import requests
from dotenv import load_dotenv
from typing import Any, List, Optional, Mapping, Callable

from langchain_core.language_models.llms import LLM
from langchain_core.callbacks.manager import CallbackManagerForLLMRun
from langchain.prompts import PromptTemplate
from langchain.chains import LLMChain


# ==============================================================================
# SECTION 1: CORE LOGIC & SERVICE PLACEHOLDERS
# ==============================================================================

# --- Service Placeholders (TODO: Implement these with your real services) ---

def send_whatsapp_message(user_id: str, message: str):
    """PLACEHOLDER: Sends a message via a real service like Twilio."""
    print("\n" + "=" * 60)
    print(f"✅ [SENDING WHATSAPP TO: {user_id}]")
    print(f"MESSAGE:\n{message}")
    print("=" * 60)


def get_case_from_db_real(case_id: str) -> dict:
    """PLACEHOLDER: Gets case data from a real database like Firebase."""
    raise NotImplementedError("This function should be implemented with a real database call.")


def update_case_in_db_real(case_id: str, updates: dict):
    """PLACEHOLDER: Updates a case in a real database like Firebase."""
    raise NotImplementedError("This function should be implemented with a real database call.")


def get_user_session_from_db_real(user_id: str) -> dict:
    """PLACEHOLDER: Gets a user's session from a real database like Firebase."""
    raise NotImplementedError("This function should be implemented with a real database call.")


def update_user_session_in_db_real(user_id: str, updates: dict):
    """PLACEHOLDER: Updates a user's session in a real database like Firebase."""
    raise NotImplementedError("This function should be implemented with a real database call.")


# --- LLM Setup ---

class CustomOpenRouterLLM(LLM):
    """Your custom LLM class for OpenRouter."""
    n: int
    model_to_use: str = "deepseek/deepseek-r1-0528:free"

    @property
    def _llm_type(self) -> str:
        return "custom_openrouter_llm"

    def _call(
            self, prompt: str, stop: Optional[List[str]] = None,
            run_manager: Optional[CallbackManagerForLLMRun] = None, **kwargs: Any
    ) -> str:
        api_key = os.getenv('OPENROUTER_API_KEY')
        if not api_key: raise ValueError("OPENROUTER_API_KEY not found.")
        headers = {'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'}
        data = {'model': self.model_to_use, 'messages': [{'role': 'user', 'content': prompt}]}
        try:
            response = requests.post('https://openrouter.ai/api/v1/chat/completions', headers=headers, json=data)
            response.raise_for_status()
            return response.json()['choices'][0]['message']['content']
        except (requests.exceptions.RequestException, KeyError, IndexError) as e:
            raise ValueError(f"API call or parsing failed: {e}")

    @property
    def _identifying_params(self) -> Mapping[str, Any]:
        return {"n": self.n, "model_name": self.model_to_use}


# --- Core Workflow Functions (Refactored for Dependency Injection) ---

def start_production_step(
        case_id: str,
        get_case_from_db: Callable,
        update_case_in_db: Callable,
        update_user_session_in_db: Callable
):
    """Main engine function. It now accepts database functions as arguments."""
    case_data = get_case_from_db(case_id)
    if not case_data:
        print(f"[ENGINE-ERROR] Case '{case_id}' not found.")
        return

    status = case_data.get("status")
    user_id = case_data.get("user_id")
    patient_name = case_data.get("patient_name")
    print(f"\n[ENGINE] Advancing case '{case_id}'. Current status: '{status}'")

    if status == "ApprovedForProduction":
        send_whatsapp_message(user_id, f"Dear Doctor, planning for patient '{patient_name}' has started.")
        update_case_in_db(case_id, {"status": "CasePlanningComplete"})
        print("➡️  [ENGINE] New status: CasePlanningComplete")

    elif status == "CasePlanningComplete":
        send_whatsapp_message(user_id,
                              f"Dear Doctor,\nThe training aligner for patient '{patient_name}' has been dispatched. Please confirm the fit once received.")
        update_case_in_db(case_id, {"status": "AwaitingFitConfirmation"})
        update_user_session_in_db(user_id, {"current_stage": "awaiting_fit_confirmation", "active_case": case_id})
        print("➡️  [ENGINE] New status: AwaitingFitConfirmation. Waiting for dentist reply.")

    elif status == "FitConfirmed_PhaseWise":
        send_whatsapp_message(user_id,
                              f"Thank you. The first phase of aligners for '{patient_name}' is being prepared for dispatch.")
        update_case_in_db(case_id, {"status": "Dispatching_PhaseWise"})
        print("➡️  [ENGINE] New status: Dispatching_PhaseWise")

    elif status == "FitConfirmed_FullCase":
        send_whatsapp_message(user_id,
                              f"Thank you. The full set of aligners for '{patient_name}' is being prepared for dispatch.")
        update_case_in_db(case_id, {"status": "Dispatching_FullCase"})
        print("➡️  [ENGINE] New status: Dispatching_FullCase")
    else:
        print(f"[ENGINE] Info: No automated action for status '{status}'.")


def handle_dentist_reply(
        user_id: str,
        message_body: str,
        llm_chain: LLMChain,
        get_user_session_from_db: Callable,
        update_user_session_in_db: Callable,
        update_case_in_db: Callable
):
    """Handles the dentist's first reply. Accepts DB functions as arguments."""
    session = get_user_session_from_db(user_id)
    if session.get("current_stage") != "awaiting_fit_confirmation":
        print("[CHATBOT] Message ignored (not awaiting confirmation).")
        return

    case_id = session.get("active_case")
    print(f"\n[CHATBOT] Dentist replied: '{message_body}'. Calling LLM...")

    try:
        fit_confirmation = llm_chain.run(user_response=message_body).strip()
        print(f"[CHATBOT] LLM classified fit confirmation as: '{fit_confirmation}'")

        if "yes" in fit_confirmation.lower():
            send_whatsapp_message(user_id,
                                  "Excellent. Would you like the aligners dispatched Phase-Wise or as a Full Case?")
            update_user_session_in_db(user_id, {"current_stage": "awaiting_dispatch_choice"})

        elif "no" in fit_confirmation.lower():
            send_whatsapp_message(user_id,
                                  "Thank you for the feedback. A member of our clinical team will contact you shortly.")
            update_case_in_db(case_id, {"status": "FitIssueReported"})
            update_user_session_in_db(user_id, {"current_stage": "general"})

        else:
            send_whatsapp_message(user_id,
                                  "I'm sorry, I didn't quite understand. Does the aligner fit correctly? A simple 'yes' or 'no' would be helpful.")

    except Exception as e:
        print(f"❌ [LLM-ERROR] API call failed: {e}")


def handle_dispatch_choice_reply(
        user_id: str,
        message_body: str,
        llm: LLM,
        get_user_session_from_db: Callable,
        update_user_session_in_db: Callable,
        get_case_from_db: Callable,
        update_case_in_db: Callable
):
    """Handles dispatch choice reply. Accepts DB functions and an LLM instance."""
    session = get_user_session_from_db(user_id)
    if session.get("current_stage") != "awaiting_dispatch_choice":
        return

    case_id = session.get("active_case")
    print(f"\n[CHATBOT] Dentist replied about dispatch choice: '{message_body}'. Calling LLM...")

    choice_prompt = PromptTemplate(
        input_variables=["user_response"],
        template="A dentist was asked if they want aligners dispatched 'Phase-Wise' or as a 'Full Case'. Classify their response. Respond with only 'PhaseWise', 'FullCase', or 'Unknown'.\n\nResponse: '{user_response}'\nChoice:"
    )
    choice_chain = LLMChain(llm=llm, prompt=choice_prompt)

    try:
        dispatch_choice = choice_chain.run(user_response=message_body).strip()
        print(f"[CHATBOT] LLM classified dispatch choice as: '{dispatch_choice}'")

        if "phasewise" in dispatch_choice.lower():
            update_case_in_db(case_id, {"status": "FitConfirmed_PhaseWise"})
        elif "fullcase" in dispatch_choice.lower():
            update_case_in_db(case_id, {"status": "FitConfirmed_FullCase"})
        else:
            send_whatsapp_message(user_id,
                                  "My apologies, I'm not sure which dispatch option you'd prefer. Please reply with 'Phase-Wise' or 'Full Case'.")
            return

        update_user_session_in_db(user_id, {"current_stage": "general"})
        # Automatically trigger the next step after the choice is made
        start_production_step(case_id, get_case_from_db, update_case_in_db, update_user_session_in_db)

    except Exception as e:
        print(f"❌ [LLM-ERROR] API call failed: {e}")


# ==============================================================================
# SECTION 2: IMPORTABLE TEST FUNCTION
# ==============================================================================

def run_interactive_test():
    """
    This function encapsulates the entire interactive test flow.
    It creates its own mock database and mock functions, then passes them
    to the core logic functions to run a self-contained test.
    """
    load_dotenv(override=True)
    if not os.getenv("OPENROUTER_API_KEY"):
        print("❌ FATAL: OPENROUTER_API_KEY not found in .env file. Cannot run test.")
        return

    # --- Setup Mock Database for this specific test run ---
    MOCK_DB = {
        "cases": {},
        "user_sessions": {}
    }

    # --- Define Mock DB functions for this test ---
    def mock_get_case_from_db(case_id: str) -> dict:
        return MOCK_DB["cases"].get(case_id, {})

    def mock_update_case_in_db(case_id: str, updates: dict):
        MOCK_DB["cases"].get(case_id, {}).update(updates)

    def mock_get_user_session_from_db(user_id: str) -> dict:
        return MOCK_DB["user_sessions"].get(user_id, {})

    def mock_update_user_session_in_db(user_id: str, updates: dict):
        MOCK_DB["user_sessions"].get(user_id, {}).update(updates)

    # --- Initialize LLM Chain for the test ---
    llm_instance = CustomOpenRouterLLM(n=1)
    fit_prompt = PromptTemplate(input_variables=["user_response"],
                                template="A dentist was asked if a training aligner fits correctly. Classify their response as 'Yes', 'No', or 'Unknown'. Respond with only one word.\n\nResponse: '{user_response}'\nClassification:")
    fit_confirm_chain = LLMChain(llm=llm_instance, prompt=fit_prompt)

    # --- Automated Test Sequence ---
    TEST_CASE_ID = "case_simple_123"
    TEST_USER_ID = "whatsapp_test_user"
    MOCK_DB["cases"][TEST_CASE_ID] = {"patient_name": "Test Patient", "user_id": TEST_USER_ID,
                                      "status": "ApprovedForProduction"}
    MOCK_DB["user_sessions"][TEST_USER_ID] = {"current_stage": "general"}

    print("\n--- STARTING INTERACTIVE WORKFLOW TEST ---")
    time.sleep(1)

    # 1. Start the process, passing the mock DB functions
    print("\nSTEP 1: Your backend starts the production for the case.")
    start_production_step(
        TEST_CASE_ID,
        get_case_from_db=mock_get_case_from_db,
        update_case_in_db=mock_update_case_in_db,
        update_user_session_in_db=mock_update_user_session_in_db
    )
    time.sleep(1)

    # 2. Mark training aligner as dispatched
    print("\nSTEP 2: Your backend marks the training aligner as dispatched.")
    start_production_step(
        TEST_CASE_ID,
        get_case_from_db=mock_get_case_from_db,
        update_case_in_db=mock_update_case_in_db,
        update_user_session_in_db=mock_update_user_session_in_db
    )
    time.sleep(1)

    # 3. Simulate dentist replying about the fit
    print("\nSTEP 3: Dentist gets the message and replies. You will provide the reply.")
    dentist_fit_reply = input("DENTIST FIT REPLY > ")
    handle_dentist_reply(
        TEST_USER_ID,
        dentist_fit_reply,
        fit_confirm_chain,
        get_user_session_from_db=mock_get_user_session_from_db,
        update_user_session_in_db=mock_update_user_session_in_db,
        update_case_in_db=mock_update_case_in_db
    )
    time.sleep(1)

    # Check if the flow is waiting for the next choice
    if mock_get_user_session_from_db(TEST_USER_ID).get("current_stage") == "awaiting_dispatch_choice":
        # 4. Simulate the dentist replying about the dispatch method
        print("\nSTEP 4: Dentist is asked for dispatch preference. You will provide the reply.")
        dentist_dispatch_reply = input("DENTIST DISPATCH CHOICE > ")
        handle_dispatch_choice_reply(
            TEST_USER_ID,
            dentist_dispatch_reply,
            llm_instance,
            get_user_session_from_db=mock_get_user_session_from_db,
            update_user_session_in_db=mock_update_user_session_in_db,
            get_case_from_db=mock_get_case_from_db,
            update_case_in_db=mock_update_case_in_db
        )

    print("\n--- TEST COMPLETE ---")
    print("Final database state:")
    print(json.dumps(MOCK_DB, indent=2))