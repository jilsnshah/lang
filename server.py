# ==============================================================================
# 1. IMPORTS
# ==============================================================================
import os
import requests
from flask import Flask, request, send_from_directory
from werkzeug.utils import safe_join # Import safe_join from its new location
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client
from dotenv import load_dotenv
import mimetypes
import tempfile
import uuid # For unique file names in temp directory to avoid clashes
import threading # For cleaning up files after a delay
import uuid
import os
import firebase_admin
from firebase_admin import db # Import the Realtime Database service
from firebase_admin import credentials # Generally not needed if using ADC, but good to know
import sys
import time
from datetime import datetime
import re
import json
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_community.chat_models import ChatOllama
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_core.outputs import ChatResult
from typing import Any, List, Optional
import re
from pydantic import Field

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.outputs import ChatResult
from langchain_core.messages import BaseMessage
from typing import List
import re
import prod_workflow
class NoThinkLLMWrapper(BaseChatModel):
    wrapped_llm: BaseChatModel

    @property
    def _llm_type(self) -> str:
        return "no_think_llm"

    def _strip_think_tags(self, text: str) -> str:
        return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()

    def _generate(
        self, messages: List[BaseMessage], stop=None, run_manager=None, **kwargs
    ) -> ChatResult:
        result = self.wrapped_llm._generate(messages, stop=stop, run_manager=run_manager, **kwargs)
        for gen in result.generations:
            gen.message.content = self._strip_think_tags(gen.message.content)
        return result


FIREBASE_DATABASE_URL = "https://diesel-ellipse-463111-a5-default-rtdb.asia-southeast1.firebasedatabase.app/"
firebase_app = None # To hold the initialized Firebase app instance
try:
    # Initialize Firebase Admin SDK using Application Default Credentials.
    # Specify the databaseURL to connect to your Realtime Database instance.
    firebase_app = firebase_admin.initialize_app(
        options={'databaseURL': FIREBASE_DATABASE_URL}
    )
    print(f"Firebase app initialized successfully for Realtime Database: '{FIREBASE_DATABASE_URL}'.")
except Exception as e:
    print(f"ERROR: Could not initialize Firebase Admin SDK or connect to Realtime Database.")
    print(f"Please ensure you have replaced 'YOUR_REALTIME_DATABASE_URL_HERE' with your actual URL,")
    print(f"and that ADC are configured and billing is enabled for your project.")
    print(f"Error details: {e}")
    sys.exit(1) # Exit if initialization fails, as the app can't function

# Get a reference to the root of the database
# All operations start from this reference
root_ref = db.reference('/')

bot_response =""
# Import the necessary functions and components from your mainlogic.py
from mainlogic import (
    get_calendar_service_oauth,
    create_tools,
    ChatOpenAI,
    hub,
    Tool,
    create_structured_chat_agent,
    AgentExecutor,
    ConversationBufferMemory,
    SystemMessage,
    HumanMessage,
    AIMessage,
    StrOutputParser,
    ChatPromptTemplate,
    RunnableBranch,
    RunnableLambda,
    RunnableMap,
    ls,
    sl,
    get_drive,
    upload_drive
)
output_parser = StrOutputParser()
# ==============================================================================
# 2. CONFIGURATION AND INITIALIZATION
# ==============================================================================
load_dotenv(override=True) # This line should be at the very top of your configuration section

app = Flask(__name__)


# Add these lines temporarily for debugging
print(f"Loaded TWILIO_ACCOUNT_SID: {os.getenv('TWILIO_ACCOUNT_SID')}")
print(f"Loaded TWILIO_AUTH_TOKEN: {os.getenv('TWILIO_AUTH_TOKEN')}")
print(f"Loaded NGROK_URL: {os.getenv('NGROK_URL')}")
# ... rest of your code ...
# --- Twilio Configuration ---
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_NUMBER = os.getenv("TWILIO_WHATSAPP_NUMBER")
FORWARD_TO_WHATSAPP_NUMBER = os.getenv("FORWARD_TO_WHATSAPP_NUMBER")
print(TWILIO_WHATSAPP_NUMBER)
twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# --- Temporary storage for media files ---
MEDIA_TEMP_DIR = os.path.join(tempfile.gettempdir(), "twilio_media_bot")
os.makedirs(MEDIA_TEMP_DIR, exist_ok=True)
print(f"Temporary media directory: {MEDIA_TEMP_DIR}")
user_sessions_fb = root_ref.child('user_sessions')


# --- LLM Initialization (from mainlogic.py) ---
llm = ChatOpenAI(
    model_name="deepseek/deepseek-r1-0528:free",
    openai_api_key=os.getenv("OPENROUTER_API_KEY"), # Assuming your .env has TOGETHER_API_KEY
    openai_api_base="https://openrouter.ai/api/v1",
)

