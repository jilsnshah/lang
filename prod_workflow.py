import os
import requests
import logging
import time
from datetime import datetime
from dotenv import load_dotenv
from typing import Any, List, Optional, Mapping, Dict

from langchain_core.language_models.llms import LLM
from langchain.prompts import PromptTemplate
from langchain.chains import LLMChain
from langchain_openai import ChatOpenAI # Required for OpenAI LLM

# Load environment variables from a .env file
# This is kept as LLM might still require API keys from environment
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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
            - **'next_actions'**: List of recommended next actions for the system.
    """

    # Initialize mutable data structures for updates and messages
    updated_case_data = current_case_data.copy() if current_case_data else {}
    updated_user_session = current_user_session.copy() if current_user_session else {}
    messages_to_send = []
    response_status = "Success"
    error_message = None
    next_actions = []

    # Add timestamp to track workflow execution
    workflow_timestamp = int(time.time())
    
    logger.info(f"🔄 Starting workflow: {action_type} at {datetime.now()}")

    try:
        if action_type == "start_production":
            result = handle_production_start(
                case_id, updated_case_data, messages_to_send, next_actions
            )
            response_status = result["status"]
            error_message = result.get("error")

        elif action_type == "process_message":
            result = handle_message_processing(
                user_id, message_body, updated_user_session, 
                updated_case_data, llm_instance, messages_to_send, next_actions
            )
            response_status = result["status"]
            error_message = result.get("error")

        else:
            error_message = "Invalid 'action_type' provided. Must be 'start_production' or 'process_message'."
            response_status = "Error"
            logger.error(f"❌ {error_message}")

    except Exception as e:
        error_message = f"Unexpected error in workflow: {str(e)}"
        response_status = "Error"
        logger.error(f"❌ {error_message}", exc_info=True)

    # Add workflow metadata
    if updated_case_data:
        updated_case_data["last_workflow_run"] = workflow_timestamp
        updated_case_data["last_action_type"] = action_type

    if updated_user_session:
        updated_user_session["last_activity"] = workflow_timestamp

    logger.info(f"✅ Workflow completed with status: {response_status}")

    return {
        "updated_case_data": updated_case_data,
        "updated_user_session": updated_user_session,
        "messages_to_send": messages_to_send,
        "status": response_status,
        "error": error_message,
        "next_actions": next_actions,
        "workflow_timestamp": workflow_timestamp
    }



# ==============================================================================
# SECTION 2: HELPER FUNCTIONS FOR WORKFLOW LOGIC
# ==============================================================================

def handle_production_start(case_id, updated_case_data, messages_to_send, next_actions):
    """Handle production start workflow"""
    if not case_id or not updated_case_data:
        return {
            "status": "Error",
            "error": "[ENGINE-ERROR] 'case_id' and 'current_case_data' must be provided for 'start_production' action."
        }
    
    status = updated_case_data.get("status")
    user_id_from_case = updated_case_data.get("user_id")
    patient_name = updated_case_data.get("patient_name", "Unknown Patient")
    
    logger.info(f"🏭 Advancing case '{case_id}'. Current status: '{status}'")

    if status == "ApprovedForProduction":
        messages_to_send.append({
            "recipient_id": user_id_from_case,
            "content": f"Dear Doctor, planning for patient '{patient_name}' has started. We'll keep you updated on the progress."
        })
        updated_case_data["status"] = "CasePlanningComplete"
        updated_case_data["planning_started_at"] = int(time.time())
        next_actions.append("schedule_training_aligner_production")
        logger.info("➡️ New status: CasePlanningComplete")

    elif status == "CasePlanningComplete":
        msg = (f"Dear Doctor,\n\nThe training aligner for patient '{patient_name}' has been dispatched. "
               "Estimated delivery: 2-3 business days.\n\n"
               "We will notify you upon delivery. You can also reply here for a status update.")
        
        messages_to_send.append({
            "recipient_id": user_id_from_case,
            "content": msg
        })
        updated_case_data["status"] = "AwaitingDelivery"
        updated_case_data["delivery_status"] = "In Transit"
        updated_case_data["dispatched_at"] = int(time.time())
        next_actions.append("track_delivery")
        logger.info("➡️ New status: AwaitingDelivery")

    elif status == "FitConfirmed_PhaseWise":
        messages_to_send.append({
            "recipient_id": user_id_from_case,
            "content": f"Thank you for confirming the fit! The first phase of aligners for '{patient_name}' is being prepared for dispatch. Expected delivery: 5-7 business days."
        })
        updated_case_data["status"] = "Dispatching_PhaseWise"
        updated_case_data["phase_production_started"] = int(time.time())
        next_actions.append("schedule_phase_production")
        logger.info("➡️ New status: Dispatching_PhaseWise")

    elif status == "FitConfirmed_FullCase":
        messages_to_send.append({
            "recipient_id": user_id_from_case,
            "content": f"Thank you for confirming the fit! The full set of aligners for '{patient_name}' is being prepared for dispatch. Expected delivery: 7-10 business days."
        })
        updated_case_data["status"] = "Dispatching_FullCase"
        updated_case_data["full_production_started"] = int(time.time())
        next_actions.append("schedule_full_production")
        logger.info("➡️ New status: Dispatching_FullCase")

    else:
        logger.info(f"ℹ️ No automated action defined for status '{status}'")
        return {"status": "NoAction"}

    return {"status": "Success"}


def handle_message_processing(user_id, message_body, updated_user_session, 
                            updated_case_data, llm_instance, messages_to_send, next_actions):
    """Handle incoming message processing workflow"""
    if not user_id or not message_body or not updated_user_session:
        return {
            "status": "Error",
            "error": "[ROUTER-ERROR] 'user_id', 'message_body', and 'current_user_session' must be provided for 'process_message' action."
        }
    
    stage = updated_user_session.get("current_stage", "general")
    active_case_id = updated_user_session.get("active_case")
    
    logger.info(f"📨 Processing message from user '{user_id}' in stage '{stage}': {message_body}")

    # Handle different conversation stages
    if stage == "awaiting_delivery":
        return handle_delivery_inquiry(
            user_id, message_body, active_case_id, updated_case_data, 
            updated_user_session, messages_to_send, next_actions
        )
    
    elif stage == "awaiting_fit_confirmation":
        return handle_fit_confirmation(
            user_id, message_body, active_case_id, updated_case_data,
            updated_user_session, llm_instance, messages_to_send, next_actions
        )
    
    elif stage == "awaiting_dispatch_choice":
        return handle_dispatch_choice(
            user_id, message_body, active_case_id, updated_case_data,
            updated_user_session, llm_instance, messages_to_send, next_actions
        )
    
    elif stage == "general":
        return handle_general_inquiry(
            user_id, message_body, updated_user_session, messages_to_send
        )
    
    else:
        logger.warning(f"⚠️ User is in unhandled stage '{stage}'. Message: {message_body}")
        return {"status": "NoAction"}


def handle_delivery_inquiry(user_id, message_body, active_case_id, updated_case_data, 
                          updated_user_session, messages_to_send, next_actions):
    """Handle delivery status inquiries"""
    if not active_case_id or not updated_case_data:
        logger.error("❌ No active case for user in awaiting_delivery stage")
        return {
            "status": "Error",
            "error": "No active case or case data found for this user to inquire about delivery."
        }
    
    patient_name = updated_case_data.get("patient_name", "your patient")
    delivery_status = updated_case_data.get("delivery_status", "Info not available")
    
    logger.info(f"📦 Dentist inquired about delivery. Current status: '{delivery_status}'")

    if delivery_status and delivery_status.lower() == "delivered":
        # Auto-progress to fit confirmation
        messages_to_send.append({
            "recipient_id": user_id,
            "content": f"Great news! Our records show the training aligner for {patient_name} has been delivered.\n\nPlease check the fit and let us know: Does the aligner fit correctly? (Yes/No)"
        })
        updated_case_data["status"] = "AwaitingFitConfirmation"
        updated_user_session["current_stage"] = "awaiting_fit_confirmation"
        next_actions.append("follow_up_fit_confirmation")
    else:
        messages_to_send.append({
            "recipient_id": user_id,
            "content": f"Hi Doctor! The current status for the aligner for {patient_name} is: {delivery_status}.\n\nWe'll notify you as soon as it's delivered."
        })
    
    return {"status": "Success"}


def handle_fit_confirmation(user_id, message_body, active_case_id, updated_case_data,
                          updated_user_session, llm_instance, messages_to_send, next_actions):
    """Handle fit confirmation responses using LLM"""
    if not active_case_id:
        return {
            "status": "Error",
            "error": "No active case found for this user to confirm fit."
        }
    
    logger.info(f"🦷 Processing fit confirmation: '{message_body}'")
    
    # Enhanced prompt for better classification
    prompt = PromptTemplate(
        input_variables=["user_response"],
        template="""You are helping classify a dentist's response about whether a dental aligner fits correctly.

