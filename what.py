import json
import time
import requests
from flask import Flask, request

app = Flask(__name__)

# Your Meta Credentials
VERIFY_TOKEN = "12345"
ACCESS_TOKEN = "EAARccu1imkYBO2STiRKXf4dfy4THn8eqzDrpZBHJWcBfWe8egFge6jKpCcchbrbz49nJiDdDDorzWNtbsolZAo6i9Dy2dBJ9gYGCj5A073h2Pu0htDLXC7OotKzCrb5m2Wc2wsHJZC9mTYftVf5nWgM37eK35WvjMZA8vcoVW5105kej127KgR3bDl0GfV1mNUfKjVfwbm8jwoX1vuz9fZA0U8Qe47zg51EUQNtdFjHZBX7ckkkfwbQhUMFyPdaNsZD"  # Your token
PHONE_NUMBER_ID = "658311557373737"

# In-memory user last-message tracker
# Format: { "wa_id": last_timestamp_in_seconds }
user_last_message = {}

# ------------------------------------------------------------------
# 1. Verify Webhook (GET)
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
# 2. Receive Messages (POST)
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
                    text = message.get("text", {}).get("body")
                    timestamp = int(message.get("timestamp"))  # Unix seconds

                    print(f"📩 Message from {sender}: {text} @ {timestamp}")

                    # Save/update the user's last contact time
                    user_last_message[sender] = timestamp

                    # ✅ Reply since it's within 24h window
                    send_whatsapp_message(sender, f"You said: {text}")

    except Exception as e:
        print("❌ Error:", e)

    return "EVENT_RECEIVED", 200

# ------------------------------------------------------------------
# 3. Send Message (Only if within 24-hour window)
# ------------------------------------------------------------------
def send_whatsapp_message(recipient_number, text):
    now = int(time.time())
    last_time = user_last_message.get(recipient_number)

    # Check if user is eligible (within 24h)
    if last_time and (now - last_time) <= 86400:
        url = f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}/messages"
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
if __name__ == "__main__":
    app.run(port=5000, debug=True)
