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

# Import the necessary functions and components from your mainlogic.py
from mainlogic import (
    get_calendar_service_oauth,
    create_tools,
    ChatOpenAI,
    hub,
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
)

# ==============================================================================
# 2. CONFIGURATION AND INITIALIZATION
# ==============================================================================
load_dotenv()

app = Flask(__name__)

# --- Twilio Configuration ---
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_NUMBER = os.getenv("TWILIO_WHATSAPP_NUMBER")
FORWARD_TO_WHATSAPP_NUMBER = os.getenv("FORWARD_TO_WHATSAPP_NUMBER")

twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# --- Temporary storage for media files ---
# We need a predictable temporary directory for Flask to serve from.
# Ensure this directory exists and is managed.
MEDIA_TEMP_DIR = os.path.join(tempfile.gettempdir(), "twilio_media_bot")
os.makedirs(MEDIA_TEMP_DIR, exist_ok=True)
print(f"Temporary media directory: {MEDIA_TEMP_DIR}")


# --- LLM Initialization (from mainlogic.py) ---
llm = ChatOpenAI(
    model_name="meta-llama/Llama-3.3-70B-Instruct-Turbo",
    openai_api_key=os.getenv("TOGETHER_API_KEY"),
    openai_api_base="https://api.together.xyz/v1",
)
model = llm

# --- Global state for each user (for simplicity; ideally use a database) ---
user_sessions = {}

# ==============================================================================
# 3. HELPER FUNCTIONS FOR BOT LOGIC INTEGRATION
# ==============================================================================
def initialize_user_session(user_id):
    """Initializes the session state for a new user."""
    if user_id not in user_sessions:
        user_sessions[user_id] = {
            'app_state': {
                'state': None,
                'cap': "none",
                'exi': False
            },
            'calendar_service': get_calendar_service_oauth(),
            'auth_memory': ConversationBufferMemory(memory_key="chat_history", return_messages=True),
            'sched_memory': ConversationBufferMemory(memory_key="chat_history", return_messages=True),
            'current_stage': 'auth',
            'last_question': None,
            'image_count': 0,
            'expected_images': 0
        }
        initial_auth_message = (
            "You are an AI assistant that helps general dentists get authorized to submit aligner cases.\n"
            "1. First ask the user to provide their email address.\n"
            "2. Use AuthorizationChecker to check if they are authorized.\n"
            "3. If not authorized, ask them for their details in this format: Name, Email, Clinic, License Number.\n"
            "4. Use DentistRegistrar to register them only if you have all Name Email Clinic License Number of the user.\n"
            "5. After the user is authorized dont use DentistRegistrar directly, say: 'Welcome to 3D-Align. How can I assist you today?'"
        )
        user_sessions[user_id]['auth_memory'].chat_memory.add_message(SystemMessage(content=initial_auth_message))

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

        # Construct the public URL for the temporary file
        NGROK_URL = os.getenv("NGROK_URL")
        if not NGROK_URL:
             print("WARNING: NGROK_URL not set. Media forwarding URL will not be publicly accessible.")
             public_media_url = f"http://localhost:5000/media/{temp_file_name}"
        else:
             public_media_url = f"{NGROK_URL}/media/{temp_file_name}"

        print(f"Public media URL for forwarding: {public_media_url}")

        # Now, forward the media using the public URL
        message = twilio_client.messages.create(
            from_=TWILIO_WHATSAPP_NUMBER,
            to=FORWARD_TO_WHATSAPP_NUMBER,
            media_url=[public_media_url], # <--- Pass the publicly accessible HTTP/HTTPS URL
            body=f"Image from {sender_whatsapp_id} for new case submission."
        )
        print(f"Media forwarded. Message SID: {message.sid}")

        # Schedule temporary file for deletion after a delay
        delete_file_after_delay(temp_file_path, delay=30) # Give Twilio 30 seconds to fetch
        return True
    except requests.exceptions.HTTPError as e:
        print(f"HTTP Error downloading media from Twilio: {e.response.status_code} - {e.response.text}")
        # Clean up immediately if download failed
        if temp_file_name and os.path.exists(os.path.join(MEDIA_TEMP_DIR, temp_file_name)):
            os.remove(os.path.join(MEDIA_TEMP_DIR, temp_file_name))
        return False
    except Exception as e:
        print(f"Error forwarding media (after download attempt): {e}")
        # Clean up immediately if error occurred
        if temp_file_name and os.path.exists(os.path.join(MEDIA_TEMP_DIR, temp_file_name)):
            os.remove(os.path.join(MEDIA_TEMP_DIR, temp_file_name))
        return False
    # No `finally` block here for deletion, as it's handled by `delete_file_after_delay`