The dentist was asked: "Does the aligner fit correctly?"
Their response: "{user_response}"

Classify this response as one of:
- "Yes" if they confirm it fits well/correctly/properly
- "No" if they say it doesn't fit/has issues/needs adjustment  
- "Unknown" if unclear or asking for more information

Respond with only one word: Yes, No, or Unknown.

Classification:"""
    )
    
    try:
        chain = LLMChain(llm=llm_instance, prompt=prompt)
        fit_confirmation = chain.run(user_response=message_body).strip().lower()
        logger.info(f"🤖 LLM classified fit as: '{fit_confirmation}'")

        patient_name = updated_case_data.get("patient_name", "your patient")

        if "yes" in fit_confirmation:
            messages_to_send.append({
                "recipient_id": user_id,
                "content": f"Excellent! The training aligner fits well.\n\nFor the full treatment aligners for {patient_name}, would you prefer:\n\n1️⃣ Phase-Wise delivery (receive aligners in phases)\n2️⃣ Full Case delivery (receive all aligners at once)\n\nPlease reply with 'Phase-Wise' or 'Full Case'."
            })
            updated_user_session["current_stage"] = "awaiting_dispatch_choice"
            next_actions.append("prepare_production_options")
            
        elif "no" in fit_confirmation:
            messages_to_send.append({
                "recipient_id": user_id,
                "content": f"Thank you for the feedback. We understand the training aligner for {patient_name} needs adjustment.\n\nA member of our clinical team will contact you within 24 hours to discuss the next steps."
            })
            updated_case_data["status"] = "FitIssueReported"
            updated_case_data["fit_issue_reported_at"] = int(time.time())
            updated_user_session["current_stage"] = "general"
            next_actions.append("escalate_to_clinical_team")
            
        else:
            messages_to_send.append({
                "recipient_id": user_id,
                "content": "I apologize, I didn't quite understand your response.\n\nRegarding the training aligner fit, could you please confirm:\n\n✅ Yes - it fits correctly\n❌ No - it has fit issues\n\nA simple 'Yes' or 'No' would be helpful."
            })
        
        return {"status": "Success"}
        
    except Exception as e:
        logger.error(f"❌ LLM error during fit confirmation: {e}")
        return {
            "status": "Error",
            "error": f"LLM error during fit confirmation: {e}"
        }


def handle_dispatch_choice(user_id, message_body, active_case_id, updated_case_data,
                         updated_user_session, llm_instance, messages_to_send, next_actions):
    """Handle dispatch choice responses using LLM"""
    if not active_case_id:
        return {
            "status": "Error",
            "error": "No active case found for this user to confirm dispatch choice."
        }
    
    logger.info(f"📦 Processing dispatch choice: '{message_body}'")
    
    prompt = PromptTemplate(
        input_variables=["user_response"],
        template="""You are helping classify a dentist's choice for aligner delivery method.

