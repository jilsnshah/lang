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


# --- LLM Initialization (from mainlogic.py) ---
llm = ChatOpenAI(
    model_name="deepseek/deepseek-r1-0528:free",
    openai_api_key=os.getenv("OPENROUTER_API_KEY"), # Assuming your .env has TOGETHER_API_KEY
    openai_api_base="https://openrouter.ai/api/v1",
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
            'app_state': None,
            'calendar_service': get_calendar_service_oauth(),
            'auth_memory': ConversationBufferMemory(memory_key="chat_history", return_messages=True),
            'sched_memory': ConversationBufferMemory(memory_key="chat_history", return_messages=True),
            'current_stage': 'auth',
            'last_question': None,
            'image_count': 0,
            'expected_images': 0
            # No longer need 'location' here as the agent will handle it
        }

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
        if temp_file_name and os.path.exists(os.path.join(MEDIA_TEMP_DIR, temp_file_name)):
            os.remove(os.path.join(MEDIA_TEMP_DIR, temp_file_name))
        return False
    except Exception as e:
        print(f"Error forwarding media (after download attempt): {e}")
        if temp_file_name and os.path.exists(os.path.join(MEDIA_TEMP_DIR, temp_file_name)):
            os.remove(os.path.join(MEDIA_TEMP_DIR, temp_file_name))
        return False


def handle_bot_logic(user_id, message_body, num_media, media_urls,session = user_sessions):
    """
    Integrates the bot's logic from mainlogic.py to process a single message.
    """
    global output_parser
    session = user_sessions[user_id]
    confirm_prompt = ChatPromptTemplate.from_messages([
            ("system", "You are an AI assistant"),
            ("human", """User was asked a yes or no question your job is to identify if the user's response was yes or no
                         this was the question asked {question}
                         Here is the user's response {input}
                         output in one word only""")
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

    auth_tools, scheduling_tools = create_tools(session['calendar_service'], session['app_state'])
    output_parser = StrOutputParser()

    # --- Authorization Stage ---
    if session['current_stage'] == 'auth':
        print("Processing in 'auth' stage...")

        # Clean phone number from Twilio format
        pure_sender_phone = user_id.replace("whatsapp:", "").strip()

        # Manually check authorization
        auth_result = auth_tools[0](user_id)

        if isinstance(auth_result, str) and "authorized" in auth_result.lower():
            # Already authorized: move to next stage
            session['current_stage'] = 'intent'
            bot_response = "Welcome to 3D-Align. How can I assist you today?"
            print("Authorization confirmed. Transitioning to 'intent' stage.")

        else:
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
            auth_agent = create_structured_chat_agent(llm=llm, tools=[auth_tools[1]], prompt=registration_prompt)
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
            bot_response = """Thank you for considering 3D-Align for your aligner case.
Kindly share clear images of the patient's case so we can prepare an accurate quotation. Once you receive the quotation, you may discuss it with the patient, and upon confirmation, we’ll proceed with the next steps.
"""
            print(f"Transitioned to 'awaiting_images' stage. Bot response: {bot_response}")
        elif 'track_case' in session['app_state']:
            bot_response = "Please provide the case ID or patient name you'd like to track."
            session['current_stage'] = 'tracking_case'
            print(f"Transitioned to 'tracking_case' stage. Bot response: {bot_response}")
        elif session['app_state'] == 'none':
            bot_response = llm.invoke({"input":message_body})

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
            if session['image_count'] > 0:
                bot_response = f"Thank you for submitting { session['image_count'] } image(s). We will review them and get back to you with a quotation shortly"
                session['current_stage'] = 'awaiting_quote'
                session['image_count'] = 0 # Reset image count
                caseid = str(uuid.uuid4())
                session[caseid] ={}
                session['active'] = caseid
                session[caseid]['quote'] = "..." 
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
                bot_response = "Great! Let's schedule the appointment." # A simple transition message
                session['current_stage'] = 'scheduling_appointment'
                
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

    elif session['current_stage'] == 'scheduling_appointment':
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

    return bot_response


# ==============================================================================
# 4. FLASK ROUTES
# ==============================================================================
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
    latitude = request.form.get("Latitude")
    longitude = request.form.get("Longitude")
    
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

    initialize_user_session(sender_id)

    bot_response = handle_bot_logic(sender_id, incoming_msg, num_media, media_urls, user_sessions)

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

    app.run(debug=True, port=5000)