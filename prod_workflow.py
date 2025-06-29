import os
import requests
from dotenv import load_dotenv
from typing import Any, List, Optional, Mapping, Dict

from langchain_core.language_models.llms import LLM
from langchain.prompts import PromptTemplate
from langchain.chains import LLMChain
from langchain_openai import ChatOpenAI # Required for OpenAI LLM

# Load environment variables from a .env file
# This is kept as LLM might still require API keys from environment
load_dotenv()

# ==============================================================================
# SECTION 1: CONSOLIDATED WORKFLOW FUNCTION
# (All logic, no direct I/O)
# ==============================================================================

def dental_aligner_workflow(
    action_type: str, # "start_production" or "process_message"
    llm_instance: ChatOpenAI,
    case_id: Optional[str] = None,
    user_id: Optional[str] = None,
    message_body: Optional[str] = None,
    current_case_data: Optional[Dict[str, Any]] = None,
    current_user_session: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Executes the dental aligner production and communication workflow logic.
    This function is a pure function: it takes all necessary current state as input
    and returns all updated state and outgoing messages, without performing any
    direct I/O (database operations or message sending).

    Args:
        action_type (str): Specifies the type of action to perform.
                           - Use **"start_production"** when a new production step is triggered
                             by your backend (e.g., after approval, delivery confirmation).
                           - Use **"process_message"** when a dentist sends an incoming message.
        llm_instance (ChatOpenAI): An initialized LangChain `ChatOpenAI` instance.
                                    This must be provided by the caller.
        case_id (Optional[str]): The unique identifier for the case relevant to the action.
                                 Required for "start_production". For "process_message",
                                 it's typically derived from `current_user_session['active_case']`.
        user_id (Optional[str]): The unique identifier for the dentist/user (e.g., WhatsApp ID).
                                 Required for "process_message" action.
        message_body (Optional[str]): The text content of the incoming message from the dentist.
                                      Required if `action_type` is "process_message".
        current_case_data (Optional[Dict[str, Any]]): The current state of the case data.
                                                       This **must be provided by the caller**
                                                       and reflects your database's current view.
                                                       Example: `{"id": "case-123", "status": "ApprovedForProduction", "user_id": "whatsapp:+123...", "patient_name": "Alice"}`
        current_user_session (Optional[Dict[str, Any]]): The current state of the user's session data.
                                                          This **must be provided by the caller**
                                                          and reflects your database's current view.
                                                          Example: `{"user_id": "whatsapp:+123...", "current_stage": "general", "active_case": "case-123"}`

    Returns:
        Dict[str, Any]: A dictionary containing the results of the operation:
            - **'updated_case_data'**: The case data after potential modifications.
                                     Your application should use this to update your database.
            - **'updated_user_session'**: The user session data after potential modifications.
                                        Your application should use this to update your database.
            - **'messages_to_send'**: A `list` of dictionaries. Each dictionary contains:
                                    `'recipient_id'` (str): The ID to send the message to.
                                    `'content'` (str): The message text.
                                    Your application should iterate this list and send messages.
            - **'status'**: A string indicating the outcome ("Success", "Error", "NoAction").
            - **'error'**: An error message string if `status` is "Error".
    """

    # Initialize mutable data structures for updates and messages
    updated_case_data = current_case_data.copy() if current_case_data else {}
    updated_user_session = current_user_session.copy() if current_user_session else {}
    messages_to_send = []
    response_status = "Success"
    error_message = None

    if action_type == "start_production":
        # --- Logic for starting a production step ---
        if not case_id or not current_case_data:
            error_message = "[ENGINE-ERROR] 'case_id' and 'current_case_data' must be provided for 'start_production' action."
            response_status = "Error"
        else:
            status = updated_case_data.get("status")
            user_id_from_case = updated_case_data.get("user_id")
            patient_name = updated_case_data.get("patient_name")
            print(f"\n[ENGINE] Advancing case '{case_id}'. Current status: '{status}'") # Internal log

            if status == "ApprovedForProduction":
                messages_to_send.append({
                    "recipient_id": user_id_from_case,
                    "content": f"Dear Doctor, planning for patient '{patient_name}' has started."
                })
                updated_case_data["status"] = "CasePlanningComplete"
                print("➡️  [ENGINE] New status: CasePlanningComplete") # Internal log

            elif status == "CasePlanningComplete":
                msg = (f"Dear Doctor,\nThe training aligner for patient '{patient_name}' has been dispatched. "
                       "We will notify you upon delivery. You can also reply here for a status update.")
                messages_to_send.append({
                    "recipient_id": user_id_from_case,
                    "content": msg
                })
                updated_case_data["status"] = "AwaitingDelivery"
                # Note: 'delivery_status' is typically updated by an external system (e.g., webhook from delivery partner)
                updated_case_data["delivery_status"] = "In Transit"
                updated_user_session["current_stage"] = "awaiting_delivery"
                updated_user_session["active_case"] = case_id
                print("➡️  [ENGINE] New status: AwaitingDelivery.") # Internal log

            elif status == "FitConfirmed_PhaseWise":
                messages_to_send.append({
                    "recipient_id": user_id_from_case,
                    "content": f"Thank you. The first phase of aligners for '{patient_name}' is being prepared for dispatch."
                })
                updated_case_data["status"] = "Dispatching_PhaseWise"
                print("➡️  [ENGINE] New status: Dispatching_PhaseWise") # Internal log

            elif status == "FitConfirmed_FullCase":
                messages_to_send.append({
                    "recipient_id": user_id_from_case,
                    "content": f"Thank you. The full set of aligners for '{patient_name}' is being prepared for dispatch."
                })
                updated_case_data["status"] = "Dispatching_FullCase"
                print("➡️  [ENGINE] New status: Dispatching_FullCase") # Internal log

            else:
                print(f"[ENGINE] Info: No automated action defined for status '{status}'.") # Internal log
                response_status = "NoAction"

    elif action_type == "process_message":
        # --- Logic for processing incoming messages ---
        if not user_id or not message_body or not current_user_session:
            error_message = "[ROUTER-ERROR] 'user_id', 'message_body', and 'current_user_session' must be provided for 'process_message' action."
            response_status = "Error"
        else:
            stage = updated_user_session.get("current_stage")
            active_case_id = updated_user_session.get("active_case")
            print(f"\n[ROUTER] Routing message for user '{user_id}' in stage '{stage}'.") # Internal log

            if stage == "awaiting_delivery":
                # Inlined delivery status inquiry logic
                if not active_case_id or not current_case_data:
                    print("[CHATBOT] No active case for user in awaiting_delivery stage.") # Internal log
                    error_message = "No active case or case data found for this user to inquire about delivery."
                    response_status = "Error"
                else:
                    patient_name = updated_case_data.get("patient_name")
                    delivery_status = updated_case_data.get("delivery_status", "Info not available")

                    print(f"[CHATBOT] Dentist inquired about delivery. DB status: '{delivery_status}'") # Internal log

                    if delivery_status and delivery_status.lower() == "delivered":
                        # Inlined fit confirmation request logic
                        print(f"[SYSTEM] Delivery confirmed for case '{active_case_id}'. Requesting fit confirmation.") # Internal log
                        messages_to_send.append({
                            "recipient_id": user_id,
                            "content": f"Dear Doctor,\nOur records show the training aligner for patient '{patient_name}' has been delivered. Please confirm the fit once checked."
                        })
                        updated_case_data["status"] = "AwaitingFitConfirmation"
                        updated_user_session["current_stage"] = "awaiting_fit_confirmation"
                    else:
                        messages_to_send.append({
                            "recipient_id": user_id,
                            "content": f"Hi Doctor, the current status for the aligner for patient '{patient_name}' is: {delivery_status}."
                        })

            elif stage == "awaiting_fit_confirmation":
                # Inlined fit confirmation reply logic
                if not active_case_id:
                    print("[CHATBOT] No active case for user in awaiting_fit_confirmation stage.") # Internal log
                    error_message = "No active case found for this user to confirm fit."
                    response_status = "Error"
                else:
                    print(f"[CHATBOT] Dentist replied about fit: '{message_body}'. Calling LLM...") # Internal log
                    prompt = PromptTemplate(input_variables=["user_response"],
                                            template="A dentist was asked if a training aligner fits correctly. Classify their response as 'Yes', 'No', or 'Unknown'. Respond with only one word.\n\nResponse: '{user_response}'\nClassification:")
                    chain = LLMChain(llm=llm_instance, prompt=prompt)

                    try:
                        fit_confirmation = chain.run(user_response=message_body).strip().lower()
                        print(f"[CHATBOT] LLM classified fit as: '{fit_confirmation}'") # Internal log

                        if "yes" in fit_confirmation:
                            messages_to_send.append({
                                "recipient_id": user_id,
                                "content": "Excellent. Would you like the aligners dispatched Phase-Wise or as a Full Case?"
                            })
                            updated_user_session["current_stage"] = "awaiting_dispatch_choice"
                        elif "no" in fit_confirmation:
                            messages_to_send.append({
                                "recipient_id": user_id,
                                "content": "Thank you for the feedback. A member of our clinical team will contact you shortly."
                            })
                            updated_case_data["status"] = "FitIssueReported"
                            updated_user_session["current_stage"] = "general"
                        else:
                            messages_to_send.append({
                                "recipient_id": user_id,
                                "content": "I'm sorry, I didn't quite understand. Does the aligner fit correctly? A simple 'yes' or 'no' would be helpful."
                            })
                    except Exception as e:
                        print(f"❌ [LLM-ERROR] Could not process fit confirmation: {e}") # Internal log
                        error_message = f"LLM error during fit confirmation: {e}"
                        response_status = "Error"

            elif stage == "awaiting_dispatch_choice":
                # Inlined dispatch choice reply logic
                if not active_case_id:
                    print("[CHATBOT] No active case for user in awaiting_dispatch_choice stage.") # Internal log
                    error_message = "No active case found for this user to confirm dispatch choice."
                    response_status = "Error"
                else:
                    print(f"[CHATBOT] Dentist replied about dispatch choice: '{message_body}'. Calling LLM...") # Internal log
                    prompt = PromptTemplate(input_variables=["user_response"],
                                            template="A dentist was asked if they want aligners dispatched 'Phase-Wise' or as a 'Full Case'. Classify their response. Respond with only 'PhaseWise', 'FullCase', or 'Unknown'.\n\nResponse: '{user_response}'\nChoice:")
                    chain = LLMChain(llm=llm_instance, prompt=prompt)

                    try:
                        dispatch_choice = chain.run(user_response=message_body).strip().lower()
                        print(f"[CHATBOT] LLM classified dispatch choice as: '{dispatch_choice}'") # Internal log

                        new_status = None
                        if "phasewise" in dispatch_choice:
                            new_status = "FitConfirmed_PhaseWise"
                        elif "fullcase" in dispatch_choice:
                            new_status = "FitConfirmed_FullCase"

                        if new_status:
                            updated_case_data["status"] = new_status
                            updated_user_session["current_stage"] = "general"
                            # IMPORTANT: The original workflow would have triggered `start_production_step` here.
                            # In this pure function, you should have your *backend* observe the returned
                            # `updated_case_data['status']` and, if it matches a trigger condition (e.g., "FitConfirmed_PhaseWise"),
                            # then make a *subsequent* call to `dental_aligner_workflow` with `action_type="start_production"`
                            # and the latest case data to advance that specific step.
                        else:
                            messages_to_send.append({
                                "recipient_id": user_id,
                                "content": "My apologies, I'm not sure which option you'd prefer. Please reply with 'Phase-Wise' or 'Full Case'."
                            })
                    except Exception as e:
                        print(f"❌ [LLM-ERROR] Could not process dispatch choice: {e}") # Internal log
                        error_message = f"LLM error during dispatch choice: {e}"
                        response_status = "Error"
            else:
                print(f"[ROUTER] User is in stage '{stage}'. No specific action defined. Ignoring message.") # Internal log
                error_message = f"User is in unhandled stage '{stage}'."
                response_status = "NoAction" # Custom status for "no specific action taken"

    else:
        error_message = "Invalid 'action_type' provided. Must be 'start_production' or 'process_message'."
        response_status = "Error"

    return {
        "updated_case_data": updated_case_data,
        "updated_user_session": updated_user_session,
        "messages_to_send": messages_to_send,
        "status": response_status,
        "error": error_message
    }