The dentist was asked to choose between "Phase-Wise" or "Full Case" delivery.
Their response: "{user_response}"

Classify this response as:
- "PhaseWise" if they want phase-wise delivery, stepped delivery, gradual delivery, or multiple shipments
- "FullCase" if they want full case, all at once, complete set, or single delivery
- "Unknown" if unclear or asking for more information

Respond with only one word: PhaseWise, FullCase, or Unknown.

Choice:"""
    )
    
    try:
        chain = LLMChain(llm=llm_instance, prompt=prompt)
        dispatch_choice = chain.run(user_response=message_body).strip().lower()
        logger.info(f"🤖 LLM classified dispatch choice as: '{dispatch_choice}'")

        patient_name = updated_case_data.get("patient_name", "your patient")
        new_status = None
        
        if "phasewise" in dispatch_choice:
            new_status = "FitConfirmed_PhaseWise"
            messages_to_send.append({
                "recipient_id": user_id,
                "content": f"Perfect! We'll prepare the phase-wise delivery for {patient_name}. You'll receive the first phase soon, followed by subsequent phases as treatment progresses."
            })
            next_actions.append("schedule_phase_wise_production")
            
        elif "fullcase" in dispatch_choice:
            new_status = "FitConfirmed_FullCase"
            messages_to_send.append({
                "recipient_id": user_id,
                "content": f"Excellent! We'll prepare the complete set of aligners for {patient_name}. All aligners will be delivered together."
            })
            next_actions.append("schedule_full_case_production")

        if new_status:
            updated_case_data["status"] = new_status
            updated_case_data["delivery_choice_confirmed_at"] = int(time.time())
            updated_user_session["current_stage"] = "general"
            logger.info(f"✅ Updated status to: {new_status}")
        else:
            messages_to_send.append({
                "recipient_id": user_id,
                "content": "I'm not sure which delivery option you'd prefer.\n\nPlease choose one of the following:\n\n1️⃣ 'Phase-Wise' - Receive aligners in phases\n2️⃣ 'Full Case' - Receive all aligners at once\n\nPlease reply with exactly 'Phase-Wise' or 'Full Case'."
            })
        
        return {"status": "Success"}
        
    except Exception as e:
        logger.error(f"❌ LLM error during dispatch choice: {e}")
        return {
            "status": "Error", 
            "error": f"LLM error during dispatch choice: {e}"
        }


def handle_general_inquiry(user_id, message_body, updated_user_session, messages_to_send):
    """Handle general inquiries and provide helpful information"""
    logger.info(f"💬 Handling general inquiry: '{message_body}'")
    
    # Simple keyword-based responses for common inquiries
    message_lower = message_body.lower()
    
    if any(word in message_lower for word in ['hello', 'hi', 'hey', 'good morning', 'good afternoon']):
        response = "Hello! Welcome to our dental aligner service. How can I assist you today?\n\n• Check delivery status\n• Report fit issues\n• General questions about your case"
        
    elif any(word in message_lower for word in ['status', 'update', 'progress', 'where']):
        response = "I'd be happy to help you check the status of your case. Could you please provide your case ID or patient name?"
        
    elif any(word in message_lower for word in ['delivery', 'shipped', 'tracking']):
        response = "For delivery updates, I can check the current status of your shipment. Do you have an active case you'd like me to look up?"
        
    elif any(word in message_lower for word in ['help', 'support', 'assistance']):
        response = "I'm here to help! I can assist with:\n\n✅ Delivery status updates\n✅ Fit confirmation\n✅ General case information\n✅ Connect you with our clinical team\n\nWhat would you like help with?"
        
    else:
        response = "Thank you for your message. I'm here to help with your aligner cases.\n\nIf you need immediate assistance, please contact our support team, or let me know how I can help you today!"
    
    messages_to_send.append({
        "recipient_id": user_id,
        "content": response
    })
    
    return {"status": "Success"}

# ==============================================================================
# SECTION 3: MAIN WORKFLOW FUNCTION
# ==============================================================================