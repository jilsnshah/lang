import os
import firebase_admin
from firebase_admin import db # Import the Realtime Database service
from firebase_admin import credentials # Generally not needed if using ADC, but good to know
import sys
import time
from datetime import datetime

# --- Configuration ---
# Ensure your Google Cloud Project has billing enabled and
# you have set up Application Default Credentials (ADC) for your environment.
# For local development: run 'gcloud auth application-default login' in your terminal.
# For GCP deployments: ensure a service account with Realtime Database permissions is attached.

# --- IMPORTANT: Replace with YOUR Realtime Database URL ---
# You can find this URL in your Firebase Console under Realtime Database.
# It will look something like: "https://YOUR-PROJECT-ID-default-rtdb.firebaseio.com/"
FIREBASE_DATABASE_URL = "https://diesel-ellipse-463111-a5-default-rtdb.asia-southeast1.firebasedatabase.app/" # <--- REPLACE THIS!

# --- User Identification for this CLI app ---
# Data will be stored under a path like: messages/cli_test_user_123/{message_id}
CLI_USER_ID = "cli-rtdb-test-user-123" # A static ID for CLI testing

# --- Firebase Initialization ---
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

# --- Realtime Database Operations ---

def add_message(message_text):
    """
    Adds a new message document to the user's messages path.

    Realtime Database Syntax:
    - `db.reference(path)`: Gets a reference to a specific location in the JSON tree.
    - `.child(child_name)`: Navigates to a child node.
    - `.push()`: Generates a unique, chronological key (like Firestore's auto-ID).
    - `.set(data)`: Writes data to the specified location, overwriting any existing data.
    """
    try:
        # Create a reference to the user's messages path
        # Example path: messages/cli-rtdb-test-user-123
        user_messages_ref = root_ref.child(f'messages/{CLI_USER_ID}')

        # Use push() to generate a unique key for each new message (like auto-IDs in Firestore)
        new_message_ref = user_messages_ref.push()

        # Data to be stored (Python dictionary, which becomes JSON in Realtime Database)
        data = {
            'text': message_text,
            'timestamp': datetime.now().isoformat(), # Use ISO format for easy sorting/reading
            'status': 'new'
        }

        # Set the data at the new_message_ref location
        new_message_ref.set(data)
        
        print(f"\nMessage added with key: {new_message_ref.key}")
        print(f"  Message: '{message_text}'")
        print(f"  Stored at path: {new_message_ref.path}")

    except Exception as e:
        print(f"\nERROR: Failed to add message: {e}")

def listen_to_messages():
    """
    Sets up a real-time listener for messages in the user's collection.

    Realtime Database Syntax:
    - `.listen(callback)`: Registers a callback for real-time changes at the reference's location.
                           The callback receives a `DataSnapshot` object.
    - `DataSnapshot.val()`: Retrieves the data at the snapshot's location.
    - `DataSnapshot.key`: Retrieves the key of the data at the snapshot's location.
    - Realtime Database listeners by default retrieve the *entire* subtree at the listened path.
      For sorting, you often need to fetch the data and sort it client-side,
      or use more advanced queries like `order_by_child()` or `order_by_key()`
      which are typically used with `get()` or when structuring for specific queries.
      For simple real-time updates of a list, listening to the parent and iterating is common.
    """
    user_messages_ref = root_ref.child(f'messages/{CLI_USER_ID}')

    def on_data_change(event):
        """Callback for data changes."""
        print(f"\n--- Realtime Database Update at: {datetime.now().isoformat()} ---")
        if event.data is None:
            print(f"Path '{event.path}' was deleted or is empty.")
            return

        messages_data = event.data
        if not messages_data:
            print("No messages yet.")
            return
            
        print("Current Messages:")
        # Sort messages by timestamp for display
        # IMPORTANT: Add a type check to ensure msg_data is a dictionary
        sorted_messages = []
        for key, msg_data in messages_data.items():
            if isinstance(msg_data, dict): # <--- ADDED TYPE CHECK HERE
                sorted_messages.append((key, msg_data))
            else:
                print(f"  WARNING: Skipping invalid data for key '{key}'. Expected dictionary, got {type(msg_data)}: {msg_data}")

        # Now sort only the valid dictionary entries
        sorted_messages.sort(key=lambda item: item[1].get('timestamp', ''), reverse=True) # Newest first

        for key, msg_data in sorted_messages:
            timestamp_str = msg_data.get('timestamp', 'N/A')
            text = msg_data.get('text', 'No text')
            print(f"  ID: {key}, Message: '{text}', Timestamp: {timestamp_str}")
        print("---------------------------------------")

    # Start listening for real-time updates
    # The `listen` method returns a `threading.Event` which can be used to stop the listener.
    print(f"Listening for messages in '{user_messages_ref.path}'...")
    listener_event = user_messages_ref.listen(on_data_change)
    return listener_event

def clear_all_messages():
    """
    Deletes all messages in the user's messages path.

    Realtime Database Syntax:
    - `.set(None)`: Deletes data at the specified reference. Setting a reference to `None` removes it.
    """
    try:
        user_messages_ref = root_ref.child(f'messages/{CLI_USER_ID}')
        
        # Get the current data to count how many items will be deleted
        current_data = user_messages_ref.get()
        if current_data:
            num_deleted = len(current_data)
            user_messages_ref.set(None) # Delete the entire subtree
            print(f"Successfully deleted {num_deleted} messages from '{user_messages_ref.path}'.")
        else:
            print(f"No messages found in '{user_messages_ref.path}' to clear.")

    except Exception as e:
        print(f"Error clearing messages: {e}")

# --- CLI Application Loop ---
def run_cli_app():
    """Runs the interactive command-line application."""
    print(f"\n--- Realtime Database CLI Messaging App (User: {CLI_USER_ID}) ---")
    print("Commands:")
    print("  add <your message> - Add a new message")
    print("  clear              - Clear all your messages")
    print("  exit               - Exit the app")
    print("------------------------------------------")

    # Start the real-time listener. This runs in a separate thread.
    detach_listener_event = listen_to_messages()

    try:
        while True:
            command = input("\nEnter command: ").strip().lower()
            
            if command.startswith("add "):
                message_text = command[4:].strip()
                if message_text:
                    add_message(message_text)
                else:
                    print("Usage: add <your message>")
            elif command == "clear":
                confirm = input("Are you sure you want to clear ALL messages? (yes/no): ").lower()
                if confirm == "yes":
                    clear_all_messages()
                else:
                    print("Clear operation cancelled.")
            elif command == "exit":
                print("Exiting application...")
                break
            else:
                print("Invalid command. Please use 'add <message>', 'clear', or 'exit'.")
            
            # Small pause for readability in console. The listener is async.
            time.sleep(0.1) 

    except KeyboardInterrupt:
        print("\nCtrl+C detected. Exiting application...")
    finally:
        # Detach the listener to clean up resources
        if detach_listener_event:
            detach_listener_event.set() # Signal the listener thread to stop
            print("Realtime Database listener detached.")

if __name__ == "__main__":
    run_cli_app()

