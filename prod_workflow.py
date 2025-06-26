# production_engine.py

import os
from dotenv import load_dotenv
from twilio.rest import Client
import firebase_admin
from firebase_admin import db

# ==============================================================================
# 1. INITIALIZATION & CONFIGURATION
# ==============================================================================
load_dotenv(override=True)

# --- Twilio Configuration ---
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_NUMBER = os.getenv("TWILIO_WHATSAPP_NUMBER")
FORWARD_TO_WHATSAPP_NUMBER = os.getenv("FORWARD_TO_WHATSAPP_NUMBER")  # For internal alerts

# --- Firebase Initialization Check ---
if not firebase_admin._apps:
    FIREBASE_DATABASE_URL = "https://diesel-ellipse-463111-a5-default-rtdb.asia-southeast1.firebasedatabase.app/"
    firebase_admin.initialize_app(options={'databaseURL': FIREBASE_DATABASE_URL})

# --- Service Clients & DB References ---
twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
db_root = db.reference('/')
# IMPORTANT: We assume a structure like /cases/{case_id}
cases_ref = db_root.child('cases')
user_sessions_ref = db_root.child('user_sessions')

# ==============================================================================
# 2. MESSAGE TEMPLATES (FROM PDF)
# ==============================================================================
# (These are the same as before, collected here for clarity)
ALIGNER_FABRICATION_MSG = """Dear Doctor,\nGreetings !!!\n\nThis is to inform you that the process of Aligner Fabrication has been initiated for your case.\n\nPatient Name :- {patient_name}\n\nDispatch details will soon be provided to you.\n\nRegards...\nTeam - 3D Align"""
DISPATCH_DETAILS_MSG = """Dear Doctor,\nGreetings !!!\n\nThank you for your valuable support.\n\nPlease take a note of details of your shipment :-\n\nPatient Name :- {patient_name}\nConsignment Items :- {consignment_items}\nTracking ID :- {tracking_id}\nTracking Site :- {tracking_site}\n\nIn case if shipment is not delivered to you within 2-4 days of dispatch than please revert back to us.\n\nRegards...\nTeam - 3D Align"""
TRAINING_ALIGNER_FIT_CONFIRM_MSG = """Dear Doctor,\nGreetings !!!\n\nWe would like to know the fit of training aligner sent to you for\nPatient Name :- {patient_name}\n\nAlso please let us know whether we should go ahead for the fabrication of remaining sets of aligner ?\n\nPlease Note :-\nRemaining sets of aligner will be dispatched within a week upon confirmation received for the case.\n\nRegards...\nTeam - 3D Align"""


# ==============================================================================
# 3. THE SINGULAR WORKFLOW ENGINE FUNCTION
# ==============================================================================

