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
load_dotenv() # This line should be at the very top of your configuration section

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
model = llm



# --- Global state for each user (for simplicity; ideally use a database) ---

# ==============================================================================
# 3. HELPER FUNCTIONS FOR BOT LOGIC INTEGRATION
# ==============================================================================
def handle_production_quotation(parent_message_sid_from_prod_reply, prod_message_body, prod_media_urls):
    """
    Handles an incoming message from the production team, assumed to be a quotation reply.
    Identifies the original user and forwards the quotation by fetching parent message body.
    """
    print(f"\n--- Handling Production Team Quotation (Parent SID: {parent_message_sid_from_prod_reply}) ---")
    
    original_user_id = None
    case_id = None

    try:
        # Fetch the original message that was replied to
        parent_message = twilio_client.messages(parent_message_sid_from_prod_reply).fetch()
        parent_message_body = parent_message.body
        print(f"Fetched parent message body: '{parent_message_body}'")

        # Parse the original user ID and case ID from the parent message body
        # Example format: "Image from whatsapp:+1234567890 for case: uuid-1234"
        match = re.search(r"Image from (whatsapp:\+\d+) for case: ([\w-]+)", parent_message_body)
        if match:
            original_user_id = match.group(1)
            case_id = match.group(2)
            print(f"Parsed original user: {original_user_id}, Case ID: {case_id}")
        else:
            print(f"ERROR: Could not parse original user ID or case ID from parent message body: '{parent_message_body}'")
            # Optionally, send a message back to the production team that the reply could not be matched
            twilio_client.messages.create(
                from_=TWILIO_WHATSAPP_NUMBER,
                to=FORWARD_TO_WHATSAPP_NUMBER,
                body="Could not process your reply. The original forwarded message's body did not contain expected user/case info. Please provide the case ID if sending a new quotation."
            )
            return

    except Exception as e:
        print(f"ERROR: Could not fetch or parse parent message (SID: {parent_message_sid_from_prod_reply}): {e}")
        twilio_client.messages.create(
            from_=TWILIO_WHATSAPP_NUMBER,
            to=FORWARD_TO_WHATSAPP_NUMBER,
            body="An error occurred trying to process your reply. Please ensure you are replying to a forwarded image."
        )
        return

    if not original_user_id or not case_id:
        print(f"ERROR: Original user ID or case ID missing after parsing. Cannot process quotation.")
        return

    # 2. Get the original user's session data
    original_user_session = user_sessions_fb.child(original_user_id).get()
    if not original_user_session:
        print(f"ERROR: Original user session not found for {original_user_id}. Cannot update quotation.")
        return
    
    original_user_session = dict(original_user_session) # Ensure it's a mutable dict

    # 3. Update the original user's case with quotation details
    cases = original_user_session.get('cases', {})
    current_case = cases.get(case_id, {})
    
    current_case['quotation_text'] = prod_message_body
    current_case['quotation_media_links'] = []
    
    if prod_media_urls:
        # If production team sends media back, download and upload to drive, then store link
        for url in prod_media_urls:
            try:
                # Download with authentication
                response = requests.get(url, auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN))
                response.raise_for_status()
                
                content_type = response.headers.get('Content-Type')
                extension = mimetypes.guess_extension(content_type) or '.bin'
                temp_file_name = f"{uuid.uuid4()}{extension}"
                temp_file_path = os.path.join(MEDIA_TEMP_DIR, temp_file_name)

                with open(temp_file_path, 'wb') as f:
                    f.write(response.content)
                
                drive_link = upload_drive(temp_file_path, temp_file_name, content_type)
                if drive_link:
                    current_case['quotation_media_links'].append(drive_link)
                    delete_file_after_delay(temp_file_path, delay=5)
                else:
                    print(f"Failed to upload production media to Drive: {url}")

            except Exception as e:
                print(f"Error processing production media {url}: {e}")

    current_case['status'] = 'quoted'
    current_case['quoted_at'] = datetime.now().isoformat()
    cases[case_id] = current_case
    original_user_session['cases'] = cases
    original_user_session['current_stage'] = 'awaiting_quote_confirmation' # Transition original user
    original_user_session['last_question'] = f"The quotation for your case (ID: {case_id}) is ready. Would you like to review it?"
    
    update_db(original_user_id, original_user_session)
    
    # 4. Auto-send quotation message to original user
    send_message_to_user(original_user_id, case_id, current_case)
    print(f"Quotation processed and message triggered for {original_user_id}.")


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

# ... (The rest of the helper functions like delete_file_after_delay and forward_media_to_number remain unchanged) ...
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


