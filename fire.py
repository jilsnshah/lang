import os
import pickle
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

# --- Configuration ---
# Path to your client_secret.json file (the one you already have for Calendar API)
CLIENT_SECRET_FILE = 'client_secret.json' 
# Path to store/load user's authentication tokens (this file will be updated/overwritten)
TOKEN_FILE = 'token.json' 

# IMPORTANT: Include ALL scopes your application needs.
# This will trigger a new consent screen asking the user to approve both Calendar and Drive access.
SCOPES = [
    'https://www.googleapis.com/auth/drive',        # For Google Drive access
    'https://www.googleapis.com/auth/calendar'      # For Google Calendar access (if you still need it)
    # Add other Calendar scopes if you use more specific ones, e.g., 'https://www.googleapis.com/auth/calendar.events'
] 

# ID of the shared folder in amalthea@iitgn.ac.in's Google Drive.
# IMPORTANT: The account that authenticates via OAuth must have 'Editor' access to this folder.
SHARED_FOLDER_ID = '1o24t5XaFt4CG8ZZp1a108eF9OXJtHr-v' 

# Path to the file you want to upload from your local system
LOCAL_FILE_PATH = 'requirements.txt'
# Desired name for the file in Google Drive
FILE_NAME_IN_DRIVE = 'hello.txt' 

# --- Authentication and Service Initialization ---
def authenticate_user_oauth():
    """Authenticates a user via OAuth 2.0 and returns a Drive service object."""
    creds = None
    # The file token.json stores the user's access and refresh tokens.
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, 'rb') as token:
            creds = pickle.load(token)

    # If there are no (valid) credentials available or scopes are insufficient, let the user log in.
    # Check if existing creds have all required scopes
    if not creds or not creds.valid or set(SCOPES) != set(creds.scopes):
        if creds and creds.expired and creds.refresh_token:
            print("Access token expired or scopes insufficient, attempting to refresh/re-authorize...")
            try:
                # Attempt to refresh first, which might also pick up new scopes if minor,
                # but often a full re-auth is needed if scopes change significantly.
                creds.refresh(Request())
                if set(SCOPES) != set(creds.scopes): # Still check if all scopes were granted after refresh
                    raise ValueError("Refreshed token does not cover all required scopes.")
            except Exception as e:
                print(f"Refresh failed or scopes insufficient ({e}). Initiating full OAuth 2.0 flow...")
                flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_FILE, SCOPES)
                creds = flow.run_local_server(port=0)
        else:
            print("No valid credentials found or scopes insufficient. Initiating full OAuth 2.0 flow...")
            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_FILE, SCOPES)
            creds = flow.run_local_server(port=0)

        # Save the credentials for the next run
        with open(TOKEN_FILE, 'wb') as token:
            pickle.dump(creds, token)
        print(f"Credentials saved to {TOKEN_FILE}")

    try:
        service = build('drive', 'v3', credentials=creds)
        print("User authenticated successfully via OAuth 2.0.")
        return service
    except Exception as e:
        print(f"Error building Drive service: {e}")
        return None

# --- Upload Function (Remains unchanged) ---
def upload_file_to_drive(service, file_path, file_name, folder_id):
    """Uploads a file to a specified Google Drive folder."""
    try:
        file_metadata = {
            'name': file_name,
            'parents': [folder_id]
        }
        
        # Determine the MIME type of the file
        mime_type = "application/octet-stream"
        if file_path.lower().endswith((".jpg", ".jpeg")):
            mime_type = "image/jpeg"
        elif file_path.lower().endswith(".png"):
            mime_type = "image/png"
        elif file_path.lower().endswith(".pdf"):
            mime_type = "application/pdf"
        elif file_path.lower().endswith(".txt"):
            mime_type = "text/plain"

        media = MediaFileUpload(file_path, mimetype=mime_type, resumable=True)
        
        file = service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id,name,webViewLink'
        ).execute()

        print(f"File '{file.get('name')}' uploaded successfully to folder ID: {folder_id}")
        print(f"View link: {file.get('webViewLink')}")
        return file.get('id')

    except HttpError as error:
        print(f"An API error occurred: {error}")
        if error.resp.status == 403:
            print("Error 403: Permission denied. Ensure the authenticated Google account has 'Editor' or 'Contributor' access to the target folder.")
            print(f"Target Folder ID: {folder_id}")
        elif error.resp.status == 404:
            print(f"Error 404: Folder not found. The folder ID '{folder_id}' might be incorrect or the folder might have been moved/deleted.")
        else:
            print(f"Error details: {error.resp.status}, {error.content.decode()}")
        return None
    except FileNotFoundError:
        print(f"Error: Local file not found at '{file_path}'. Please check the path.")
        return None
    except Exception as e:
        print(f"An unexpected error occurred during upload: {e}")
        return None

# --- Main Execution ---
if __name__ == '__main__':
    # Create a dummy file for testing if it doesn't exist
    if not os.path.exists(LOCAL_FILE_PATH):
        try:
            with open(LOCAL_FILE_PATH, 'w') as f:
                f.write("This is a test file created by the OAuth app.\n")
                f.write("Timestamp: " + str(os.path.getmtime(os.path.dirname(LOCAL_FILE_PATH) + "/requirements.txt")) + "\n")
            print(f"Created a dummy file for testing at: {LOCAL_FILE_PATH}")
        except Exception as e:
            print(f"Could not create dummy file at '{LOCAL_FILE_PATH}': {e}")
            print("Please create the file manually or adjust LOCAL_FILE_PATH to an existing file.")
            exit()

    drive_service = authenticate_user_oauth()

    if drive_service:
        file_id = upload_file_to_drive(drive_service, LOCAL_FILE_PATH, FILE_NAME_IN_DRIVE, SHARED_FOLDER_ID)
        if file_id:
            print(f"File upload process completed. New file ID: {file_id}")
        else:
            print("File upload failed.")
    else:
        print("Application stopped due to authentication failure.")