def handle_bot_logic(user_id, message_body, num_media, media_urls):
    """
    Integrates the bot's logic from mainlogic.py to process a single message.
    This function will be called for each incoming WhatsApp message.
    """
    session = user_sessions[user_id]
    app_state = session['app_state']
    calendar_service = session['calendar_service']
    auth_memory = session['auth_memory']
    sched_memory = session['sched_memory']
    current_stage = session['current_stage']
    last_question = session['last_question']

    # --- DEBUGGING PRINTS ---
    print(f"\n--- handle_bot_logic for User: {user_id} ---")
    print(f"Incoming message: '{message_body}'")
    print(f"Current stage: {current_stage}")
    print(f"Num media: {num_media}, Media URLs: {media_urls}")
    print(f"App state before processing: {app_state}")


    bot_response = "I'm sorry, I couldn't process your request." # Default response

    if not calendar_service:
        print("Calendar service not initialized.")
        return "Sorry, I'm unable to connect to the calendar service at the moment. Please try again later."

    auth_tools, scheduling_tools = create_tools(calendar_service, app_state)
    output_parser = StrOutputParser()

    # --- Authorization Stage ---
    if current_stage == 'auth':
        print("Processing in 'auth' stage...")
        auth_prompt = hub.pull("hwchase17/structured-chat-agent") + '''Important:
- If the AuthorizationChecker tool says the user is NOT authorized,
  do NOT call the same tool again.
- Instead, collect missing information: name, email, clinic, and license number.
- Then use the DentistRegistrar tool with that data.'''

        auth_agent = create_structured_chat_agent(llm=llm, tools=auth_tools, prompt=auth_prompt)
        auth_executor = AgentExecutor.from_agent_and_tools(
            agent=auth_agent, tools=auth_tools, verbose=True, memory=auth_memory, handle_parsing_errors=True
        )

        auth_memory.chat_memory.add_message(HumanMessage(content=message_body))
        try:
            response = auth_executor.invoke({"input": message_body})
            bot_response = response["output"]
            print(f"Auth agent raw response: {response}")
            print(f"Auth bot_response: {bot_response}")
            auth_memory.chat_memory.add_message(AIMessage(content=bot_response))
        except Exception as e:
            print(f"Error during auth agent invocation: {e}")
            bot_response = "An error occurred during authorization. Please try again."

        if app_state['state'] == 'registered':
            session['current_stage'] = 'intent'
            bot_response = "Welcome to 3D-Align. How can I assist you today?"
            auth_memory.clear()
            print(f"Transitioned to 'intent' stage. Bot response: {bot_response}")


    # --- Intent Detection Stage ---
    elif current_stage == 'intent':
        print("Processing in 'intent' stage...")
        def capture_intent(x):
            app_state['cap'] = x
            print(f"Captured intent (app_state['cap']): {x}")
            return x

        intent_classification_prompt = ChatPromptTemplate.from_messages([
            ("system", "You are an helpful assistant"),
            ("human", """Your job is to identify if the user has a new case file or patient he would like to submit or he wants to track existing case or patient
                            Here is the User Input : {input}
                            Output shoul be one word only : submit_case or track_case or none""")
        ])
        submit_case_prompt = ChatPromptTemplate.from_messages([
            ("system", "You are an assistant helping dentists submit new aligner cases."),
            ("human", "ask the user to send images for the new case he wants to submit so that we can get quotation talk directly to the user")
        ])
        track_case_prompt = ChatPromptTemplate.from_messages([
            ("system", "You are an assistant that tracks case progress."), ("human", "ask for the case Id user wants to track")
        ])
        other_help_prompt = ChatPromptTemplate.from_messages([
            ("system", "You are an assistant helping with general queries."), ("human", "{input}")
        ])

        intent_chain = intent_classification_prompt | model | output_parser
        branches = RunnableBranch(
            (lambda x: "submit_case" in x, RunnableLambda(lambda _: {}) | submit_case_prompt | model | output_parser),
            (lambda x: "track_case" in x, RunnableLambda(lambda _: {}) | track_case_prompt | model | output_parser),
            other_help_prompt | model | output_parser
        )
        main_chain = intent_chain | RunnableLambda(capture_intent) | branches

        try:
            response = main_chain.invoke({"input": message_body})
            bot_response = response
            print(f"Intent chain raw response: {response}")
            print(f"Intent stage bot_response: {bot_response}")
        except Exception as e:
            print(f"Error during intent chain invocation: {e}")
            bot_response = "An error occurred while determining your intent. Please try again."


        if 'submit_case' in app_state['cap']:
            session['current_stage'] = 'awaiting_images'
            bot_response = "Please send the images for the case now. You can send them one by one or all at once. Type 'DONE' when you have sent all images."
            print(f"Transitioned to 'awaiting_images' stage. Bot response: {bot_response}")
        elif 'track_case' in app_state['cap']:
            bot_response = "Please provide the case ID or patient name you'd like to track."
            session['current_stage'] = 'tracking_case'
            print(f"Transitioned to 'tracking_case' stage. Bot response: {bot_response}")
        elif app_state['cap'] == 'none':
            print(f"Intent classified as 'none'. Bot response (from 'other_help_prompt'): {bot_response}")
            pass # The bot_response would be set by the main_chain.invoke directly

    # --- Awaiting Images Stage ---
    elif current_stage == 'awaiting_images':
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
                bot_response = f"Received and forwarded {successful_forwards} image(s). You have sent a total of {session['image_count']} image(s). Send more or type 'DONE' when you have sent all images."
            else:
                bot_response = "There was an error forwarding your images. Please try again or type 'DONE' if you have nothing to send."
            print(f"Bot response in 'awaiting_images' after media: {bot_response}")

        elif message_body.lower() == 'done':
            print("User typed 'DONE' in 'awaiting_images' stage.")
            if session['image_count'] > 0:
                bot_response = f"Thank you for submitting {session['image_count']} image(s). We will process them. Here is the quotation........did patient agree?"
                session['current_stage'] = 'scheduling_quote_confirm'
                session['last_question'] = "did patient agree?"
                session['image_count'] = 0 # Reset image count
                print(f"Transitioned to 'scheduling_quote_confirm'. Bot response: {bot_response}")
            else:
                bot_response = "You haven't sent any images yet. Please send images or type 'DONE' if you have nothing to send."
                print(f"Bot response: {bot_response}")
        else:
            bot_response = "Please send images for the case or type 'DONE' if you have sent all images."
            print(f"Bot response (prompt for images): {bot_response}")


    # --- Scheduling Stage (after "submit_case" intent and images received) ---
    elif current_stage == 'scheduling_quote_confirm':
        print("Processing in 'scheduling_quote_confirm' stage...")
        confirm_prompt = ChatPromptTemplate.from_messages([
            ("system", "You are an AI assistant"),
            ("human", """User was asked a yes or no question your job is to identify if the user's response was yes or no
                            this was the question asked {question}
                            Here is the user's response {input}
                            output in one word only""")
        ])
        confirm_chain = confirm_prompt | llm | output_parser

        try:
            confirmation_response = confirm_chain.invoke({"input": message_body, "question": last_question})
            session['last_question'] = None
            print(f"Confirmation response: {confirmation_response}")

            if "No" in confirmation_response:
                bot_response = "Thank you for contacting 3D-Align."
                session['current_stage'] = 'end_session'
                print(f"Transitioned to 'end_session'. Bot response: {bot_response}")
            elif "Yes" in confirmation_response:
                bot_response = "Do you have scanning machines or our technicians should bring them?"
                session['current_stage'] = 'scheduling_machine_confirm'
                session['last_question'] = "Do you have scanning machines or our technicians should bring them ?"
                print(f"Transitioned to 'scheduling_machine_confirm'. Bot response: {bot_response}")
            else:
                bot_response = "I didn't understand your response. Please say 'Yes' or 'No'."
                session['last_question'] = "did patient agree?"
                print(f"Bot response (did not understand confirm): {bot_response}")
        except Exception as e:
            print(f"Error during scheduling_quote_confirm: {e}")
            bot_response = "An error occurred while confirming. Please try again."


    elif current_stage == 'scheduling_machine_confirm':
        print("Processing in 'scheduling_machine_confirm' stage...")
        confirm_prompt = ChatPromptTemplate.from_messages([
            ("system", "You are an AI assistant"),
            ("human", """User was asked a yes or no question your job is to identify if the user's response was yes or no
                            this was the question asked {question}
                            Here is the user's response {input}
                            output in one word only""")
        ])
        confirm_chain = confirm_prompt | llm | output_parser
        try:
            machine_response = confirm_chain.invoke({"input": message_body, "question": last_question})
            session['last_question'] = None
            print(f"Machine confirmation response: {machine_response}")

            if "Yes" in machine_response or "No" in machine_response:
                bot_response = "Great! Let's decide appointment time now!!"
                session['current_stage'] = 'scheduling_appointment'
                sched_initial_message = ("""
You are a scheduling assistant.
Ask the user for a time and date they are available for a 30-minute appointment.
Once the user provides a time and date, convert it to ISO 8601 format (e.g., 2025-06-12T15:30) for the query.
Use the CheckCalendarAvailability tool to see if it's free.
If the timeslot is available then display the date and timeslot in nice format and ask for user to confirm the timeslot
Only when the user confirms the appointment use the BookCalendarAppointment or else ask for new timeslot and repeat the process
""")
                sched_memory.chat_memory.add_message(SystemMessage(content=sched_initial_message))
                print(f"Transitioned to 'scheduling_appointment'. Bot response: {bot_response}")
            else:
                bot_response = "I didn't quite catch that. Please let me know if you have scanning machines or if our technicians should bring them."
                session['last_question'] = "Do you have scanning machines or our technicians should bring them ?"
                print(f"Bot response (did not understand machine confirm): {bot_response}")
        except Exception as e:
            print(f"Error during scheduling_machine_confirm: {e}")
            bot_response = "An error occurred while confirming machine availability. Please try again."


    elif current_stage == 'scheduling_appointment':
        print("Processing in 'scheduling_appointment' stage...")
        sched_prompt = hub.pull("hwchase17/structured-chat-agent")
        sched_agent = create_structured_chat_agent(llm, tools=scheduling_tools, prompt=sched_prompt)
        sched_executor = AgentExecutor.from_agent_and_tools(
            agent=sched_agent, tools=scheduling_tools, memory=sched_memory, handle_parsing_errors=True, verbose=True
        )

        sched_memory.chat_memory.add_message(HumanMessage(content=message_body))
        try:
            response = sched_executor.invoke({"input": message_body})
            bot_response = response["output"]
            print(f"Scheduling agent raw response: {response}")
            print(f"Scheduling stage bot_response: {bot_response}")
            sched_memory.chat_memory.add_message(AIMessage(content=bot_response))
        except Exception as e:
            print(f"Error during scheduling agent invocation: {e}")
            bot_response = "An error occurred during scheduling. Please try again."

        if app_state['exi']:
            bot_response += "\nYour appointment has been successfully booked. Thank you!"
            session['current_stage'] = 'end_session'
            print(f"Transitioned to 'end_session'. Bot response: {bot_response}")

    # --- Tracking Case Stage ---
    elif current_stage == 'tracking_case':
        print("Processing in 'tracking_case' stage...")
        bot_response = f"Searching for case details related to '{message_body}'. Please wait..."
        session['current_stage'] = 'end_session'
        print(f"Transitioned to 'end_session'. Bot response: {bot_response}")

    # --- End Session ---
    elif current_stage == 'end_session':
        print("Processing in 'end_session' stage...")
        bot_response = "Thank you for using 3D-Align services. Have a great day!"
        print(f"Bot response: {bot_response}")

    # --- Final check before returning ---
    print(f"App state AFTER processing: {app_state}")
    print(f"Final bot_response to be sent: '{bot_response}'")
    print(f"--- End handle_bot_logic ---\n")

    return bot_response


