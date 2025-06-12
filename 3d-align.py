# ==============================================================================
# 1. IMPORTS
# ==============================================================================
import os
import datetime
import pytz

# Third-party libraries
from dotenv import load_dotenv

# Google API imports
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.auth.exceptions import RefreshError

# LangChain imports
from langchain import hub
from langchain.agents import AgentExecutor, create_structured_chat_agent
from langchain.memory import ConversationBufferMemory
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.tools import Tool
from langchain.prompts import ChatPromptTemplate
from langchain.schema.output_parser import StrOutputParser
from langchain.schema.runnable import RunnableBranch, RunnableLambda, RunnableMap
from langchain_openai import ChatOpenAI

# ==============================================================================
# 2. CONFIGURATION AND INITIALIZATION
# ==============================================================================
load_dotenv()

# --- Configuration Constants ---
CLIENT_SECRET_FILE = 'client_secret.json'
TOKEN_FILE = 'token.json'
CALENDAR_ID = 'jilsnshah@gmail.com'
SCOPES = ['https://www.googleapis.com/auth/calendar']

# --- LLM Initialization ---
# Note: It is best practice to load keys from environment variables, not hardcode them.
# Example: openai_api_key=os.getenv("TOGETHER_API_KEY")
llm = ChatOpenAI(
    model_name="meta-llama/Llama-3.3-70B-Instruct-Turbo",
    openai_api_key="a18c9313356c6d115edee12b37a77f5ebce4656361077556cb792851963faedf",
    openai_api_base="https://api.together.xyz/v1",
)
model = llm # Using 'model' as an alias for consistency with the original code.

# --- Mock Dentist Database ---
authorized_dentists = {
    "dr.jils@clinic.com": {
        "name": "Dr. Jils Shah",
        "clinic": "Smile Dental Studio",
        "license": "GJ12345"
    }
}

# ==============================================================================
# 3. GOOGLE CALENDAR SERVICE
# ==============================================================================
def get_calendar_service_oauth():
    """
    Initializes and returns the Google Calendar API service using OAuth 2.0 Client ID.
    Handles user authentication via browser for the first run and uses token.json thereafter.
    """
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("Refreshing existing credentials...")
            try:
                creds.refresh(Request())
            except RefreshError as e:
                print(f"Error refreshing token: {e}. Re-authenticating...")
                if os.path.exists(TOKEN_FILE):
                    os.remove(TOKEN_FILE)
                flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_FILE, SCOPES)
                creds = flow.run_local_server(port=0)
        else:
            print("No valid token.json found or token expired. Starting new authentication flow...")
            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_FILE, SCOPES)
            creds = flow.run_local_server(port=0)

        with open(TOKEN_FILE, 'w') as token:
            token.write(creds.to_json())
        print(f"Authentication successful and token saved to {TOKEN_FILE}.")

    try:
        service = build('calendar', 'v3', credentials=creds)
        print("Google Calendar service initialized successfully.")
        return service
    except HttpError as error:
        print(f"An HTTP error occurred while building the service: {error}")
        return None
    except Exception as e:
        print(f"An unexpected error occurred during service initialization: {e}")
        return None

