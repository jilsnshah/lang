# production_logic.py

import os
from dotenv import load_dotenv
from twilio.rest import Client
import firebase_admin
from firebase_admin import db

# ==============================================================================
# 1. INITIALIZATION
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

# --- Service Clients ---
twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
db_root = db.reference('/')
cases_ref = db_root.child('cases')
user_sessions_ref = db_root.child('user_sessions')

# ==============================================================================
# 2. MESSAGE TEMPLATES (From PDF)
# ==============================================================================

# Aligner Fabrication Message (Page 9)
ALIGNER_FABRICATION_MSG = """Dear Doctor,
Greetings !!!

This is to inform you that the process of Aligner Fabrication has been initiated for your case.

Patient Name :- {patient_name}

Dispatch details will soon be provided to you.

Regards...
Team - 3D Align"""

# Dispatch Details Message (Page 10)
DISPATCH_DETAILS_MSG = """Dear Doctor,
Greetings !!!

Thank you for your valuable support.

Please take a note of details of your shipment :-

Patient Name :- {patient_name}
Consignment Items :- {consignment_items}
Tracking ID :- {tracking_id}
Tracking Site :- {tracking_site}

In case if shipment is not delivered to you within 2-4 days of dispatch than please revert back to us.

Regards...
Team - 3D Align"""

# Training Aligner Fit Confirmation Message (Page 8)
TRAINING_ALIGNER_FIT_CONFIRM_MSG = """Dear Doctor,
Greetings !!!

We would like to know the fit of training aligner sent to you for
Patient Name :- {patient_name}

Also please let us know whether we should go ahead for the fabrication of remaining sets of aligner ?

Please Note :-
Remaining sets of aligner will be dispatched within a week upon confirmation received for the case.

Regards...
Team - 3D Align"""


# ==============================================================================
# 3. PRODUCTION WORKFLOW FUNCTIONS
# ==============================================================================

def start_case_planning(user_id: str, case_id: str, patient_name: str):
    """
    Step 1: Intimates the dentist that case planning has begun.
    - user_id: The dentist's WhatsApp ID (e.g., 'whatsapp:+91...')
    - case_id: The unique ID for the case.
    - patient_name: The name of the patient.
    """
    try:
        message_body = f"Dear Doctor, planning for patient '{patient_name}' (Case ID: {case_id}) has started. We will keep you updated."

        twilio_client.messages.create(
            from_=TWILIO_WHATSAPP_NUMBER,
            to=user_id,
            body=message_body
        )

        # Update case status in Firebase
        cases_ref.child(case_id).update({'status': 'CasePlanning'})
        print(f"Successfully sent 'Case Planning' intimation for case {case_id} to {user_id}.")
        return True
    except Exception as e:
        print(f"ERROR in start_case_planning for case {case_id}: {e}")
        return False


def dispatch_training_aligner(user_id: str, case_id: str, patient_name: str, tracking_id: str, tracking_site: str):
    """
    Step 2: Dispatches the training aligner and asks the dentist for fit confirmation.
    """
    try:
        # First, send the dispatch details for the training aligner
        dispatch_message = DISPATCH_DETAILS_MSG.format(
            patient_name=patient_name,
            consignment_items="Training Aligner Set",
            tracking_id=tracking_id,
            tracking_site=tracking_site
        )
        twilio_client.messages.create(
            from_=TWILIO_WHATSAPP_NUMBER,
            to=user_id,
            body=dispatch_message
        )
        print(f"Sent 'Training Aligner Dispatch Details' for case {case_id} to {user_id}.")

        # Second, send the fit confirmation request message
        fit_confirm_message = TRAINING_ALIGNER_FIT_CONFIRM_MSG.format(patient_name=patient_name)
        twilio_client.messages.create(
            from_=TWILIO_WHATSAPP_NUMBER,
            to=user_id,
            body=fit_confirm_message
        )
        print(f"Sent 'Training Aligner Fit Confirmation Request' for case {case_id} to {user_id}.")

        # Update Firebase state
        cases_ref.child(case_id).update({
            'status': 'AwaitingFitConfirmation',
            'tracking_id_training': tracking_id
        })
        user_sessions_ref.child(user_id).update({
            'current_stage': 'awaiting_fit_confirmation',
            'active_case_for_confirmation': case_id  # Critical for the webhook to know which case this is for
        })

        print(f"Successfully updated status for case {case_id} and user {user_id} to 'awaiting_fit_confirmation'.")
        return True
    except Exception as e:
        print(f"ERROR in dispatch_training_aligner for case {case_id}: {e}")
        return False


def start_full_case_fabrication(user_id: str, case_id: str, patient_name: str):
    """
    Step 3: Called after dentist confirms fit. Intimates that main fabrication has started.
    """
    try:
        message_body = ALIGNER_FABRICATION_MSG.format(patient_name=patient_name)

        twilio_client.messages.create(
            from_=TWILIO_WHATSAPP_NUMBER,
            to=user_id,
            body=message_body
        )

        # Update case status and clear user's waiting stage
        cases_ref.child(case_id).update({'status': 'FullCaseFabrication'})
        user_sessions_ref.child(user_id).update({
            'current_stage': 'intent',  # Reset user to a neutral state
            'active_case_for_confirmation': None
        })

        print(f"Successfully sent 'Full Case Fabrication' intimation for case {case_id} to {user_id}.")
        return True
    except Exception as e:
        print(f"ERROR in start_full_case_fabrication for case {case_id}: {e}")
        return False


def dispatch_full_case(user_id: str, case_id: str, patient_name: str, consignment_items: str, tracking_id: str,
                       tracking_site: str):
    """
    Step 4: Dispatches the full set of aligners and provides final tracking details.
    """
    try:
        message_body = DISPATCH_DETAILS_MSG.format(
            patient_name=patient_name,
            consignment_items=consignment_items,
            tracking_id=tracking_id,
            tracking_site=tracking_site
        )

        twilio_client.messages.create(
            from_=TWILIO_WHATSAPP_NUMBER,
            to=user_id,
            body=message_body
        )

        # Update case status to final state
        cases_ref.child(case_id).update({
            'status': 'CompletedAndDispatched',
            'tracking_id_final': tracking_id
        })

        print(f"Successfully sent 'Full Case Dispatch' details for case {case_id} to {user_id}.")
        return True
    except Exception as e:
        print(f"ERROR in dispatch_full_case for case {case_id}: {e}")
        return False


def alert_team_on_fit_issue(user_id: str, case_id: str, patient_name: str, dentist_message: str):
    """
    Alerts the internal team if the dentist reports a fit issue.
    """
    try:
        alert_body = (
            f"🚨 FIT ISSUE ALERT 🚨\n\n"
            f"Dentist: {user_id}\n"
            f"Case ID: {case_id}\n"
            f"Patient: {patient_name}\n\n"
            f"Dentist's Message: '{dentist_message}'\n\n"
            f"Please contact the dentist immediately to resolve the issue."
        )

        twilio_client.messages.create(
            from_=TWILIO_WHATSAPP_NUMBER,
            to=FORWARD_TO_WHATSAPP_NUMBER,  # Sending to internal team number
            body=alert_body
        )

        # Update case status and clear user's waiting stage
        cases_ref.child(case_id).update({'status': 'FitIssueReported'})
        user_sessions_ref.child(user_id).update({
            'current_stage': 'intent',
            'active_case_for_confirmation': None
        })
        print(f"Successfully alerted team about fit issue for case {case_id}.")
        return True
    except Exception as e:
        print(f"ERROR in alert_team_on_fit_issue for case {case_id}: {e}")
        return False