#llm = ChatGoogleGenerativeAI(model="gemini-2.0-flash", temperature=0.3)
#llm = ChatOllama(model="deepseek-r1:7b")
#llm = NoThinkLLMWrapper(wrapped_llm=llm)
model = llm
#======================================
#intent prompts
intent_classification_prompt = ChatPromptTemplate.from_messages([
            ("system", "You are an helpful assistant"),
            ("human", """You are an AI assistant for 3D Align, and your job is to classify the intent of the user's message into one of the following four categories:

1. New Aligner Case Inquiry - for dentists or users who want to submit, inquire or require quotation about a **new aligner case** .
2. Existing Aligner Case Trouble-Shoot - for issues, complaints, or help needed for an **ongoing or completed aligner case**.
3. Aligner By-Products - for questions about **products related to aligner use**, such as chewies, aligner cases, cleaning kits, etc.
4. Finances Related Query - for queries involving **payments, invoices, pricing, or refunds**.

Respond with only the **exact name** of the category that best matches the user's message. If the message is unclear or does not match any, respond with: `Unclear Intent`.

---

User Message: {input}

---

Intent:""")
        ])
express_prompt = ChatPromptTemplate.from_template(
    """You are a helpful assistant that classifies doctor responses into three categories based on urgency.

Categories:
- "express" - if the doctor clearly indicates urgency or requests faster processing.
- "normal" - if the doctor accepts standard processing time or shows no urgency.
- "unrelated" - if the response is not related to urgency or turnaround time at all.

Classify the following doctor response into one of these categories.

Response: "{input}"

Classification (express/normal/unrelated):"""
)
intent_chain = intent_classification_prompt | llm | output_parser
confirm_prompt = ChatPromptTemplate.from_messages([
    ("system", "You are an AI assistant that analyzes user responses."),
    ("human", """You are given a yes-or-no question and a user's response.

Task:
- Determine if the user's response indicates **Yes** or **No**.
- If the response is unclear or ambiguous, return `Unknown`.
- Respond with **only one word**: Yes, No, or Unknown.

Question: {question}
User's Response: {input}
""")
])
confirm_chain = confirm_prompt | llm | output_parser
new_aligner_case_prompt = ChatPromptTemplate.from_messages([
    ("human","""You are an intent classifier for a dental aligner assistant chatbot.  
Your job is to classify the user's response into one of the following intents:

1. **submit_case** - if the user wants to directly submit the aligner case.
2. **request_quotation** - if the user wants a quotation before proceeding.
3. **other** - if the user's message does not match either of the above intents.

Classify the intent based on the user's message.  
Respond with only the intent label (`submit_case`, `request_quotation`, or `other`) and nothing else.

Examples:
- "I want to go ahead and submit the case." → `submit_case`
- "Can I get a quotation first?" → `request_quotation`
- "Can you help me with something else?" → `other`

Now classify this message:
{user_input}""")])
new_aligner_case_chain = new_aligner_case_prompt | llm | output_parser
express_chain = express_prompt | llm | output_parser
choose_prompt = ChatPromptTemplate.from_template("""
You are a helpful assistant for a dental aligner service. Classify the user's message into one of the following categories:

1. "submit_scan" - if the user already has an intraoral scan or PVS impression and wants to send or submit it.
2. "schedule_scan" - if the user wants to schedule an intraoral scan or is asking about booking one.
3. "unrelated" - if the message does not clearly match either of the above.

User message: "{input}"

Respond with only one of these three labels: submit_scan, schedule_scan, or unrelated.
""")
choose_chain = choose_prompt | llm | StrOutputParser()
# --- Global state for each user (for simplicity; ideally use a database) ---

# ==============================================================================
# 3. HELPER FUNCTIONS FOR BOT LOGIC INTEGRATION
# ==============================================================================
def delete_file_after_delay(file_path, delay=60):
    """Deletes a file after a specified delay in a separate thread."""
    def _delete_file():
        try:
            # Give Twilio some time to fetch the media
            threading.Event().wait(delay)
            if os.path.exists(file_path):
                os.remove(file_path)
                print(f"Successfully deleted temporary file: {file_path}")
        except Exception as e:
            print(f"Error deleting temporary file {file_path}: {e}")

    # Start the deletion in a new thread
    thread = threading.Thread(target=_delete_file)
    thread.daemon = True # Allow the program to exit even if thread is running
    thread.start()
