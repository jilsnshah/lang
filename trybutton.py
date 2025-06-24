import json
import requests
from flask import Flask, request
from requests.auth import HTTPBasicAuth

app = Flask(__name__)

# Replace with your Twilio credentials
ACCOUNT_SID = 'AC8f31dbc6278d7c27badaa8f19f380308'
AUTH_TOKEN = '35c761c63ad1afcb19e03b32d2056c88'
TWILIO_WHATSAPP_NUMBER = 'whatsapp:+14155238886'

@app.route("/whatsapp", methods=["POST"])
def whatsapp_webhook():
    to_number = 'whatsapp:+917801833884'

    url = f"https://api.twilio.com/2010-04-01/Accounts/{ACCOUNT_SID}/Messages.json"

    payload = {
        "To": to_number,
        "From": TWILIO_WHATSAPP_NUMBER,
        "Interactive": json.dumps({
            "type": "button",
            "body": {
                "text": "Do you agree?"
            },
            "action": {
                "buttons": [
                    {
                        "type": "reply",
                        "reply": {
                            "id": "yes_button",
                            "title": "Yes"
                        }
                    },
                    {
                        "type": "reply",
                        "reply": {
                            "id": "no_button",
                            "title": "No"
                        }
                    }
                ]
            }
        })
    }

    response = requests.post(
        url,
        data=payload,
        auth=HTTPBasicAuth(ACCOUNT_SID, AUTH_TOKEN)
    )

    print(f"Twilio API Response: {response.status_code}, {response.text}")
    return "OK", 200