# ==============================================================================
# 4. TOOL DEFINITIONS
# ==============================================================================
def create_tools(calendar_service, app_state):
    """Creates all the necessary tools for the agents."""

    # --- Tool Functions ---
    def book_calendar_appointment(iso_datetime_str: str) -> str:
        """
        Books a 30-minute appointment on the calendar for the specified ISO datetime string.
        """
        try:
            ahmedabad_tz = pytz.timezone('Asia/Kolkata')
            start_time = datetime.datetime.fromisoformat(iso_datetime_str)
            if start_time.tzinfo is None:
                start_time = ahmedabad_tz.localize(start_time)

            end_time = start_time + datetime.timedelta(minutes=30)

            event = {
                'summary': '3D-Align Scanning Appointment',
                'description': 'Patient scanning session for 3D-Align aligners.',
                'start': {
                    'dateTime': start_time.isoformat(),
                    'timeZone': str(ahmedabad_tz),
                },
                'end': {
                    'dateTime': end_time.isoformat(),
                    'timeZone': str(ahmedabad_tz),
                },
            }

            created_event = calendar_service.events().insert(calendarId=CALENDAR_ID, body=event).execute()
            print(f"Event created: {created_event.get('htmlLink')}")
            
            app_state['exi'] = True # Set flag to exit loop after booking
            return f"Success! The appointment has been booked for {start_time.strftime('%A, %B %d at %I:%M %p')}."

        except HttpError as e:
            return f"Failed to book appointment due to a Google API error: {e}"
        except Exception as e:
            return f"An unexpected error occurred while booking the appointment: {e}"
    def check_calendar_availability(iso_datetime_str: str) -> str:
        """
        Check if a given time in ISO 8601 format (e.g., 2025-06-11T15:30) is free.
        """
        try:
            dt_object = datetime.datetime.fromisoformat(iso_datetime_str)
            ahmedabad_tz = pytz.timezone('Asia/Kolkata')
            if dt_object.tzinfo is None:
                localized_dt = ahmedabad_tz.localize(dt_object)
                start_time_utc = localized_dt.astimezone(pytz.utc)
            else:
                start_time_utc = dt_object.astimezone(pytz.utc)

            end_time_utc = start_time_utc + datetime.timedelta(minutes=30)
            events_result = calendar_service.events().list(
                calendarId=CALENDAR_ID, timeMin=start_time_utc.isoformat(),
                timeMax=end_time_utc.isoformat(), singleEvents=True, orderBy='startTime'
            ).execute()
            events = events_result.get('items', [])

            if not events:
                return f"The slot at {iso_datetime_str} is available on {CALENDAR_ID}."
            else:
                summary = events[0].get('summary', 'an unknown event')
                return f"The slot at {iso_datetime_str} is NOT available on {CALENDAR_ID} due to an event: '{summary}'."
        except ValueError as e:
            return f"Invalid datetime format. Please use ISO 8601 (e.g., 2025-06-11T15:30). Error: {e}"
        except HttpError as e:
            return f"Failed to check calendar due to a Google API error: {e}"
        except Exception as e:
            return f"An unexpected error occurred during calendar check: {e}"

    def confirm_appointment_and_exit(*args, **kwargs):
        """Sets the exit flag when an appointment is confirmed."""
        app_state['exi'] = True

    def check_authorization(email: str) -> str:
        """Checks authorization and updates state."""
        if email.strip().lower() in authorized_dentists:
            app_state['state'] = "registered"
            return f"{authorized_dentists[email.strip().lower()]['name']} is already authorized."
        else:
            return {
                "authorized": False, "reason": "Dentist not found",
                "required_fields": ["name", "email", "clinic", "license"]
            }

    def register_dentist(details: str) -> str:
        """Registers a new dentist and updates state."""
        try:
            name, email, clinic, license_number = [x.strip() for x in details.split(",")]
            authorized_dentists[email.lower()] = {
                "name": name, "clinic": clinic, "license": license_number
            }
            app_state['state'] = "registered"
            return f"{name} has been registered and is now authorized."
        except Exception:
            return "Invalid format. Please use: Name, Email, Clinic, License Number"

    # --- Tool Instantiation ---
    auth_tools = [
        Tool(
            name="AuthorizationChecker",
            func=check_authorization,
            description="Check if a dentist is authorized using their email address."
        ),
        Tool(
            name="DentistRegistrar",
            func=register_dentist,
            description="Register a new dentist. Input format: Name, Email, Clinic, License Number."
        )
    ]

    scheduling_tools = [
        Tool(
            name="CheckCalendarAvailability",
            func=check_calendar_availability,
            description="Check if a given time in ISO format (e.g. 2025-06-11T15:30) is free on the client's calendar."
        ),
        Tool(
            name="BookCalendarAppointment",
            func=book_calendar_appointment,
            description="Use this final tool to book the appointment on the calendar. This should only be used when the user explicitly confirms an available timeslot. The input MUST be the ISO datetime string of the confirmed slot (e.g., '2025-06-13T15:00:00')."
        )
    ]

    return auth_tools, scheduling_tools