def send_message_to_user(user_id, case_id, case_data):
    """Sends the quotation details to the original user."""
    quote_text = case_data.get('quotation_text', "Your quotation is ready!")
    quote_media = case_data.get('quotation_media_links', [])

    message_body = f"Hello! The quotation for your case (ID: {case_id}) is ready.\n\n{quote_text}\n\nDo you want to proceed with this quotation?"
    
    try:
        # Send text message
        twilio_client.messages.create(
            from_=TWILIO_WHATSAPP_NUMBER,
            to=user_id,
            body=message_body
        )
        print(f"Sent quotation text to {user_id} for case {case_id}.")

        # Send media messages if any
        for media_link in quote_media:
            twilio_client.messages.create(
                from_=TWILIO_WHATSAPP_NUMBER,
                to=user_id,
                media_url=[media_link]
            )
            print(f"Sent quotation media to {user_id} for case {case_id}.")

    except Exception as e:
        print(f"ERROR sending quotation to user {user_id}: {e}")
    """Sends the quotation details to the original user."""
    quote_text = case_data.get('quotation_text', "Your quotation is ready!")
    quote_media = case_data.get('quotation_media_links', [])

    message_body = f"Hello! The quotation for your case (ID: {case_id}) is ready.\n\n{quote_text}\n\nDo you want to proceed with this quotation?"
    
    try:
        # Send text message
        twilio_client.messages.create(
            from_=TWILIO_WHATSAPP_NUMBER,
            to=user_id,
            body=message_body
        )
        print(f"Sent quotation text to {user_id} for case {case_id}.")

        # Send media messages if any
        for media_link in quote_media:
            twilio_client.messages.create(
                from_=TWILIO_WHATSAPP_NUMBER,
                to=user_id,
                media_url=[media_link]
            )
            print(f"Sent quotation media to {user_id} for case {case_id}.")

    except Exception as e:
        print(f"ERROR sending quotation to user {user_id}: {e}")
def register_dentist(details: str) -> str:
        """Registers a new dentist and updates state.
        Input format: Name, Phone Number, Clinic, License Number.
        """
        try:
            name, phone_number, clinic, license_number = [x.strip() for x in details.split(",")]
            
            cleaned_phone_number = phone_number.replace("whatsapp:", "").strip()
            if not cleaned_phone_number.startswith('+'):
                print(f"Warning: Phone number '{phone_number}' does not start with '+'. Attempting to prepend '+'.")
                cleaned_phone_number = '+' + cleaned_phone_number
            user_sessions_fb.child("whatsapp:"+str(phone_number)).update({
                "name": name,
                "clinic": clinic,
                "license": license_number
            })

            return f"{name} has been successfully registered you should simply greet them now."
        except Exception as e:
            return f"Invalid format. Please use: Name, Phone Number, Clinic, License Number. Error: {e}"

def update_db(user_id,session) :
    user_sessions_fb.child(user_id).update(session)

def initialize_user_session(user_id):
    """Initializes the session state for a new user."""
    user_sessions_fb.child(user_id).set({
            'app_state': "",
            'auth_memory' : False,
            'sched_memory' : False,
            'calendar_service': True,
            'current_stage': 'auth',
            'last_question': "",
            'image_count': 0,
            'expected_images': 0
        })

def forward_media_to_number(media_url, sender_whatsapp_id,label ="images"):
    """
    Downloads media from Twilio's authenticated URL, saves it locally,
    and then forwards it via a temporary Flask-served public URL.
    """
    temp_file_name = None # Store just the file name
    try:
        if not FORWARD_TO_WHATSAPP_NUMBER:
            print("FORWARD_TO_WHATSAPP_NUMBER is not set in .env. Cannot forward media.")
            return False

        print(f"Attempting to download media from: {media_url}")

        # Download the media with Twilio authentication
        response = requests.get(media_url, auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN))
        response.raise_for_status() # Raise an HTTPError for bad responses (4xx or 5xx)

        # Get file extension from content-type header
        content_type = response.headers.get('Content-Type')
        extension = mimetypes.guess_extension(content_type) if content_type else '.bin'
        if not extension and '.' in media_url: # Fallback to URL extension if mimetype fails
            extension = os.path.splitext(media_url)[1]
        if not extension:
            extension = '.jpeg' # Default to jpeg if no extension can be determined (adjust as needed)

        # Generate a unique file name to avoid clashes
        temp_file_name = f"{uuid.uuid4()}{extension}"
        temp_file_path = os.path.join(MEDIA_TEMP_DIR, temp_file_name)

        with open(temp_file_path, 'wb') as temp_media_file:
            temp_media_file.write(response.content)

        print(f"Media downloaded to temporary file: {temp_file_path}")
        print(sender_whatsapp_id)
        client_fb =user_sessions_fb.child(sender_whatsapp_id)
        caseid = client_fb.child('active').get()
        # Construct the public URL for the temporary file
        drive_link = upload_drive(temp_file_path, temp_file_name, content_type,client_fb.child('name').get(),client_fb.child(caseid).child('name').get(),label)
        if not drive_link:
            print("Failed to upload file to Google Drive. Cannot forward media.")
            return False

        # Now, forward the media using the Google Drive public URL
        message = twilio_client.messages.create(
            from_=TWILIO_WHATSAPP_NUMBER,
            to="whatsapp:+917801833884",
            media_url=[drive_link], # <--- Pass the Google Drive public URL
            body=f"Image from {sender_whatsapp_id} for case: {caseid}"
        )
        print(f"Media forwarded via Google Drive. Message SID: {message.sid}")

        # Schedule temporary local file for deletion (it's no longer needed after Drive upload)
        delete_file_after_delay(temp_file_path, delay=5) # 
        return True

    except requests.exceptions.HTTPError as e:
        print(f"HTTP Error downloading media from Twilio: {e.response.status_code} - {e.response.text}")
        if temp_file_name and os.path.exists(os.path.join(MEDIA_TEMP_DIR, temp_file_name)):
            os.remove(os.path.join(MEDIA_TEMP_DIR, temp_file_name))
        return False
    except Exception as e:
        print(f"Error forwarding media (after download attempt): {e}")
        if temp_file_name and os.path.exists(os.path.join(MEDIA_TEMP_DIR, temp_file_name)):
            os.remove(os.path.join(MEDIA_TEMP_DIR, temp_file_name))
        return False

