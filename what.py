import json
import time
import requests
from flask import Flask, request

app = Flask(__name__)

# ------------------------------------------------------------------
# 🔐 Meta Credentials (replace with your actual credentials)
# ------------------------------------------------------------------


# In-memory tracker for user message times and custom replies
user_last_message = {}
custom_reply_text = "Hello! This is a default response."

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
# 2. Webhook Receiver (POST)
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

                    # Save last message timestamp
                    user_last_message[sender] = timestamp

                    # Send the custom reply
                    send_whatsapp_text(sender, custom_reply_text)

    except Exception as e:
        print("❌ Error:", e)

    return "EVENT_RECEIVED", 200

# ------------------------------------------------------------------
# 3. Endpoint to Set Custom Reply
# ------------------------------------------------------------------
@app.route("/set-reply", methods=["POST"])
def set_reply():
    global custom_reply_text
    data = request.get_json()
    reply = data.get("reply")
    if reply:
        custom_reply_text = reply
        return {"message": "Reply updated successfully."}, 200
    return {"error": "No reply text provided."}, 400

# ------------------------------------------------------------------
# 4. Send Text Message (within 24-hour window)
# ------------------------------------------------------------------
def send_whatsapp_text(recipient_number, text):
    now = int(time.time())
    last_time = user_last_message.get(recipient_number)

    if last_time and (now - last_time) <= 86400:
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
    else:
        print(f"⏰ Cannot send to {recipient_number} - outside 24h window")

# ------------------------------------------------------------------
# 5. Run Flask App
# ------------------------------------------------------------------
if __name__ == "__main__":
    app.run(port=5000, debug=True)