# ==============================================================================
# 5. MAIN EXECUTION LOGIC
# ==============================================================================
if __name__ == "__main__":
    # --- State Management ---
    # Using a dictionary for state to avoid global variables
    app_state = {
        'state': None,  # For authorization status
        'cap': "none",  # For intent capture
        'exi': False    # For exiting the scheduling loop
    }

    # --- Initializations ---
    calendar_service = get_calendar_service_oauth()
    if not calendar_service:
        print("Exiting: Could not initialize calendar service.")
        exit()

    auth_tools, scheduling_tools = create_tools(calendar_service, app_state)
    output_parser = StrOutputParser()

    # --- STAGE 1: AUTHORIZATION ---
    print("--- Starting Authorization Stage ---")
    auth_prompt = hub.pull("hwchase17/structured-chat-agent") + '''Important:
- If the AuthorizationChecker tool says the user is NOT authorized,
  do NOT call the same tool again.
- Instead, collect missing information: name, email, clinic, and license number.
- Then use the RegisterDentist tool with that data.'''
    auth_memory = ConversationBufferMemory(memory_key="chat_history", return_messages=True)
    initial_message = (
        "You are an AI assistant that helps general dentists get authorized to submit aligner cases.\n"
        "1. First ask the user to provide their email address.\n"
        "2. Use AuthorizationChecker to check if they are authorized.\n"
        "3. If not authorized, ask them for their details in this format: Name, Email, Clinic, License Number.\n"
        "4. Use DentistRegistrar to register them only if you have all Name Email Clinic License Number of the user.\n"
        "5. After the user is authorized dont use DentistRegistrar directly, say: 'Welcome to 3D-Align. How can I assist you today?'"
    )
    auth_memory.chat_memory.add_message(SystemMessage(content=initial_message))
    auth_agent = create_structured_chat_agent(llm=llm, tools=auth_tools, prompt=auth_prompt)
    auth_executor = AgentExecutor.from_agent_and_tools(
        agent=auth_agent, tools=auth_tools, verbose=True, memory=auth_memory, handle_parsing_errors=True
    )

    while app_state['state'] != 'registered':
        user_input = input("User: ")
        if user_input.lower() == "exit":
            break
        auth_memory.chat_memory.add_message(HumanMessage(content=user_input))
        response = auth_executor.invoke({"input": user_input})
        print("Bot:", response["output"])
        auth_memory.chat_memory.add_message(AIMessage(content=response["output"]))

    # --- STAGE 2: INTENT DETECTION ---
    if app_state['state'] == 'registered':
        print("\n--- Starting Intent Detection Stage ---")
        print("Bot: Welcome to 3D-Align. How can I assist you today?")

        def capture_intent(x):
            app_state['cap'] = x
            return x

        intent_classification_prompt = ChatPromptTemplate.from_messages([
            ("system", "You are an helpful assistant"),
            ("human", """Your job is to identify if the user has a new case file or patient he would like to submit or he wants to track existing case or patient
                        Here is the User Input : {input}
                        Output shoul be one word only : submit_case or track_case or none""")
        ])
        submit_case_prompt = ChatPromptTemplate.from_messages([
            ("system", "You are an assistant helping dentists submit new aligner cases."),
            ("human", "Ask the User to submit images of the case so that we can provide further details and quotation of it, ask in just 1 or 2 sentences")
        ])
        track_case_prompt = ChatPromptTemplate.from_messages([
            ("system", "You are an assistant that tracks case progress."), ("human", "")
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

        while app_state['cap'] == "none":
            help_input = input("User: ")
            if help_input.lower() == "exit":
                break
            response = main_chain.invoke({"input": help_input})
            print("Bot:", response)

    # --- STAGE 3: SCHEDULING ---
    if 'submit_case' in app_state['cap']:
        print("\n--- Starting Scheduling Stage ---")
        confirm_prompt = ChatPromptTemplate.from_messages([
            ("system", "You are an AI assistant"),
            ("human", """User was asked a yes or no question your job is to identify if the user's response was yes or no
                        this was the question asked {question}
                        Here is the user's response {input}
                        output in one word only""")
        ])
        confirm_chain = confirm_prompt | llm | output_parser

        print('Bot:', "Thank you for approaching 3D-Align we will get back to you soon")
        print('Bot:', 'Here is the quotation........did patient agree ?')
        confirm = confirm_chain.invoke({"input": input("User :"), "question": "did patient agree?"})

        if "No" in confirm:
            print("Thank you for contacting 3D-Align")
        elif "Yes" in confirm:
            print("Do you have scanning machines or our technicians should bring them ?")
            machine = confirm_chain.invoke({"question": "Do you have scanning machines or our technicians should bring them ?", "input": input("User :")})
            print("Bot:", machine)
            print("Bot: great let's decide appointment time now !!")

            sched_prompt = hub.pull("hwchase17/structured-chat-agent")
            sched_initial_message = ("""
You are a scheduling assistant.
Ask the user for a time and date they are available for a 30-minute appointment.
Once the user provides a time and date, convert it to ISO 8601 format (e.g., 2025-06-12T15:30) for the query.
Use the CheckCalendarAvailability tool to see if it's free.
If the timeslot is available then display the date and timeslot in nice format and ask for user to confirm the timeslot
Only when the user confirms the appointment use the BookCalendarAppointment or else ask for confirmation
If user rejects the timeslot ask for new timeslot and repeat the process
""")
            sched_memory = ConversationBufferMemory(memory_key="chat_history", return_messages=True)
            sched_memory.chat_memory.add_message(SystemMessage(content=sched_initial_message))
            sched_agent = create_structured_chat_agent(llm, tools=scheduling_tools, prompt=sched_prompt)
            sched_executor = AgentExecutor.from_agent_and_tools(
                agent=sched_agent, tools=scheduling_tools, memory=sched_memory, handle_parsing_errors=True, verbose=True
            )

            while not app_state['exi']:
                user_input = input("User: ")
                if user_input.lower() in ["exit", "quit"]:
                    break
                response = sched_executor.invoke({"input": user_input})
                print("Bot:", response["output"])

    print("\n--- End of session ---")