def handle_bot_logic(user_id, message_body, num_media, media_urls, media_content_types,session):
    temp = True
    caseid =""
    if session['auth_memory'] :
        print("here auth")
        session['auth_memory'] = sl(session['auth_memory'])
    else :
        session['auth_memory'] = ConversationBufferMemory(memory_key="chat_history", return_messages=True)
    if session['sched_memory'] :
        session['sched_memory'] = sl(session['sched_memory'])
    else :
        session['sched_memory'] = ConversationBufferMemory(memory_key="chat_history", return_messages=True)
    
    """
    Integrates the bot's logic from mainlogic.py to process a single message.
    """
    global output_parser

    # ... (Code for 'auth', 'intent', 'awaiting_images' stages remains the same) ...
    # --- DEBUGGING PRINTS ---
    print(f"\n--- handle_bot_logic for User: {user_id} ---")
    print(f"Incoming message: '{message_body}'")
    print(f"Current stage: {session['current_stage']}")
    print(f"Num media: {num_media}, Media URLs: {media_urls}")
    print(f"App state before processing: {session['app_state']}")

    bot_response = "I'm sorry, I couldn't process your request." # Default response

    if not session['calendar_service']:
        print("Calendar service not initialized.")
        return "Sorry, I'm unable to connect to the calendar service at the moment. Please try again later."
    auth_tools = [
        Tool(
            name="DentistRegistrar",
            func=register_dentist,
            description="Register a new dentist. Input format: Name, Phone Number, Clinic, License Number. confirms you have collected all required fields."
        )
    ]
    scheduling_tools = create_tools()
    output_parser = StrOutputParser()

    # --- Authorization Stage ---
    if session['current_stage'] == 'auth':
        print("Processing in 'auth' stage...")

        # Clean phone number from Twilio format
        pure_sender_phone = user_id.replace("whatsapp:", "").strip()

        # Manually check authorization
        # Not authorized: run registration agent
        print("Dentist not authorized. Invoking registration agent.")
        registration_prompt = hub.pull("hwchase17/structured-chat-agent") + """
You are a structured AI assistant responsible for registering dentists to 3D-Align.

---

## 🚨 Response Format:

You must always respond using a **structured JSON object**, like this:

{{
  "action": "ActionName",
  "action_input": "your string here"
}}

- Do **not** include any text outside of this JSON.
- Do **not** use Markdown or code formatting in the output.
- Never return anything except this JSON object.

---

## 🎯 Goal: Register a dentist to 3D-Align

---

### Step 1 - Start the Conversation

Start by greeting the user politely and offering to help with registration:

{{
  "action": "Final Answer",
  "action_input": "Hi there! Welcome to 3D-Align. I'd be happy to help you register. May I please have your full name?"
}}

---

### Step 2 - Collect Required Details

You must collect **all three** of the following:

1. Full Name  
2. Clinic Name  
3. Dental License Number

Ask one at a time. For example:

- If full name is missing:
{{
  "action": "Final Answer",
  "action_input": "Could you please share your full name?"
}}

- If clinic name is missing:
{{
  "action": "Final Answer",
  "action_input": "Thanks! What's the name of your clinic?"
}}

- If license number is missing:
{{
  "action": "Final Answer",
  "action_input": "Lastly, may I have your dental license number?"
}}

Only ask for details that haven't been provided yet. Always review chat history to avoid repetition.

---

### Step 3 - Register Dentist

Once you have all details, call the tool like this only if registration is still pending:

{{
  "action": "DentistRegistrar",
  "action_input": "<full_name>,<clinic_name>,<license_number>"
}}

---

### Step 4 - Confirm Registration

If registration is successful:

{{
  "action": "Final Answer",
  "action_input": "Registration successful. Welcome to 3D-Align. How can I assist you today?"
}}

---

## 🧠 Rules Recap

- ❌ Never return plain text outside JSON
- ❌ Never show examples to the user
- ✅ Always wait for full name, clinic, and license before registering
- ✅ Be polite and brief in all responses
"""

            # Create agent and executor for registration only
        auth_agent = create_structured_chat_agent(llm=llm, tools=auth_tools, prompt=registration_prompt)
        auth_executor = AgentExecutor.from_agent_and_tools(
                agent=auth_agent, tools=auth_tools, verbose=True, memory=session['auth_memory'], handle_parsing_errors=True
            )

            # Prepare input message
        input_to_agent = message_body
        if not session['auth_memory'].chat_memory.messages or (
                len(session['auth_memory'].chat_memory.messages) == 1 and isinstance(session['auth_memory'].chat_memory.messages[0], SystemMessage)
            ):
            input_to_agent = f"User's phone number: {pure_sender_phone}. User says: {message_body}"
            print(f"First registration input crafted: {input_to_agent}")
            session['auth_memory'].chat_memory.add_message(HumanMessage(content=input_to_agent))

        try:
            response = auth_executor.invoke({"input": input_to_agent})
            bot_response = response["output"]
            print(f"Registration agent response: {bot_response}")

            if "Registration successful" in bot_response:
                session['current_stage'] = 'intent'
                session['auth_memory'].clear()

        except Exception as e:
            print(f"Error during registration agent execution: {e}")
            return "An error occurred during registration. Please try again."

    # --- Intent Detection Stage ---
    elif session['current_stage'] == 'intent':
        print("Processing in 'intent' stage...")  
        try:
            session['app_state'] = intent_chain.invoke({"input": message_body})
            print(session['app_state'])
        except Exception as e:
            print(f"Error during intent chain invocation: {e}")
            return "An error occurred while determining your intent. Please try again."


        if 'New Aligner Case Inquiry' in session['app_state']:
            session['current_stage'] = 'new_aligner'
            bot_response = """Thank you for choosing 3D-Align for your aligner case.
Please choose how you'd like to proceed with the new aligner case:
"""         
        elif 'Unclear Intent' in session['app_state']:
            temp =False
            bot_response = 'HXF0d74b90bbc7fb77db59ac99869bfde'
        elif 'Aligner By-Products' in session['app_state']:
            pass
       
        #atharva's code here
    elif session['current_stage'] == 'new_aligner' :
        session['app_state'] = new_aligner_case_chain.invoke({"user_input" : message_body})
        if 'request_quotation' in session['app_state'] :
            session['current_stage'] = "awaiting_images"
            caseid = str(uuid.uuid4())
            session[caseid] ={}
            session['active'] = caseid
            session[caseid]['quote'] = "..." 
            session[caseid]['name'] = caseid
            bot_response = """Requisite for Aligner Case Submission to 3D Align 

1. Intraoral & Extraoral Photographs 
    (Based on this we will be able to roughly give you idea regarding range of aligners required   
    for your case so that you can have rough estimate to quote to your patient before 
    proceeding for next step) 
2. Intraoral Scan / PVS Impression 
3. OPG (Mandatory) 
4. Lateral Cephalohram / CBCT (if required our 3D Align Team will contact you for the same) 

Note :- 
Prior to Intraoral Scanning / Impression taking we recommend you to execute and confirm with our 3D Align Team : 
Scaling & Polishing 
Restorations
Prosthetic Replacements
Disimpaction / Teeth Removal
Interproximal Reduction (as directed by our 3D Align team) 

This recommendation criteria is enforced in order to have better aligner fit and to avoid any discrepancies during ongoing aligner treatment which might affect the results. If not executed as directed by 3D Align team than treating dentist would be responsible for the same. 
To Proceed Further share the Images
"""
        elif 'submit_case' in session['app_state'] :
            session['current_stage'] = "fetching_name"
            caseid = str(uuid.uuid4())
            session[caseid] ={}
            session['active'] = caseid
            session[caseid]['quote'] = "..." 
            session[caseid]['name'] = caseid
            bot_response = "great Please let us know the name of patient"
            session['app_state'] = "direct"
        elif 'other' in session['app_state'] :
            bot_response = "Please choose one of the following options or you would like to do something else ?"
            
    elif session['current_stage'] == 'awaiting_images':
        print("Processing in 'awaiting_images' stage...")
        if num_media > 0:
            print(f"Received {num_media} media items. Attempting to forward...")
            successful_forwards = 0
            for url in media_urls:
                if forward_media_to_number(url, user_id):
                    successful_forwards += 1
                else:
                    print(f"Failed to forward media: {url}")
            session['image_count'] += successful_forwards
            if successful_forwards > 0:
                bot_response = f"I have sucessfully recieved {session['image_count']} image(s). type 'DONE' to proceed further"
            else:
                bot_response = "There was an error forwarding your images. Please try again or type 'DONE' if you have nothing to send."
            print(f"Bot response in 'awaiting_images' after media: {bot_response}")

        elif message_body.lower() == 'done':
            print("User typed 'DONE' in 'awaiting_images' stage.")
            if session['image_count'] > 0 or manual_test:
                bot_response = f"Thank you for submitting { session['image_count'] } image(s). We will review them and get back to you with a quotation shortly"
                session['current_stage'] = 'awaiting_quote'
                session['image_count'] = 0 # Reset image count 
                print(f"Transitioned to 'scheduling_quote_confirm'. Bot response: {bot_response}")
            else:
                bot_response = "You haven't sent any images yet. Please send images to proceed further"
        else:
             bot_response = "You haven't sent any images yet. Please send images to proceed further or would you like to do something else ?"

    elif session["current_stage"] == 'awaiting_quote':
        if session[session["active"]]["quote"] != "..." or manual_test:
            bot_response = f"Based on the images you provided, the quotation is {session[session['active']]['quote']}, please let us know once the patient agrees to it?"
            session['current_stage'] = 'scheduling_quote_confirm'
            session['last_question'] = bot_response
        else:
            bot_response = "We are still reviewing the quote will get back to you shortly, till then woudl you like to do anything else perhap submit an another case or track an existing case"


    elif session['current_stage'] == 'scheduling_quote_confirm':
        print("Processing in 'scheduling_quote_confirm' stage...")
        confirmation_response = confirm_chain.invoke({"input": message_body, "question": session['last_question']})
        session['last_question'] = None
        confirmation_response = confirmation_response.lower()
        print(f"Confirmation response: {confirmation_response}")

        if "no" in confirmation_response:
                bot_response = "Thank you for contacting 3D-Align."
                session['current_stage'] = 'end_session'
                print(f"Transitioned to 'end_session'. Bot response: {bot_response}")
        elif "yes" in confirmation_response:
                bot_response = "Great...Now please let us know the patient name"
                session['current_stage'] = 'fetching_name'


    # --- Scheduling Stage (after "submit_case" intent and images received) ---
    elif session['current_stage'] == 'fetching_name' :
        print("stage : getname")
        get_name = llm.invoke(f"""
You are an AI assistant.

The user was asked to provide the patient's name. Their response was:
"{message_body}"

Your task:
- Extract the patient's **full name** from the response.
- your response should be **only the name** as plain text, with no extra words or formatting.
- If a name cannot be confidently identified, return a message that starts with the backtick symbol (`) and politely ask the user to provide the full name again.
""").content

        print(get_name)
        if '`' in get_name :
            bot_response = get_name
        else :
            session[session['active']]['name'] = get_name
            root_ref.child('namebook').child(session['active']).set(get_name)
            message_body = 'unrelated'
            session['current_stage'] = 'choose'

    if session['current_stage'] == 'choose' :
        reply = choose_chain.invoke({"input":message_body})
        if 'submit_scan' in reply:
            session['current_stage'] = 'fetch_scan'
            bot_response = f"Send Intraroral Scan of {session[session['active']]['name']} on 3d.alignsolutions@gmail.com or here through whatsapp"
        elif 'schedule_scan' in reply:
            session['current_stage'] = 'scheduling_appointment'
            message_body = "need to schedule scan"
        else :
            bot_response = 'Please choose how you would like to proceeed further ?'
    
    if session['current_stage'] == 'scheduling_appointment':
        print("Processing in 'scheduling_appointment' stage...")
        sched_prompt = hub.pull("hwchase17/structured-chat-agent") + """

You are a friendly and helpful assistant responsible for scheduling 3D-Align scanning appointments.

Behavior:
- Always respond only in valid JSON.
- Never write any text outside JSON—no thoughts, explanations, markdown, or formatting.
- Never use <think>, backticks, markdown lists, or headers.
- Each response must strictly follow the JSON format:
  {{
    "action": "Final Answer",
    "action_input": "your message to user"
  }}

Your Role:
Guide the user step by step to book a 3D-Align scan by following this process:

---

Step 1: Ask for Scan Date and Time
- First, say:
  "When would you like to schedule your scan? Please share the preferred date and time in ISO format, like 2025-06-12T15:30."

- Do not continue until the user provides a valid ISO 8601 date and time.

Once you get that:

- Say:
  "Thanks! And where will the scan take place? You can share the clinic address or send your location."

- Wait until both date/time and location are provided before continuing.

---

Step 2: Check Availability
- After receiving both date/time and location:
  - Convert the provided date and time to ISO 8601 format.
  - Use the `CheckCalendarAvailability` tool with just the ISO datetime as input.

---

Step 3: Confirm with User
- If the slot is available:
  - Say: "The slot is available."
  - Then ask: "Would you like me to book the appointment for this date, time, and location?"

- Do not proceed without user confirmation.

---

Step 4: Book the Appointment
- If the user confirms:
  - Call `BookCalendarAppointment` with this string format:
    "<iso_datetime>,<location>"

  - If the location is GPS coordinates, convert it to:
    "https://maps.google.com/?q=<latitude>,<longitude>"

- If successful, return this final response in JSON:
  {{
    "action": "Final Answer",
    "action_input": "2025-06-12,15:30,https://maps.google.com/?q=19.0760,72.8777,True"
  }}

---

Step 5: Handle Unavailability
- If the slot is NOT available:
  - Say: "That slot is not available."
  - Go back to Step 1 and politely ask the user to suggest a new date and time.

---

Important Rules:
- Never assume anything. Always wait for the user to provide clear information.
- Ask only one question at a time.
- Keep each message short, clear, and polite.
- Do not suggest alternate times.
- Do not continue unless required data is present.
- Final output must always be valid JSON with only `action` and `action_input` keys.

"""

        sched_agent = create_structured_chat_agent(llm, tools=scheduling_tools, prompt=sched_prompt)
        sched_executor = AgentExecutor.from_agent_and_tools(
            agent=sched_agent, tools=scheduling_tools, memory=session['sched_memory'], handle_parsing_errors=True, verbose=True
        )

        # The first message to this agent will be from the user, following the bot's "Great! Let's schedule..." message
        # The agent will then use its instructions (in sched_initial_message) to ask for time and location.
        try:
            response = sched_executor.invoke({"input": message_body})["output"]
            if response.strip().split(',')[-1] == "True":
                bot_response = f"""This is to inform you that Intraoral Scan booked for 

Patient Name :- {session[session['active']]['name']}

Date :- {response.strip().split(',')[0]}
Time :-{response.strip().split(',')[1]}
Location :- {response.strip().split(',')[2]}

Please Note :-
Any changes in intraoral scan schedule has to be made 24 hours prior or else scan cancellation charges would be levied as applicable. 
No Cancellation charges if intimated 24 hours prior. 
Intraoral Scan once taken will be consider to go for aligner treatment plan simulation and simulation charges would be levied as applicable. In case of any query please feel free to contact."""

            else:
                bot_response =response
        except Exception as e:
            print(f"Error during scheduling agent invocation: {e}")
            bot_response = "An error occurred during scheduling. Please try again."
   
    elif session['current_stage'] == 'fetch_scan' :
        print("Processing in 'awaiting_stl_files' stage...")
        if num_media > 0:
            print(f"Received {num_media} media items. Checking for STL files...")
            successful_forwards = 0

            for url, content_type in zip(media_urls, media_content_types):
                if content_type in ["application/sla", "model/stl"]:
                    if forward_media_to_number(url, user_id, 'intraoral_scan'):
                        successful_forwards += 1
                    else:
                        print(f"Failed to forward STL file: {url}")
                else:
                    print(f"Ignored non-STL file: {url} (Content-Type: {content_type})")

            session['stl_file_count'] += successful_forwards

            if successful_forwards > 0:
                bot_response = (
                    f"I've successfully received {session['stl_file_count']} STL file(s). "
                    "Type 'DONE' when you're ready to proceed."
                )
            else:
                bot_response = (
                    "None of the files you sent appear to be valid STL files. "
                    "Please try again or type 'DONE' if you're finished."
                )
            print(f"Bot response in 'awaiting_stl_files': {bot_response}")

        elif message_body.lower() == 'done':
            print("User typed 'DONE' in 'awaiting_stl_files' stage.")
            if session['stl_file_count'] > 0 or manual_test:
                session['scan_recieved'] = True
                session['stl_file_count'] = 0  # Reset counter
            else:
                bot_response = (
                    "You haven't submitted any valid STL files yet. "
                    "Please send at least one to continue."
                )
        if session['scan_recieved'] :
            bot_response = f"""We have received - Intraoral Scan / PVS Impression of your case 
Patient Name :- {session[session['active']]['name']}
Our 3D Align Team will be working on your case and will provide you Treatment Plan alongwith Simulations Videos within next 48 hours 
In case if the case has to be delivered on urgent basis please intimate to us prior so that we can put under "Express Category" (processing fee will be levied additional) and deliver the case as per your requirement."""
            session['current_stage'] = 'scan_confirm'

    elif session['current_stage'] == 'scan_confirm' :
        reply = express_chain.invoke({'input' : message_body})
        if 'express' in reply :
            session[session['active']]['cat'] = 'express'
            bot_response = f"okay I have kept it in express category"
        elif 'normal' in reply:
            session[session['active']]['cat'] = 'normal'
            bot_response =f"no problem it is in normal category"
        else :
            if session[session['active']]['status']:
            #bot_response = atharva's code here
                bot_response = "congo"
            else :
                bot_response = f"your case for {session[session['active']]['name']} is still under processing"
        # In server.py, inside the handle_bot_logic function

        # ... (existing elif blocks for other stages) ...
    elif session['current_stage'] == 'awaiting_fit_confirmation':
        print("Processing in 'awaiting_fit_confirmation' stage...")

        case_id = session.get('active_case_for_confirmation')
        if not case_id:
            bot_response = "I'm sorry, I seem to have lost track of which case we were discussing. A team member will get in touch."
            session['current_stage'] = 'intent'
            # You might want to alert your team here as well
        else:
            # Retrieve case details from Firebase
            case_data = root_ref.child('cases').child(case_id).get()
            patient_name = case_data.get('name', 'the patient') if case_data else 'the patient'

            # Use the confirm_chain to interpret the Yes/No response
            last_question = f"Should we go ahead with the fabrication for patient {patient_name}?"
            confirmation = confirm_chain.invoke({"input": message_body, "question": last_question})
            print(f"Fit confirmation from dentist: '{confirmation}'")

            if 'yes' in confirmation.lower():
                bot_response = "Thank you for the confirmation! We will now proceed with the fabrication of the remaining aligner sets."
                # Trigger the next step in the production workflow
                production_logic.start_full_case_fabrication(user_id, case_id, patient_name)
                session['current_stage'] = 'intent'  # Reset state

            elif 'no' in confirmation.lower():
                bot_response = "Thank you for your feedback. A member of our clinical team will contact you shortly to troubleshoot the issue."
                # Alert the internal team about the problem
                production_logic.alert_team_on_fit_issue(user_id, case_id, patient_name, message_body)
                session['current_stage'] = 'intent'  # Reset state

            else:
                bot_response = "I'm sorry, I didn't quite understand. Does the training aligner fit correctly? Please respond with 'Yes' or 'No'."
                # The stage remains 'awaiting_fit_confirmation' to prompt the user again


    # ... (The rest of the stages and the Flask routes remain the same) ...
    # --- Tracking Case Stage ---
    elif session['current_stage'] == 'tracking_case':
        print("Processing in 'tracking_case' stage...")
        bot_response = f"Searching for case details related to '{message_body}'. Please wait..."
        session['current_stage'] = 'end_session'
        print(f"Transitioned to 'end_session'. Bot response: {bot_response}")

    # --- End Session ---
    elif session['current_stage'] == 'end_session':
        print("Processing in 'end_session' stage...")
        bot_response = "Thank you for using 3D-Align services. Have a great day!"
        print(f"Bot response: {bot_response}")

    # --- Final check before returning ---
    print(f"Final bot_response to be sent: '{bot_response}'")
    print(f"--- End handle_bot_logic ---\n")
    if ls(session['sched_memory']) :
        session['sched_memory'] = ls(session['sched_memory'])
    else:
        session['sched_memory'] = False
    if ls(session['auth_memory']) :
        session['auth_memory'] = ls(session['auth_memory'])
    else:
        session['auth_memory']= False
    session['calender_service'] = True
    update_db(user_id,session)

    return temp,bot_response