def advance_production_workflow(case_id: str, **kwargs):
    """
    Advances a case to its next logical step in the production workflow.
    This is the main function your internal system will call.

    Args:
        case_id (str): The unique ID of the case to process.
        **kwargs: Optional arguments needed for specific steps, e.g.,
                  tracking_id="...", tracking_site="..."

    Returns:
        str: A message indicating the action taken or the current status.
    """
    print(f"\n--- Advancing workflow for Case ID: {case_id} ---")

    # 1. Fetch case data from Firebase
    case_data = cases_ref.child(case_id).get()
    if not case_data:
        return f"ERROR: Case ID '{case_id}' not found in Firebase."

    current_status = case_data.get('status', 'new')
    user_id = case_data.get('user_id')  # Assumes user_id is stored in the case
    patient_name = case_data.get('name')

    if not all([user_id, patient_name]):
        return f"ERROR: Case '{case_id}' is missing 'user_id' or 'name' in Firebase."

    print(f"Current status: '{current_status}'")

    # 2. State Machine Logic (if/elif based on current status)

    # === INITIAL STEP ===
    if current_status == 'ApprovedForProduction':
        message_body = f"Dear Doctor, planning for patient '{patient_name}' (Case ID: {case_id}) has started. We will keep you updated."
        twilio_client.messages.create(to=user_id, from_=TWILIO_WHATSAPP_NUMBER, body=message_body)
        cases_ref.child(case_id).update({'status': 'CasePlanning'})
        return f"Action: Sent 'Case Planning' notification to {user_id}. Status updated to 'CasePlanning'."

    # === STEP AFTER PLANNING ===
    elif current_status == 'CasePlanning':
        tracking_id = kwargs.get('tracking_id')
        tracking_site = kwargs.get('tracking_site')
        if not all([tracking_id, tracking_site]):
            return f"ERROR: For status 'CasePlanning', you must provide 'tracking_id' and 'tracking_site' for the training aligner."

        # Send dispatch details
        dispatch_message = DISPATCH_DETAILS_MSG.format(patient_name=patient_name,
                                                       consignment_items="Training Aligner Set",
                                                       tracking_id=tracking_id, tracking_site=tracking_site)
        twilio_client.messages.create(to=user_id, from_=TWILIO_WHATSAPP_NUMBER, body=dispatch_message)

        # Send fit confirmation request
        fit_confirm_message = TRAINING_ALIGNER_FIT_CONFIRM_MSG.format(patient_name=patient_name)
        twilio_client.messages.create(to=user_id, from_=TWILIO_WHATSAPP_NUMBER, body=fit_confirm_message)

        # Update case and user states
        cases_ref.child(case_id).update({'status': 'TrainingAlignerDispatched', 'tracking_id_training': tracking_id})
        user_sessions_ref.child(user_id).update(
            {'current_stage': 'awaiting_fit_confirmation', 'active_case_for_confirmation': case_id})
        return f"Action: Dispatched training aligner for case {case_id}. Waiting for dentist fit confirmation."

    # === STEP AFTER DENTIST CONFIRMS FIT ===
    elif current_status == 'FitConfirmed':
        message_body = ALIGNER_FABRICATION_MSG.format(patient_name=patient_name)
        twilio_client.messages.create(to=user_id, from_=TWILIO_WHATSAPP_NUMBER, body=message_body)
        cases_ref.child(case_id).update({'status': 'FullCaseFabrication'})
        return f"Action: Sent 'Full Fabrication' notification to {user_id}. Status updated to 'FullCaseFabrication'."

    # === STEP AFTER FULL FABRICATION ===
    elif current_status == 'FullCaseFabrication':
        tracking_id = kwargs.get('tracking_id')
        tracking_site = kwargs.get('tracking_site')
        consignment_items = kwargs.get('consignment_items', 'Full Aligner Set')
        if not all([tracking_id, tracking_site]):
            return f"ERROR: For status 'FullCaseFabrication', you must provide 'tracking_id' and 'tracking_site' for the final dispatch."

        message_body = DISPATCH_DETAILS_MSG.format(patient_name=patient_name, consignment_items=consignment_items,
                                                   tracking_id=tracking_id, tracking_site=tracking_site)
        twilio_client.messages.create(to=user_id, from_=TWILIO_WHATSAPP_NUMBER, body=message_body)
        cases_ref.child(case_id).update({'status': 'Completed', 'tracking_id_final': tracking_id})
        return f"Action: Dispatched full case for case {case_id}. Status updated to 'Completed'."

    # === WAITING OR END STATES ===
    elif current_status == 'TrainingAlignerDispatched':
        return "Info: Case is currently waiting for the dentist to confirm the training aligner fit. No action taken."

    elif current_status == 'FitIssueReported':
        return "Info: Dentist reported a fit issue. Case requires manual intervention. No action taken."

    elif current_status == 'Completed':
        return "Info: This case has already been completed. No further action can be taken."

    else:
        return f"Warning: Case '{case_id}' has an unknown status: '{current_status}'. No action taken."