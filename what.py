import json
import time
import requests
from flask import Flask, request, jsonify
import os
from dotenv import load_dotenv
from prod_workflow import dental_aligner_workflow
from langchain_openai import ChatOpenAI
from google_sheets_manager import GoogleSheetsManager

# Load environment variables
load_dotenv()

app = Flask(__name__)

# ------------------------------------------------------------------
# 🔐 Meta Credentials (replace with your actual credentials)  
# ------------------------------------------------------------------
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "your_verify_token_here")
ACCESS_TOKEN = os.getenv("ACCESS_TOKEN", "your_access_token_here") 
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID", "your_phone_number_id_here")

# Initialize LLM for workflow
llm = ChatOpenAI(
    model_name="gpt-3.5-turbo",
    openai_api_key=os.getenv("OPENAI_API_KEY"),
    temperature=0.1
)

# Initialize Google Sheets Manager
sheets_manager = GoogleSheetsManager()

# In-memory storage (replace with proper database in production)
cases_db = {}
user_sessions = {}
custom_reply_text = "Hello! Welcome to [Aligner Company]. How can I assist you today?"

# ------------------------------------------------------------------
# 1. Webhook Verification (GET)
# ------------------------------------------------------------------
@app.route("/webhook", methods=["GET"])
def verify():
    if (
        request.args.get("hub.mode") == "subscribe"
        and request.args.get("hub.verify_token") == VERIFY_TOKEN
    ):
        return request.args.get("hub.challenge"), 200
    return "Verification failed", 403

# ------------------------------------------------------------------
# 2. Webhook Receiver (POST) - Enhanced with Workflow Integration
# ------------------------------------------------------------------
@app.route("/webhook", methods=["POST"])
def receive_message():
    data = request.get_json()
    print("📥 Incoming Data:\n", json.dumps(data, indent=2))

    try:
        for entry in data.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                messages = value.get("messages", [])
                for message in messages:
                    sender = message.get("from")
                    text = message.get("text", {}).get("body", "")
                    timestamp = int(message.get("timestamp"))

                    print(f"📩 Message from {sender}: {text} @ {timestamp}")

                    # Process message through workflow
                    result = process_dentist_message(sender, text, timestamp)
                    
                    # Send responses
                    for msg in result.get("messages_to_send", []):
                        send_whatsapp_text(msg["recipient_id"], msg["content"])

    except Exception as e:
        print("❌ Error:", e)

    return "EVENT_RECEIVED", 200

# ------------------------------------------------------------------
# 3. Process Dentist Message through Workflow
# ------------------------------------------------------------------
def process_dentist_message(user_id, message_body, timestamp):
    """Process incoming message through the dental workflow"""
    
    # Get or create user session
    if user_id not in user_sessions:
        user_sessions[user_id] = {
            "user_id": user_id,
            "current_stage": "general",
            "active_case": None,
            "last_message_time": timestamp
        }
    
    user_sessions[user_id]["last_message_time"] = timestamp
    
    # Get active case data if exists
    active_case_id = user_sessions[user_id].get("active_case")
    current_case_data = cases_db.get(active_case_id) if active_case_id else None
    
    # Process through workflow
    result = dental_aligner_workflow(
        action_type="process_message",
        llm_instance=llm,
        user_id=user_id,
        message_body=message_body,
        current_case_data=current_case_data,
        current_user_session=user_sessions[user_id]
    )
    
    # Update local storage
    if result["updated_case_data"]:
        case_id = result["updated_case_data"].get("id") or active_case_id
        if case_id:
            cases_db[case_id] = result["updated_case_data"]
    
    user_sessions[user_id] = result["updated_user_session"]
    
    return result

# ------------------------------------------------------------------
# 4. Start Production Step - API Endpoint
# ------------------------------------------------------------------
@app.route("/start-production", methods=["POST"])
def start_production():
    """API endpoint to trigger production steps"""
    data = request.get_json()
    case_id = data.get("case_id")
    
    if not case_id or case_id not in cases_db:
        return {"error": "Case not found"}, 404
    
    result = dental_aligner_workflow(
        action_type="start_production",
        llm_instance=llm,
        case_id=case_id,
        current_case_data=cases_db[case_id],
        current_user_session=user_sessions.get(cases_db[case_id].get("user_id"), {})
    )
    
    # Update storage
    if result["updated_case_data"]:
        cases_db[case_id] = result["updated_case_data"]
    
    # Send messages
    for msg in result.get("messages_to_send", []):
        send_whatsapp_text(msg["recipient_id"], msg["content"])
    
    return {"message": "Production step triggered", "status": result["status"]}, 200

