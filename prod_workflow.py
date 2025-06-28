# production_workflow.py
# DEPLOYMENT-READY VERSION
# This file contains the complete, self-contained business logic for the
# automated dental aligner production and communication workflow.

# How to use this file:
# 1. Implement the placeholder functions in SECTION 1 with your real services
#    (e.g., Firebase, Twilio/Meta).
# 2. In your server file (e.g., server.py), import the functions from this file.
# 3. Initialize the LLM instance once in your server.
# 4. Call `start_production_step()` from your backend to advance a case.
# 5. Call `process_incoming_message()` from your webhook to handle replies from dentists.

import os
import requests
from dotenv import load_dotenv
from typing import Any, List, Optional, Mapping

from langchain_core.language_models.llms import LLM
from langchain_core.callbacks.manager import CallbackManagerForLLMRun
from langchain.prompts import PromptTemplate
from langchain.chains import LLMChain

# Load environment variables from a .env file
load_dotenv()


# ==============================================================================
# SECTION 1: SERVICE INTEGRATION PLACEHOLDERS
#
# TODO: You MUST implement these five functions with your actual services.
# ==============================================================================

def send_whatsapp_message(user_id: str, message: str):
    """
    IMPLEMENTATION REQUIRED: Sends a message to the user via your chosen provider.
    - user_id: The recipient's identifier (e.g., 'whatsapp:+15551234567').
    - message: The text content of the message to send.
    """
    print("\n" + "=" * 60)
    print(f"✅ [SENDING WHATSAPP TO: {user_id}]")
    print(f"MESSAGE:\n{message}")
    print("=" * 60)
    # Example for Meta/Twilio would involve an API call here.
    # e.g., client.messages.create(from_='whatsapp:+<YOUR_NUM>', body=message, to=user_id)
    raise NotImplementedError("Implement `send_whatsapp_message` with your API provider.")


def get_case_from_db(case_id: str) -> Optional[dict]:
    """
    IMPLEMENTATION REQUIRED: Gets case data from your database (e.g., Firebase).
    - case_id: The unique identifier for the case.
    - Returns a dictionary with case data or None if not found.
    """
    # Example for Firebase would be:
    # doc_ref = db.collection('cases').document(case_id)
    # doc = doc_ref.get()
    # return doc.to_dict() if doc.exists else None
    raise NotImplementedError("Implement `get_case_from_db` to fetch from your database.")


def update_case_in_db(case_id: str, updates: dict):
    """
    IMPLEMENTATION REQUIRED: Updates a case document in your database.
    - case_id: The unique identifier for the case to update.
    - updates: A dictionary of fields to set or merge.
    """
    # Example for Firebase would be:
    # db.collection('cases').document(case_id).update(updates)
    raise NotImplementedError("Implement `update_case_in_db` for your database.")


def get_user_session_from_db(user_id: str) -> Optional[dict]:
    """
    IMPLEMENTATION REQUIRED: Gets a user's session data from your database.
    - user_id: The user's unique identifier.
    - Returns a dictionary with session data or None if not found.
    """
    # Example for Firebase would be:
    # doc_ref = db.collection('user_sessions').document(user_id)
    # doc = doc_ref.get()
    # return doc.to_dict() if doc.exists else None
    raise NotImplementedError("Implement `get_user_session_from_db` for your database.")


def update_user_session_in_db(user_id: str, updates: dict):
    """
    IMPLEMENTATION REQUIRED: Updates a user's session in your database.
    - user_id: The user's unique identifier.
    - updates: A dictionary of fields to set or merge.
    """
    # Example for Firebase would be:
    # db.collection('user_sessions').document(user_id).set(updates, merge=True)
    raise NotImplementedError("Implement `update_user_session_in_db` for your database.")


# ==============================================================================
# SECTION 2: LLM CONFIGURATION
# ==============================================================================

class CustomOpenRouterLLM(LLM):
    """Custom LLM class for OpenRouter API."""
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
        if not api_key: raise ValueError("OPENROUTER_API_KEY not found in environment.")
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


# ==============================================================================
# SECTION 3: INTERNAL WORKFLOW LOGIC
# (These functions are called by the main entry points below)
# ==============================================================================

def _trigger_fit_confirmation_request(case_id: str, user_id: str, patient_name: str):
    """Internal: Sends the fit check message and updates system state."""
    print(f"[SYSTEM] Delivery confirmed for case '{case_id}'. Requesting fit confirmation.")
    message = f"Dear Doctor,\nOur records show the training aligner for patient '{patient_name}' has been delivered. Please confirm the fit once checked."
    send_whatsapp_message(user_id, message)
    update_case_in_db(case_id, {"status": "AwaitingFitConfirmation"})
    update_user_session_in_db(user_id, {"current_stage": "awaiting_fit_confirmation"})


def _handle_delivery_status_inquiry(user_id: str, session: dict):
    """Internal: Handles messages while user is awaiting delivery."""
    case_id = session.get("active_case")
    case_data = get_case_from_db(case_id)
    if not case_data: return

    patient_name = case_data.get("patient_name")
    delivery_status = case_data.get("delivery_status", "Info not available")

    print(f"[CHATBOT] Dentist inquired about delivery. DB status: '{delivery_status}'")

    if delivery_status and delivery_status.lower() == "delivered":
        _trigger_fit_confirmation_request(case_id, user_id, patient_name)
    else:
        message = f"Hi Doctor, the current status for the aligner for patient '{patient_name}' is: {delivery_status}."
        send_whatsapp_message(user_id, message)


