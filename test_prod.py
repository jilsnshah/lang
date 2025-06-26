# test_production.py

# This is a script to simulate your internal team triggering the production workflow.
# Run this from your terminal: python test_production.py

import prod_workflow
import time

# --- Fill in with actual data for testing ---
TEST_DENTIST_USER_ID = "whatsapp:+91xxxxxxxxxx"  # The dentist's WhatsApp number
TEST_CASE_ID = "case-007"                        # The unique case ID you are tracking
TEST_PATIENT_NAME = "James Bond"

def run_test_workflow():
    print("--- STARTING PRODUCTION WORKFLOW TEST ---")

    # Step 1: Your team starts planning the case.
    print("\n[ACTION] Triggering case planning...")
    production_logic.start_case_planning(TEST_DENTIST_USER_ID, TEST_CASE_ID, TEST_PATIENT_NAME)
    print("Dentist has been notified about case planning. Waiting 5 seconds...")
    time.sleep(5)

    # Step 2: Your team fabricates and dispatches the training aligner.
    print("\n[ACTION] Triggering training aligner dispatch...")
    production_logic.dispatch_training_aligner(
        user_id=TEST_DENTIST_USER_ID,
        case_id=TEST_CASE_ID,
        patient_name=TEST_PATIENT_NAME,
        tracking_id="BLUEDART-12345",
        tracking_site="www.bluedart.com"
    )
    print("Dentist has been notified and asked for fit confirmation.")
    print("NOW, GO TO WHATSAPP AND REPLY 'Yes, it fits perfectly' TO THE BOT.")
    print("The webhook in server.py will handle the response.")
    print("Waiting 30 seconds for you to reply...")
    time.sleep(30) # Gives you time to reply on WhatsApp

    # The `start_full_case_fabrication` is triggered automatically by server.py when you reply 'Yes'.
    # If you reply 'No', the team will be alerted.

    # Step 3: Let's assume you replied 'Yes'. After some time, your team dispatches the full case.
    print("\n[ACTION] Triggering full case dispatch...")
    production_logic.dispatch_full_case(
        user_id=TEST_DENTIST_USER_ID,
        case_id=TEST_CASE_ID,
        patient_name=TEST_PATIENT_NAME,
        consignment_items="Full Aligner Set (1-12)",
        tracking_id="DELHIVERY-67890",
        tracking_site="www.delhivery.com"
    )
    print("Dentist has been notified with final dispatch details.")

    print("\n--- TEST WORKFLOW COMPLETE ---")

if __name__ == "__main__":
    run_test_workflow()