# ==============================================================================
# 4. FLASK ROUTES
# ==============================================================================
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
import requests
import os
@app.route("/whatsapp"  , methods=["POST"])
def whatsapp_webhook():
    """
    Twilio webhook endpoint for incoming WhatsApp messages.
    """

    incoming_msg = request.values.get("Body", "")
    sender_id = request.values.get("From", "")
    num_media = int(request.values.get("NumMedia", 0))
    latitude = request.form.get("Latitude")
    longitude = request.form.get("Longitude")
    parent_message_sid_from_prod_reply = request.values.get("OriginalRepliedMessageSid", None)

    media_urls = []
    media_content_types = []

    if latitude and longitude:
        location_url = f"https://www.google.com/maps?q={latitude},{longitude}"
        print("User location received:", location_url)
        incoming_msg = location_url

    if num_media > 0:
        for i in range(num_media):
            media_url = request.values.get(f"MediaUrl{i}")
            content_type = request.values.get(f"MediaContentType{i}")
            media_urls.append(media_url)
            media_content_types.append(content_type)
            print(f"Received media: {media_url} (Content-Type: {content_type})")

    session = user_sessions_fb.child(sender_id).get()
    if session is not None:
        session = dict(session)
        bot_response = handle_bot_logic(
            sender_id, incoming_msg, num_media, media_urls, media_content_types, session
        )
    else:
        initialize_user_session(sender_id)

    resp = MessagingResponse()
    if bot_response[0]:
        twilio_client.messages.create(
            from_=TWILIO_WHATSAPP_NUMBER,
            to=sender_id,
            body=bot_response[1]
        )
    else:
        twilio_client.messages.create(
        from_=TWILIO_WHATSAPP_NUMBER,  # Twilio Sandbox or your approved number
        to=sender_id,    # Customer's WhatsApp number
        content_sid="HXf0d74b90bbc7fb77db59ac99869bfded",  # From the image
        content_variables='{}'          # Populate this if your template uses variables
        )

    return str(resp)
 # This is the ONLY line that should send the TwiML to Twilio