def _handle_fit_confirmation_reply(user_id: str, message_body: str, llm_instance: LLM, session: dict):
    """Internal: Handles the 'yes/no' reply for aligner fit."""
    case_id = session.get("active_case")
    print(f"[CHATBOT] Dentist replied about fit: '{message_body}'. Calling LLM...")

    prompt = PromptTemplate(input_variables=["user_response"],
                            template="A dentist was asked if a training aligner fits correctly. Classify their response as 'Yes', 'No', or 'Unknown'. Respond with only one word.\n\nResponse: '{user_response}'\nClassification:")
    chain = LLMChain(llm=llm_instance, prompt=prompt)

    try:
        fit_confirmation = chain.run(user_response=message_body).strip().lower()
        print(f"[CHATBOT] LLM classified fit as: '{fit_confirmation}'")

        if "yes" in fit_confirmation:
            send_whatsapp_message(user_id,
                                  "Excellent. Would you like the aligners dispatched Phase-Wise or as a Full Case?")
            update_user_session_in_db(user_id, {"current_stage": "awaiting_dispatch_choice"})
        elif "no" in fit_confirmation:
            send_whatsapp_message(user_id,
                                  "Thank you for the feedback. A member of our clinical team will contact you shortly.")
            update_case_in_db(case_id, {"status": "FitIssueReported"})
            update_user_session_in_db(user_id, {"current_stage": "general"})
        else:
            send_whatsapp_message(user_id,
                                  "I'm sorry, I didn't quite understand. Does the aligner fit correctly? A simple 'yes' or 'no' would be helpful.")
    except Exception as e:
        print(f"❌ [LLM-ERROR] Could not process fit confirmation: {e}")


def _handle_dispatch_choice_reply(user_id: str, message_body: str, llm_instance: LLM, session: dict):
    """Internal: Handles the 'Phase-Wise' or 'Full Case' reply."""
    case_id = session.get("active_case")
    print(f"[CHATBOT] Dentist replied about dispatch choice: '{message_body}'. Calling LLM...")

    prompt = PromptTemplate(input_variables=["user_response"],
                            template="A dentist was asked if they want aligners dispatched 'Phase-Wise' or as a 'Full Case'. Classify their response. Respond with only 'PhaseWise', 'FullCase', or 'Unknown'.\n\nResponse: '{user_response}'\nChoice:")
    chain = LLMChain(llm=llm_instance, prompt=prompt)

    try:
        dispatch_choice = chain.run(user_response=message_body).strip().lower()
        print(f"[CHATBOT] LLM classified dispatch choice as: '{dispatch_choice}'")

        new_status = None
        if "phasewise" in dispatch_choice:
            new_status = "FitConfirmed_PhaseWise"
        elif "fullcase" in dispatch_choice:
            new_status = "FitConfirmed_FullCase"

        if new_status:
            update_case_in_db(case_id, {"status": new_status})
            update_user_session_in_db(user_id, {"current_stage": "general"})
            start_production_step(case_id)  # Automatically trigger the next step
        else:
            send_whatsapp_message(user_id,
                                  "My apologies, I'm not sure which option you'd prefer. Please reply with 'Phase-Wise' or 'Full Case'.")
    except Exception as e:
        print(f"❌ [LLM-ERROR] Could not process dispatch choice: {e}")


# ==============================================================================
# SECTION 4: MAIN ENTRY POINTS FOR YOUR SERVER
#
# These are the only two functions you should need to import and call from
# your server code (e.g., server.py or main.py).
# ==============================================================================

def start_production_step(case_id: str):
    """
    SERVER ENTRY POINT 1: Call this from your backend to advance a case.

    This function checks the case's current status and executes the next
    automated step in the production workflow.

    Example usage in your backend:
    from production_workflow import start_production_step

    # When a case is approved by your team:
    start_production_step("case-abc-123")
    """
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
        msg = (f"Dear Doctor,\nThe training aligner for patient '{patient_name}' has been dispatched. "
               "We will notify you upon delivery. You can also reply here for a status update.")
        send_whatsapp_message(user_id, msg)
        # Your system should update 'delivery_status' from the Google Sheet/delivery partner
        update_case_in_db(case_id, {"status": "AwaitingDelivery", "delivery_status": "In Transit"})
        update_user_session_in_db(user_id, {"current_stage": "awaiting_delivery", "active_case": case_id})
        print("➡️  [ENGINE] New status: AwaitingDelivery.")

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
        print(f"[ENGINE] Info: No automated action defined for status '{status}'.")


def process_incoming_message(user_id: str, message_body: str, llm_instance: LLM):
    """
    SERVER ENTRY POINT 2: Call this from your webhook for all incoming messages.

    This function routes the message to the correct logic based on the user's
    current stage in the conversation.

    Example usage in your Flask/FastAPI webhook:
    from production_workflow import process_incoming_message, CustomOpenRouterLLM

    # Initialize LLM once when your server starts
    llm = CustomOpenRouterLLM(n=1)

    @app.route("/webhook", methods=["POST"])
    def webhook():
        data = request.json
        user_id = data.get("from")
        message_body = data.get("body")
        process_incoming_message(user_id, message_body, llm)
        return "OK", 200
    """
    session = get_user_session_from_db(user_id)
    if not session or "current_stage" not in session:
        print(f"[ROUTER] No active session found for user '{user_id}'. Ignoring message.")
        return

    stage = session["current_stage"]
    print(f"\n[ROUTER] Routing message for user '{user_id}' in stage '{stage}'.")

    if stage == "awaiting_delivery":
        _handle_delivery_status_inquiry(user_id, session)
    elif stage == "awaiting_fit_confirmation":
        _handle_fit_confirmation_reply(user_id, message_body, llm_instance, session)
    elif stage == "awaiting_dispatch_choice":
        _handle_dispatch_choice_reply(user_id, message_body, llm_instance, session)
    else:
        print(f"[ROUTER] User is in stage '{stage}'. No specific action defined. Ignoring message.")