# ==============================================================================
# 4. FLASK ROUTES
# ==============================================================================
# New route to serve temporary media files
@app.route('/media/<filename>')
def serve_media(filename):
    """Serve media files from the temporary directory."""
    print(f"Attempting to serve file: {filename} from {MEDIA_TEMP_DIR}")
    return send_from_directory(MEDIA_TEMP_DIR, filename)

@app.route("/whatsapp", methods=["POST"])
def whatsapp_webhook():
    """
    Twilio webhook endpoint for incoming WhatsApp messages.
    """
    incoming_msg = request.values.get("Body", "")
    sender_id = request.values.get("From", "")
    num_media = int(request.values.get("NumMedia", 0))
    media_urls = []

    if num_media > 0:
        for i in range(num_media):
            media_url = request.values.get(f"MediaUrl{i}")
            media_urls.append(media_url)
            print(f"Received media URL: {media_url}")

    initialize_user_session(sender_id)

    bot_response = handle_bot_logic(sender_id, incoming_msg, num_media, media_urls)

    resp = MessagingResponse()
    # Ensure bot_response is not None or empty, otherwise Twilio might not send a message
    if bot_response:
        msg = resp.message(bot_response)
    else:
        print("WARNING: bot_response was empty or None. Not sending a message.")
        # Optionally, send a default error message if bot_response is empty
        # msg = resp.message("Sorry, I encountered an issue and couldn't respond.")

    return str(resp)

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
    # For local testing, ensure NGROK_URL is set in your .env or manually assigned here.
    # e.g., os.environ['NGROK_URL'] = "YOUR_CURRENT_NGROK_HTTPS_URL"
    # Make sure to run ngrok: `ngrok http 5000` and copy the HTTPS forwarding URL.
    if not os.getenv("NGROK_URL"):
        print("\n*** IMPORTANT: NGROK_URL environment variable is NOT set. ***")
        print("    Media forwarding will likely FAIL as Twilio cannot access localhost.")
        print("    Please run ngrok (e.g., `ngrok http 5000`) and set NGROK_URL in your .env file")
        print("    to the HTTPS URL ngrok provides (e.g., https://xxxxxxxxxxxx.ngrok-free.app).\n")

    app.run(debug=True, port=5000)