# ------------------------------------------------------------------
# 5. Google Sheets Integration - Customer Management
# ------------------------------------------------------------------
@app.route("/sync-customers", methods=["POST"])
def sync_customers():
    """Sync customer data from Google Sheets"""
    try:
        customers = sheets_manager.get_customers()
        
        # Update cases_db with customer data
        for customer in customers:
            case_id = customer.get("case_id")
            if case_id:
                if case_id not in cases_db:
                    cases_db[case_id] = {}
                cases_db[case_id].update(customer)
        
        return {"message": f"Synced {len(customers)} customers", "customers": customers}, 200
    except Exception as e:
        return {"error": str(e)}, 500

@app.route("/update-case-status", methods=["POST"])
def update_case_status():
    """Update case status in Google Sheets"""
    data = request.get_json()
    case_id = data.get("case_id")
    status = data.get("status")
    
    if not case_id or not status:
        return {"error": "case_id and status required"}, 400
    
    try:
        sheets_manager.update_case_status(case_id, status)
        
        # Update local storage
        if case_id in cases_db:
            cases_db[case_id]["status"] = status
        
        return {"message": "Status updated successfully"}, 200
    except Exception as e:
        return {"error": str(e)}, 500

@app.route("/create-case", methods=["POST"])
def create_case():
    """Create new case"""
    data = request.get_json()
    
    case_id = data.get("case_id")
    if not case_id:
        case_id = f"case-{int(time.time())}"
    
    case_data = {
        "id": case_id,
        "user_id": data.get("user_id"),
        "patient_name": data.get("patient_name"),
        "dentist_name": data.get("dentist_name"),
        "status": data.get("status", "ApprovedForProduction"),
        "created_at": int(time.time())
    }
    
    # Save to local storage
    cases_db[case_id] = case_data
    
    # Save to Google Sheets
    try:
        sheets_manager.add_case(case_data)
        return {"message": "Case created successfully", "case_id": case_id}, 201
    except Exception as e:
        return {"error": str(e)}, 500

# ------------------------------------------------------------------
# 6. Enhanced WhatsApp Messaging
# ------------------------------------------------------------------
def send_whatsapp_text(recipient_number, text):
    """Send WhatsApp message with 24-hour window check"""
    user_session = user_sessions.get(recipient_number, {})
    last_time = user_session.get("last_message_time")
    now = int(time.time())

    if last_time and (now - last_time) <= 86400:  # 24 hour window
        url = f"https://graph.facebook.com/v22.0/{PHONE_NUMBER_ID}/messages"
        headers = {
            "Authorization": f"Bearer {ACCESS_TOKEN}",
            "Content-Type": "application/json"
        }
        payload = {
            "messaging_product": "whatsapp",
            "to": recipient_number,
            "type": "text",
            "text": {
                "body": text
            }
        }

        res = requests.post(url, headers=headers, json=payload)
        print(f"📤 Sent to {recipient_number}: {text}")
        print("✅ Status:", res.status_code)
        print("📄 Response:", res.text)
        
        return res.status_code == 200
    else:
        print(f"⏰ Cannot send to {recipient_number} - outside 24h window")
        return False

# ------------------------------------------------------------------
# 7. Admin Interface Endpoints
# ------------------------------------------------------------------
@app.route("/admin/cases", methods=["GET"])
def get_all_cases():
    """Get all cases for admin dashboard"""
    return {"cases": list(cases_db.values())}, 200

@app.route("/admin/users", methods=["GET"])
def get_all_users():
    """Get all user sessions"""
    return {"users": list(user_sessions.values())}, 200

@app.route("/set-reply", methods=["POST"])
def set_reply():
    """Set custom default reply"""
    global custom_reply_text
    data = request.get_json()
    reply = data.get("reply")
    if reply:
        custom_reply_text = reply
        return {"message": "Reply updated successfully."}, 200
    return {"error": "No reply text provided."}, 400

# ------------------------------------------------------------------
# 8. Run Flask App
# ------------------------------------------------------------------
if __name__ == "__main__":
    print("🚀 Starting Dental Aligner Production System...")
    print("📋 Available endpoints:")
    print("  - POST /webhook (WhatsApp messages)")
    print("  - POST /start-production (trigger production steps)")
    print("  - POST /sync-customers (sync from Google Sheets)")
    print("  - POST /create-case (create new case)")
    print("  - GET /admin/cases (view all cases)")
    
    app.run(host="0.0.0.0", port=5000, debug=True)