def forward_media_to_number(media_url, sender_whatsapp_id):
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
        drive_link = upload_drive(temp_file_path, temp_file_name, content_type,client_fb.child('name').get(),client_fb.child(caseid).child('name').get())
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


def handle_bot_logic(user_id, message_body, num_media, media_urls,session):
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
    confirm_prompt = ChatPromptTemplate.from_messages([
    ("system", "You are an AI assistant that analyzes user responses."),
    ("human", """
You are given a yes-or-no question and a user's response.

Task:
- Determine if the user's response indicates **Yes** or **No**.
- If the response is unclear or ambiguous, return `Unknown`.
- Respond with **only one word**: Yes, No, or Unknown.

Question: {question}
User's Response: {input}
""")
])
    confirm_chain = confirm_prompt | llm | output_parser

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
    scheduling_tools = create_tools(session['calendar_service'])
    output_parser = StrOutputParser()

    # --- Authorization Stage ---
    if session['current_stage'] == 'auth':
        print("Processing in 'auth' stage...")

        # Clean phone number from Twilio format
        pure_sender_phone = user_id.replace("whatsapp:", "").strip()

        # Manually check authorization
        # Not authorized: run registration agent
        print("Dentist not authorized. Invoking registration agent.")
        registration_prompt = hub.pull("hwchase17/structured-chat-agent") + '''

You are a friendly assistant helping register dentists to 3D-Align.

Behavior:
- Always greet the user politely at the beginning of the conversation.
- Use a natural, conversational tone—be warm, professional, and human-like.
- The user's phone number is already available. Never ask for it.

Your Task:
- Collect the following three details from the user:
  1. Full Name
  2. Clinic Name
  3. Dental License Number

Process:
- As you interact, gently guide the user to provide the missing information, if any.
- Only after collecting **all three** details, call the `DentistRegistrar` tool with:
  
  `DentistRegistrar(name, phone_number, clinic, license)`

Response:
- If the registration is successful, respond with:

  `"Registration successful. Welcome to 3D-Align. How can I assist you today?"`

Rules:
- Do **not** call `DentistRegistrar` if any detail is missing.
- Review the chat history before asking for any detail to avoid repetition.
- Be helpful and ensure the user feels comfortable throughout.
- Do not give any example to user
- Keep your responses brief and crisp

Start the interaction with a warm greeting and an offer to help with registration.
'''

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

        intent_classification_prompt = ChatPromptTemplate.from_messages([
            ("system", "You are an helpful assistant"),
            ("human", """Your job is to identify if the user has a new case file or patient he would like to submit or he wants to track existing case or patient
                         Here is the User Input : {input}
                         Output should be one word only : submit_case or track_case or none""")
        ])

        intent_chain = intent_classification_prompt | model | output_parser
        try:
            session['app_state'] = intent_chain.invoke({"input": message_body})
        except Exception as e:
            print(f"Error during intent chain invocation: {e}")
            return "An error occurred while determining your intent. Please try again."


        if 'submit_case' in session['app_state']:
            session['current_stage'] = 'awaiting_images'
            caseid = str(uuid.uuid4())
            session[caseid] ={}
            session['active'] = caseid
            session[caseid]['quote'] = "..." 
            session[caseid]['name'] = caseid
            bot_response = """Thank you for considering 3D-Align for your aligner case.
Kindly share clear images of the patient's case so we can prepare an accurate quotation. Once you receive the quotation, you may discuss it with the patient, and upon confirmation, we’ll proceed with the next steps.
"""
            print(f"Transitioned to 'awaiting_images' stage. Bot response: {bot_response}")
        elif 'track_case' in session['app_state']:
            bot_response = "Please provide the case ID or patient name you'd like to track."
            session['current_stage'] = 'tracking_case'
            print(f"Transitioned to 'tracking_case' stage. Bot response: {bot_response}")
        elif session['app_state'] == 'none':
            bot_response = llm.invoke(message_body).content
    # --- Awaiting Images Stage ---
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
                print(f"Bot response: {bot_response}")
        else:
             bot_response = "You haven't sent any images yet. Please send images to proceed further"
             print(f"Bot response: {bot_response}")

    elif session["current_stage"] == 'awaiting_quote':
        bot_response = f"Based on the images you provided, the quotation is {3}, please let us know once the patient agrees to it?"
        session['current_stage'] = 'scheduling_quote_confirm'
        session['last_question'] = bot_response

    # --- Scheduling Stage (after "submit_case" intent and images received) ---
    elif session['current_stage'] == 'scheduling_quote_confirm':
        print("Processing in 'scheduling_quote_confirm' stage...")

        try:
            confirmation_response = confirm_chain.invoke({"input": message_body, "question": session['last_question']})
            session['last_question'] = None
            confirmation_response = confirmation_response.lower()
            print(f"Confirmation response: {confirmation_response}")

            if "no" in confirmation_response:
                bot_response = "Thank you for contacting 3D-Align."
                session['current_stage'] = 'end_session'
                print(f"Transitioned to 'end_session'. Bot response: {bot_response}")
            elif "yes" in confirmation_response:
                bot_response = "Great...Now would you prefer we bring our own scanning equipment, or do you have it on-site?"
                session['current_stage'] = 'scheduling_machine_confirm'
                session['last_question'] = "Do you have scanning machines or our technicians should bring them ?"
                print(f"Transitioned to 'scheduling_machine_confirm'. Bot response: {bot_response}")
            else:
                bot_response = "I didn't understand your response. Please say 'Yes' or 'No'."
                print(f"Bot response (did not understand confirm): {bot_response}")
        except Exception as e:
            print(f"Error during scheduling_quote_confirm: {e}")
            bot_response = "An error occurred while confirming. Please try again."


    # MODIFICATION: This stage now transitions directly to the scheduling agent with new instructions.
    elif session['current_stage'] == 'scheduling_machine_confirm':
        print("Processing in 'scheduling_machine_confirm' stage...")
        try:
            machine_response = confirm_chain.invoke({"input": message_body, "question": session['last_question']})
            session['last_question'] = None
            print(f"Machine confirmation response: {machine_response}")
            machine_response =machine_response.lower().strip()

            if "yes" in machine_response or "no" in machine_response:
                session[session['active']]['machine'] = machine_response
                bot_response = "Great! Let's schedule the appointment....Please provide me the full name of patient" # A simple transition message
                session['current_stage'] = 'fetching_name'
                
                # The new, more detailed prompt for the scheduling agent.
                # Clear previous scheduling memory and add the new system prompt
                session['sched_memory'].clear()
                print(f"Transitioned to 'scheduling_appointment' with new instructions.")
            else:
                bot_response = "I didn't quite catch that. Please let me know if you have scanning machines or if our technicians should bring them."
                session['last_question'] = "Do you have scanning machines or our technicians should bring them ?"
                print(f"Bot response (did not understand machine confirm): {bot_response}")
        except Exception as e:
            print(f"Error during scheduling_machine_confirm: {e}")
            bot_response = "An error occurred while confirming machine availability. Please try again."
    
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
            message_body = "Hi"
            session['current_stage'] = 'scheduling_appointment'
    if session['current_stage'] == 'scheduling_appointment':
        print("Processing in 'scheduling_appointment' stage...")
        sched_prompt = hub.pull("hwchase17/structured-chat-agent")+"""
You are a friendly and helpful assistant responsible for scheduling 3D-Align scanning appointments.

Behavior:
- Be polite and conversational—sound like a real human assistant.
- Ask one question at a time.
- Keep responses short, clear, and natural.

Goal:
To book a 3D-Align scanning appointment by strictly following these steps:

---

**Step 1 - Collect Details:**
Start by asking:
- “When would you like to schedule your scan? Please share the preferred date and time.”

Once the user provides a valid response, ask:
- “Thanks! And where will the scan take place? You can share the clinic address or send your location.”

→ Do **not** continue unless you have both the **date/time** and **location**.

---

**Step 2 - Check Availability:**
- Convert the date/time to ISO 8601 format (e.g., `2025-06-12T15:30`).
- Use the `CheckCalendarAvailability` tool with that date/time.

---

**Step 3 - Confirm with User:**
If the slot is available:
- Say: “The slot is available.”
- Then ask: “Would you like me to book the appointment for this date, time, and location?”

---

**Step 4 - Book Appointment:**
If the user confirms:
- Call `BookCalendarAppointment` with a single comma-separated string:
  `"<iso_datetime_str>,<location>"`

  - If the location is GPS coordinates, convert it to:
    `https://maps.google.com/?q=<latitude>,<longitude>`
  - After successfully booking appointment say thank you and ask if they need anything else politely

---

**Step 5 - Handle Unavailability:**
If the slot is not available:
- Say: “That slot is not available.”
- Go back to Step 1 and politely ask the user to suggest a new date and time.

---

Rules:
- Never assume anything—always wait for clear user input.
- Never suggest alternate times yourself.
- Only the user decides what to book.
- Keep you response brief

"""
        sched_agent = create_structured_chat_agent(llm, tools=scheduling_tools, prompt=sched_prompt)
        sched_executor = AgentExecutor.from_agent_and_tools(
            agent=sched_agent, tools=scheduling_tools, memory=session['sched_memory'], handle_parsing_errors=True, verbose=True
        )

        # The first message to this agent will be from the user, following the bot's "Great! Let's schedule..." message
        # The agent will then use its instructions (in sched_initial_message) to ask for time and location.
        try:
            response = sched_executor.invoke({"input": message_body})
            bot_response = response["output"]
            print(f"Scheduling agent raw response: {response}")
            print(f"Scheduling stage bot_response: {bot_response}")
        except Exception as e:
            print(f"Error during scheduling agent invocation: {e}")
            bot_response = "An error occurred during scheduling. Please try again."


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

    return bot_response