# ==============================================================================
# 5. RUN THE FLASK APP
# ==============================================================================
if __name__ == "__main__":
    if not os.path.exists('client_secret.json'):
        print("Error: 'client_secret.json' not found. Please download it from Google Cloud Console.")
        exit()

    print("Initializing Google Calendar service (may require browser authentication)...")
    temp_service = get_calendar_service_oauth()
    if not temp_service:
        print("Failed to initialize Google Calendar service. The bot may not function correctly.")
    else:
        print("Google Calendar service ready.")

    print("Starting Flask server. Your Twilio webhook URL will be something like: YOUR_NGROK_URL/whatsapp")
    if not os.getenv("NGROK_URL"):
        print("\n*** IMPORTANT: NGROK_URL environment variable is NOT set. ***")
        print("   Media forwarding will likely FAIL as Twilio cannot access localhost.")
        print("   Please run ngrok (e.g., `ngrok http 5000`) and set NGROK_URL in your .env file")
        print("   to the HTTPS URL ngrok provides (e.g., https://xxxxxxxxxxxx.ngrok-free.app).\n")
    manual_test = False
    while manual_test:
        sender_id = "whatsapp:+917801833662"
        num_media = 0
        media_urls =[]
        session = user_sessions_fb.child(sender_id).get()
        if session is not None :
            incoming_msg = input("user :")
            print(session)
            session = dict(session)
            media_content_types = ["application/sla"]
            bot_response = handle_bot_logic(sender_id, incoming_msg, num_media, media_urls, media_content_types, session )
        else :
            initialize_user_session(sender_id)
    app.run(debug=True, port=5000)