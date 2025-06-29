"""
Google Sheets Manager for Dental Aligner Production System
Handles all Google Sheets operations for customer and case management
"""

import os
import json
import logging
from typing import List, Dict, Any, Optional
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from dotenv import load_dotenv
import pickle

# Load environment variables
load_dotenv()

class GoogleSheetsManager:
    """
    Manages Google Sheets operations for dental aligner production system.
    Provides functionality to:
    - Read customer/dentist data from sheets
    - Update case statuses
    - Add new cases
    - Sync data between sheets and application
    """
    
    def __init__(self, spreadsheet_id: Optional[str] = None, credentials_file: Optional[str] = None):
        """
        Initialize Google Sheets Manager
        
        Args:
            spreadsheet_id: Google Sheets ID (can be set via environment variable)
            credentials_file: Path to Google credentials JSON file
        """
        self.spreadsheet_id = spreadsheet_id or os.getenv("GOOGLE_SHEETS_ID")
        self.credentials_file = credentials_file or os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")
        self.token_file = "token.pickle"
        
        # Google Sheets API scopes
        self.scopes = [
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/drive.readonly'
        ]
        
        self.service = None
        self._authenticate()
        
        # Default sheet names
        self.customers_sheet = "Customers"
        self.cases_sheet = "Cases"
        self.production_sheet = "Production"
        
        logging.basicConfig(level=logging.INFO)
        self.logger = logging.getLogger(__name__)

    def _authenticate(self):
        """Authenticate with Google Sheets API"""
        creds = None
        
        # Load existing token
        if os.path.exists(self.token_file):
            with open(self.token_file, 'rb') as token:
                creds = pickle.load(token)
        
        # If there are no (valid) credentials available, let the user log in
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                except Exception as e:
                    self.logger.error(f"Error refreshing token: {e}")
                    creds = None
            
            if not creds:
                if not os.path.exists(self.credentials_file):
                    raise FileNotFoundError(
                        f"Google credentials file not found: {self.credentials_file}\n"
                        "Please download credentials.json from Google Cloud Console"
                    )
                
                flow = InstalledAppFlow.from_client_secrets_file(
                    self.credentials_file, self.scopes
                )
                creds = flow.run_local_server(port=0)
            
            # Save the credentials for the next run
            with open(self.token_file, 'wb') as token:
                pickle.dump(creds, token)
        
        self.service = build('sheets', 'v4', credentials=creds)

    def get_customers(self) -> List[Dict[str, Any]]:
        """
        Get all customers/dentists from the Google Sheet
        
        Returns:
            List of customer dictionaries with keys: dentist_name, phone, email, clinic_name, etc.
        """
        try:
            # Read from Customers sheet
            range_name = f"{self.customers_sheet}!A:Z"
            result = self.service.spreadsheets().values().get(
                spreadsheetId=self.spreadsheet_id,
                range=range_name
            ).execute()
            
            values = result.get('values', [])
            if not values:
                self.logger.warning("No customer data found in sheet")
                return []
            
            # First row should contain headers
            headers = values[0]
            customers = []
            
            for row in values[1:]:
                # Pad row with empty strings if it's shorter than headers
                while len(row) < len(headers):
                    row.append('')
                
                customer = dict(zip(headers, row))
                customers.append(customer)
            
            self.logger.info(f"Retrieved {len(customers)} customers from sheet")
            return customers
            
        except HttpError as error:
            self.logger.error(f"Error reading customers from sheet: {error}")
            raise

    def get_cases(self) -> List[Dict[str, Any]]:
        """
        Get all cases from the Google Sheet
        
        Returns:
            List of case dictionaries
        """
        try:
            range_name = f"{self.cases_sheet}!A:Z"
            result = self.service.spreadsheets().values().get(
                spreadsheetId=self.spreadsheet_id,
                range=range_name
            ).execute()
            
            values = result.get('values', [])
            if not values:
                return []
            
            headers = values[0]
            cases = []
            
            for row in values[1:]:
                while len(row) < len(headers):
                    row.append('')
                
                case = dict(zip(headers, row))
                cases.append(case)
            
            return cases
            
        except HttpError as error:
            self.logger.error(f"Error reading cases from sheet: {error}")
            raise

    def add_case(self, case_data: Dict[str, Any]) -> bool:
        """
        Add a new case to the Google Sheet
        
        Args:
            case_data: Dictionary containing case information
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Get current headers
            headers_range = f"{self.cases_sheet}!1:1"
            headers_result = self.service.spreadsheets().values().get(
                spreadsheetId=self.spreadsheet_id,
                range=headers_range
            ).execute()
            
            headers = headers_result.get('values', [[]])[0]
            
            # If no headers exist, create them
            if not headers:
                headers = [
                    'case_id', 'user_id', 'patient_name', 'dentist_name', 
                    'status', 'created_at', 'updated_at', 'delivery_status',
                    'notes', 'priority'
                ]
                
                # Write headers
                self.service.spreadsheets().values().update(
                    spreadsheetId=self.spreadsheet_id,
                    range=f"{self.cases_sheet}!A1",
                    valueInputOption='RAW',
                    body={'values': [headers]}
                ).execute()
            
            # Prepare row data based on headers
            row_data = []
            for header in headers:
                row_data.append(str(case_data.get(header, '')))
            
            # Find next empty row
            range_name = f"{self.cases_sheet}!A:A"
            result = self.service.spreadsheets().values().get(
                spreadsheetId=self.spreadsheet_id,
                range=range_name
            ).execute()
            
            existing_rows = len(result.get('values', []))
            next_row = existing_rows + 1
            
            # Add the new case
            insert_range = f"{self.cases_sheet}!A{next_row}"
            self.service.spreadsheets().values().update(
                spreadsheetId=self.spreadsheet_id,
                range=insert_range,
                valueInputOption='RAW',
                body={'values': [row_data]}
            ).execute()
            
            self.logger.info(f"Added new case {case_data.get('case_id')} to sheet")
            return True
            
        except HttpError as error:
            self.logger.error(f"Error adding case to sheet: {error}")
            raise

    def update_case_status(self, case_id: str, status: str, notes: str = "") -> bool:
        """
        Update case status in the Google Sheet
        
        Args:
            case_id: ID of the case to update
            status: New status
            notes: Optional notes
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Find the case row
            cases = self.get_cases()
            case_row = None
            
            for i, case in enumerate(cases):
                if case.get('case_id') == case_id:
                    case_row = i + 2  # +2 because sheet is 1-indexed and has headers
                    break
            
            if case_row is None:
                self.logger.error(f"Case {case_id} not found in sheet")
                return False
            
            # Update status column (assuming status is in column E - index 4)
            status_range = f"{self.cases_sheet}!E{case_row}"
            self.service.spreadsheets().values().update(
                spreadsheetId=self.spreadsheet_id,
                range=status_range,
                valueInputOption='RAW',
                body={'values': [[status]]}
            ).execute()
            
            # Update notes if provided (assuming notes is in column I - index 8)
            if notes:
                notes_range = f"{self.cases_sheet}!I{case_row}"
                self.service.spreadsheets().values().update(
                    spreadsheetId=self.spreadsheet_id,
                    range=notes_range,
                    valueInputOption='RAW',
                    body={'values': [[notes]]}
                ).execute()
            
            # Update timestamp (assuming updated_at is in column G - index 6)
            import time
            timestamp = str(int(time.time()))
            timestamp_range = f"{self.cases_sheet}!G{case_row}"
            self.service.spreadsheets().values().update(
                spreadsheetId=self.spreadsheet_id,
                range=timestamp_range,
                valueInputOption='RAW',
                body={'values': [[timestamp]]}
            ).execute()
            
            self.logger.info(f"Updated case {case_id} status to {status}")
            return True
            
        except HttpError as error:
            self.logger.error(f"Error updating case status: {error}")
            raise

    def create_sheets_if_not_exist(self) -> bool:
        """
        Create the required sheets if they don't exist
        
        Returns:
            True if successful
        """
        try:
            # Get existing sheets
            sheet_metadata = self.service.spreadsheets().get(
                spreadsheetId=self.spreadsheet_id
            ).execute()
            
            existing_sheets = [sheet['properties']['title'] 
                             for sheet in sheet_metadata['sheets']]
            
            required_sheets = [self.customers_sheet, self.cases_sheet, self.production_sheet]
            
            for sheet_name in required_sheets:
                if sheet_name not in existing_sheets:
                    # Create the sheet
                    request = {
                        'addSheet': {
                            'properties': {
                                'title': sheet_name
                            }
                        }
                    }
                    
                    self.service.spreadsheets().batchUpdate(
                        spreadsheetId=self.spreadsheet_id,
                        body={'requests': [request]}
                    ).execute()
                    
                    self.logger.info(f"Created sheet: {sheet_name}")
                    
                    # Add headers for each sheet
                    if sheet_name == self.customers_sheet:
                        headers = [
                            'dentist_name', 'phone', 'email', 'clinic_name', 
                            'address', 'city', 'state', 'subscription_type',
                            'created_at', 'last_contact'
                        ]
                    elif sheet_name == self.cases_sheet:
                        headers = [
                            'case_id', 'user_id', 'patient_name', 'dentist_name',
                            'status', 'created_at', 'updated_at', 'delivery_status',
                            'notes', 'priority'
                        ]
                    elif sheet_name == self.production_sheet:
                        headers = [
                            'case_id', 'production_stage', 'started_at', 'completed_at',
                            'assigned_to', 'estimated_completion', 'notes'
                        ]
                    
                    # Write headers
                    self.service.spreadsheets().values().update(
                        spreadsheetId=self.spreadsheet_id,
                        range=f"{sheet_name}!A1",
                        valueInputOption='RAW',
                        body={'values': [headers]}
                    ).execute()
            
            return True
            
        except HttpError as error:
            self.logger.error(f"Error creating sheets: {error}")
            raise

    def sync_cases_to_sheet(self, cases: List[Dict[str, Any]]) -> bool:
        """
        Sync all cases to the Google Sheet (bulk update)
        
        Args:
            cases: List of case dictionaries
            
        Returns:
            True if successful
        """
        try:
            # Clear existing data (except headers)
            clear_range = f"{self.cases_sheet}!A2:Z"
            self.service.spreadsheets().values().clear(
                spreadsheetId=self.spreadsheet_id,
                range=clear_range
            ).execute()
            
            if not cases:
                return True
            
            # Get headers
            headers = [
                'case_id', 'user_id', 'patient_name', 'dentist_name',
                'status', 'created_at', 'updated_at', 'delivery_status',
                'notes', 'priority'
            ]
            
            # Prepare data rows
            rows = []
            for case in cases:
                row = [str(case.get(header, '')) for header in headers]
                rows.append(row)
            
            # Write all data at once
            range_name = f"{self.cases_sheet}!A2"
            self.service.spreadsheets().values().update(
                spreadsheetId=self.spreadsheet_id,
                range=range_name,
                valueInputOption='RAW',
                body={'values': rows}
            ).execute()
            
            self.logger.info(f"Synced {len(cases)} cases to sheet")
            return True
            
        except HttpError as error:
            self.logger.error(f"Error syncing cases to sheet: {error}")
            raise

    def get_production_schedule(self) -> List[Dict[str, Any]]:
        """
        Get production schedule from the sheet
        
        Returns:
            List of production items
        """
        try:
            range_name = f"{self.production_sheet}!A:Z"
            result = self.service.spreadsheets().values().get(
                spreadsheetId=self.spreadsheet_id,
                range=range_name
            ).execute()
            
            values = result.get('values', [])
            if not values:
                return []
            
            headers = values[0]
            production_items = []
            
            for row in values[1:]:
                while len(row) < len(headers):
                    row.append('')
                
                item = dict(zip(headers, row))
                production_items.append(item)
            
            return production_items
            
        except HttpError as error:
            self.logger.error(f"Error reading production schedule: {error}")
            raise

    def add_production_item(self, production_data: Dict[str, Any]) -> bool:
        """
        Add a production item to the schedule
        
        Args:
            production_data: Dictionary containing production information
            
        Returns:
            True if successful
        """
        try:
            # Get headers
            headers = [
                'case_id', 'production_stage', 'started_at', 'completed_at',
                'assigned_to', 'estimated_completion', 'notes'
            ]
            
            row_data = [str(production_data.get(header, '')) for header in headers]
            
            # Find next empty row
            range_name = f"{self.production_sheet}!A:A"
            result = self.service.spreadsheets().values().get(
                spreadsheetId=self.spreadsheet_id,
                range=range_name
            ).execute()
            
            existing_rows = len(result.get('values', []))
            next_row = existing_rows + 1
            
            # Add the new production item
            insert_range = f"{self.production_sheet}!A{next_row}"
            self.service.spreadsheets().values().update(
                spreadsheetId=self.spreadsheet_id,
                range=insert_range,
                valueInputOption='RAW',
                body={'values': [row_data]}
            ).execute()
            
            self.logger.info(f"Added production item for case {production_data.get('case_id')}")
            return True
            
        except HttpError as error:
            self.logger.error(f"Error adding production item: {error}")
            raise