# ==============================================================================
# 4. FLASK ROUTES
# ==============================================================================
@app.route("/whatsapp", methods=["POST"])
def whatsapp_webhook():
    """
    Twilio webhook endpoint for incoming WhatsApp messages.
    """


    msg = twilio_client.messages.create(
    from_='whatsapp:+14155238886',
    to='whatsapp:+917801833884',
    body='✅ Please swipe reply to *this* message.'
    )

    print(f"Sent message SID: {msg.sid}")

    incoming_msg = request.values.get("Body", "")
    sender_id = request.values.get("From", "")
    num_media = int(request.values.get("NumMedia", 0))
    latitude = request.form.get("Latitude")
    longitude = request.form.get("Longitude")
    parent_message_sid_from_prod_reply = request.values.get("OriginalRepliedMessageSid", None)
    for key in request.values:
        print(f"{key}: {request.values.get(key)}")

    prod_media_urls = []
    if num_media > 0:
        for i in range(num_media):
            media_url = request.values.get(f"MediaUrl{i}")
            if media_url:
                prod_media_urls.append(media_url)

    # Check if the message is from the production team's number AND it's a reply
    if sender_id == "whatsapp:+917801833884":
        print(f"Received reply from production team ({sender_id}) with parent SID: {parent_message_sid_from_prod_reply}")
        """
        # Call the function to handle the quotation from the production team
        handle_production_quotation(
            parent_message_sid_from_prod_reply, # The SID of the message our bot sent to prod
            incoming_msg,                        # The text body of prod's reply (the quotation)
            prod_media_urls                      # Any media (images/docs) attached to prod's reply
        )
        """
        resp = MessagingResponse()
        # You might want to send a confirmation back to the production team here
        # resp.message("Quotation received and being processed for the customer.")
        return str(resp)
    else :

        if latitude and longitude:
            # Store this in your session/memory for the LangTune agent
            location_url = f"https://www.google.com/maps?q={latitude},{longitude}"
            print("User location received:", location_url)
            incoming_msg = location_url
        media_urls = []
        # Remove the redundant `location_url =[]` line as it's not used and can cause confusion.
        # media_urls should be sufficient.

        if num_media > 0:
            for i in range(num_media):
                media_url = request.values.get(f"MediaUrl{i}")
                media_urls.append(media_url)
                print(f"Received media URL: {media_url}")

        
        session = user_sessions_fb.child(sender_id).get()
        if session is not None :
            session = dict(session)
            bot_response = handle_bot_logic(sender_id, incoming_msg, num_media, media_urls, session)
        else :
            initialize_user_session(sender_id)

        resp = MessagingResponse()
        if bot_response:
            message = twilio_client.messages.create(
                    from_=TWILIO_WHATSAPP_NUMBER,
                    to=sender_id,
                    body=bot_response
                )
        else:
            print("WARNING: bot_response was empty or None. Sending a generic message.")
            # Ensure a message is always added to the response, even if bot_response is empty
            msg = resp.message("Sorry, I'm having trouble generating a response right now. Please try again.")

        # IMPORTANT: REMOVE these print statements! They interfere with the HTTP response.
        # print(resp) 
        # print(msg) 
        
        return str(resp) # This is the ONLY line that should send the TwiML to Twilio


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
        sender_id = "whatsapp:+917801833800"
        num_media = 0
        media_urls =[]
        session = user_sessions_fb.child(sender_id).get()
        if session is not None :
            incoming_msg = input("user :")
            print(session)
            session = dict(session)
            bot_response = handle_bot_logic(sender_id, incoming_msg, num_media, media_urls, session)
        else :
            initialize_user_session(sender_id)
    app.run(debug=True, port=5000)