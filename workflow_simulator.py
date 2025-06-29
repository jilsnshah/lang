"""
🦷 Dental Aligner Production System - Local Workflow Simulator
================================================================

This simulator allows you to test all system workflows locally with real LLM calls
but simulated external services (WhatsApp, Firebase, Google Sheets).

Features:
- Complete workflow simulation
- Real LLM integration for testing
- Simulated WhatsApp conversations
- Mock Firebase database
- Mock Google Sheets operations
- Interactive testing interface
"""

import os
import json
import time
import logging
from datetime import datetime
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict
import uuid

# Import the actual workflow logic
from prod_workflow import dental_aligner_workflow
from langchain_openai import ChatOpenAI
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

@dataclass
class SimulatedUser:
    """Represents a simulated user/dentist"""
    user_id: str
    name: str
    phone: str
    clinic: str
    stage: str = "general"
    active_case: Optional[str] = None
    last_message_time: int = 0

@dataclass
class SimulatedCase:
    """Represents a simulated case"""
    case_id: str
    user_id: str
    patient_name: str
    dentist_name: str
    status: str
    created_at: int
    updated_at: int
    delivery_status: str = "Not Started"
    notes: str = ""
    priority: str = "Normal"

class MockFirebaseDatabase:
    """Simulates Firebase Realtime Database"""
    
    def __init__(self):
        self.data = {
            "user_sessions": {},
            "cases": {},
            "production_schedule": {}
        }
        logger.info("🔥 Mock Firebase Database initialized")
    
    def child(self, path: str):
        return MockFirebaseChild(self, path)
    
    def get_data(self, path: str):
        keys = path.split('/')
        current = self.data
        for key in keys:
            if key in current:
                current = current[key]
            else:
                return None
        return current
    
    def set_data(self, path: str, value: Any):
        keys = path.split('/')
        current = self.data
        for key in keys[:-1]:
            if key not in current:
                current[key] = {}
            current = current[key]
        current[keys[-1]] = value

class MockFirebaseChild:
    """Simulates Firebase child reference"""
    
    def __init__(self, db: MockFirebaseDatabase, path: str):
        self.db = db
        self.path = path
    
    def get(self):
        return self.db.get_data(self.path)
    
    def set(self, value: Any):
        self.db.set_data(self.path, value)
    
    def update(self, value: Dict):
        current = self.db.get_data(self.path) or {}
        current.update(value)
        self.db.set_data(self.path, current)

class MockGoogleSheetsManager:
    """Simulates Google Sheets operations"""
    
    def __init__(self):
        self.customers = []
        self.cases = []
        self.production_items = []
        logger.info("📊 Mock Google Sheets Manager initialized")
    
    def get_customers(self) -> List[Dict]:
        logger.info(f"📋 Retrieved {len(self.customers)} customers from mock sheets")
        return self.customers
    
    def add_case(self, case_data: Dict) -> bool:
        self.cases.append(case_data)
        logger.info(f"➕ Added case {case_data.get('case_id')} to mock sheets")
        return True
    
    def update_case_status(self, case_id: str, status: str, notes: str = "") -> bool:
        for case in self.cases:
            if case.get('case_id') == case_id:
                case['status'] = status
                case['updated_at'] = str(int(time.time()))
                if notes:
                    case['notes'] = notes
                logger.info(f"📝 Updated case {case_id} status to {status}")
                return True
        return False
    
    def add_sample_data(self):
        """Add sample data for testing"""
        sample_customer = {
            'dentist_name': 'Dr. Sarah Johnson',
            'phone': '+1234567890',
            'email': 'sarah.johnson@clinic.com',
            'clinic_name': 'Johnson Dental Clinic',
            'subscription_type': 'Premium'
        }
        self.customers.append(sample_customer)
        
        sample_case = {
            'case_id': 'case-demo-001',
            'user_id': '+1234567890',
            'patient_name': 'John Doe',
            'dentist_name': 'Dr. Sarah Johnson',
            'status': 'ApprovedForProduction',
            'created_at': str(int(time.time())),
            'updated_at': str(int(time.time())),
            'delivery_status': 'Not Started',
            'notes': 'Demo case for testing',
            'priority': 'Normal'
        }
        self.cases.append(sample_case)
        logger.info("✅ Sample data added to mock sheets")

class MockWhatsAppAPI:
    """Simulates WhatsApp Business API"""
    
    def __init__(self):
        self.sent_messages = []
        logger.info("📱 Mock WhatsApp API initialized")
    
    def send_message(self, recipient_id: str, content: str) -> bool:
        message = {
            "recipient_id": recipient_id,
            "content": content,
            "timestamp": int(time.time()),
            "status": "sent"
        }
        self.sent_messages.append(message)
        logger.info(f"📤 Sent message to {recipient_id}: {content[:50]}...")
        return True
    
    def get_sent_messages(self, recipient_id: Optional[str] = None) -> List[Dict]:
        if recipient_id:
            return [msg for msg in self.sent_messages if msg["recipient_id"] == recipient_id]
        return self.sent_messages

class WorkflowSimulator:
    """Main simulator class that orchestrates all components"""
    
    def __init__(self):
        # Initialize LLM with real OpenAI API
        self.llm = ChatOpenAI(
            model_name="gpt-3.5-turbo",
            openai_api_key=os.getenv("OPENAI_API_KEY"),
            temperature=0.1
        )
        
        # Initialize mock services
        self.firebase_db = MockFirebaseDatabase()
        self.sheets_manager = MockGoogleSheetsManager()
        self.whatsapp_api = MockWhatsAppAPI()
        
        # In-memory storage for simulation
        self.cases_db = {}
        self.user_sessions = {}
        
        # Add sample data
        self.sheets_manager.add_sample_data()
        self._create_sample_users()
        
        logger.info("🚀 Workflow Simulator initialized successfully")
    
    def _create_sample_users(self):
        """Create sample users for testing"""
        sample_users = [
            SimulatedUser(
                user_id="+1234567890",
                name="Dr. Sarah Johnson",
                phone="+1234567890",
                clinic="Johnson Dental Clinic"
            ),
            SimulatedUser(
                user_id="+9876543210",
                name="Dr. Michael Smith", 
                phone="+9876543210",
                clinic="Smith Family Dentistry"
            )
        ]
        
        for user in sample_users:
            self.user_sessions[user.user_id] = {
                "user_id": user.user_id,
                "current_stage": user.stage,
                "active_case": user.active_case,
                "last_message_time": int(time.time())
            }
        
        logger.info(f"👥 Created {len(sample_users)} sample users")
    
    def create_test_case(self, user_id: str, patient_name: str) -> str:
        """Create a test case for simulation"""
        case_id = f"case-sim-{int(time.time())}"
        
        case_data = {
            "id": case_id,
            "user_id": user_id,
            "patient_name": patient_name,
            "dentist_name": self._get_dentist_name(user_id),
            "status": "ApprovedForProduction",
            "created_at": int(time.time()),
            "updated_at": int(time.time()),
            "delivery_status": "Not Started"
        }
        
        self.cases_db[case_id] = case_data
        self.sheets_manager.add_case(case_data)
        
        logger.info(f"📋 Created test case: {case_id} for patient {patient_name}")
        return case_id
    
    def _get_dentist_name(self, user_id: str) -> str:
        """Get dentist name from user ID"""
        if user_id == "+1234567890":
            return "Dr. Sarah Johnson"
        elif user_id == "+9876543210":
            return "Dr. Michael Smith"
        return "Dr. Unknown"
    
    def simulate_production_start(self, case_id: str) -> Dict:
        """Simulate starting a production workflow"""
        logger.info(f"🏭 Simulating production start for case: {case_id}")
        
        if case_id not in self.cases_db:
            return {"error": "Case not found", "status": "Error"}
        
        current_case_data = self.cases_db[case_id]
        user_id = current_case_data["user_id"]
        current_user_session = self.user_sessions.get(user_id, {})
        
        # Call the actual workflow function
        result = dental_aligner_workflow(
            action_type="start_production",
            llm_instance=self.llm,
            case_id=case_id,
            current_case_data=current_case_data,
            current_user_session=current_user_session
        )
        
        # Update local storage
        if result["updated_case_data"]:
            self.cases_db[case_id] = result["updated_case_data"]
            self.sheets_manager.update_case_status(
                case_id, 
                result["updated_case_data"]["status"]
            )
        
        if result["updated_user_session"]:
            self.user_sessions[user_id] = result["updated_user_session"]
        
        # Send messages via mock WhatsApp
        for msg in result.get("messages_to_send", []):
            self.whatsapp_api.send_message(msg["recipient_id"], msg["content"])
        
        return result
    
    def simulate_message_processing(self, user_id: str, message: str) -> Dict:
        """Simulate processing an incoming message"""
        logger.info(f"📨 Simulating message from {user_id}: {message}")
        
        # Get current user session
        current_user_session = self.user_sessions.get(user_id, {
            "user_id": user_id,
            "current_stage": "general",
            "active_case": None,
            "last_message_time": int(time.time())
        })
        
        # Get active case data if exists
        active_case_id = current_user_session.get("active_case")
        current_case_data = None
        if active_case_id and active_case_id in self.cases_db:
            current_case_data = self.cases_db[active_case_id]
        
        # Update last message time
        current_user_session["last_message_time"] = int(time.time())
        
        # Call the actual workflow function
        result = dental_aligner_workflow(
            action_type="process_message",
            llm_instance=self.llm,
            user_id=user_id,
            message_body=message,
            current_case_data=current_case_data,
            current_user_session=current_user_session
        )
        
        # Update local storage
        if result["updated_case_data"] and active_case_id:
            self.cases_db[active_case_id] = result["updated_case_data"]
            self.sheets_manager.update_case_status(
                active_case_id,
                result["updated_case_data"]["status"]
            )
        
        if result["updated_user_session"]:
            self.user_sessions[user_id] = result["updated_user_session"]
        
        # Send messages via mock WhatsApp
        for msg in result.get("messages_to_send", []):
            self.whatsapp_api.send_message(msg["recipient_id"], msg["content"])
        
        return result
    
    def run_interactive_session(self):
        """Run an interactive testing session"""
        print("\n🦷 Dental Aligner Production System - Interactive Simulator")
        print("=" * 60)
        print("Available commands:")
        print("1. 'create case <user_id> <patient_name>' - Create a new case")
        print("2. 'start production <case_id>' - Start production workflow")
        print("3. 'send message <user_id> <message>' - Send message as user")
        print("4. 'show cases' - Display all cases")
        print("5. 'show users' - Display all user sessions")
        print("6. 'show messages <user_id>' - Show messages for user")
        print("7. 'test scenario <scenario_name>' - Run predefined test scenario")
        print("8. 'help' - Show this help")
        print("9. 'quit' - Exit simulator")
        print()
        
        while True:
            try:
                command = input("\n🎮 Enter command: ").strip()
                
                if command.lower() in ['quit', 'exit', 'q']:
                    print("👋 Goodbye!")
                    break
                
                elif command.lower() == 'help':
                    self._show_help()
                
                elif command.startswith('create case'):
                    self._handle_create_case(command)
                
                elif command.startswith('start production'):
                    self._handle_start_production(command)
                
                elif command.startswith('send message'):
                    self._handle_send_message(command)
                
                elif command.lower() == 'show cases':
                    self._show_cases()
                
                elif command.lower() == 'show users':
                    self._show_users()
                
                elif command.startswith('show messages'):
                    self._handle_show_messages(command)
                
                elif command.startswith('test scenario'):
                    self._handle_test_scenario(command)
                
                else:
                    print("❌ Unknown command. Type 'help' for available commands.")
                    
            except KeyboardInterrupt:
                print("\n👋 Goodbye!")
                break
            except Exception as e:
                print(f"❌ Error: {e}")
                logger.error(f"Command error: {e}", exc_info=True)
    
    def _show_help(self):
        """Show detailed help information"""
        print("\n📚 Detailed Command Help:")
        print("-" * 40)
        print("create case +1234567890 'John Doe'    - Create case for user")
        print("start production case-sim-123          - Start production workflow")
        print("send message +1234567890 'Hello'       - Send message as user")
        print("show cases                             - List all cases")
        print("show users                             - List all user sessions")
        print("show messages +1234567890              - Show user's messages")
        print("test scenario fit_confirmation         - Run fit confirmation test")
        print("test scenario dispatch_choice          - Run dispatch choice test")
        print("test scenario full_workflow           - Run complete workflow")
    
    def _handle_create_case(self, command: str):
        """Handle create case command"""
        parts = command.split()
        if len(parts) >= 4:
            user_id = parts[2]
            patient_name = ' '.join(parts[3:]).strip("'\"")
            case_id = self.create_test_case(user_id, patient_name)
            print(f"✅ Created case {case_id} for patient {patient_name}")
        else:
            print("❌ Usage: create case <user_id> <patient_name>")
    
    def _handle_start_production(self, command: str):
        """Handle start production command"""
        parts = command.split()
        if len(parts) >= 3:
            case_id = parts[2]
            result = self.simulate_production_start(case_id)
            print(f"✅ Production started. Status: {result['status']}")
            if result.get('error'):
                print(f"❌ Error: {result['error']}")
        else:
            print("❌ Usage: start production <case_id>")
    
    def _handle_send_message(self, command: str):
        """Handle send message command"""
        parts = command.split(' ', 3)
        if len(parts) >= 4:
            user_id = parts[2]
            message = parts[3].strip("'\"")
            result = self.simulate_message_processing(user_id, message)
            print(f"✅ Message processed. Status: {result['status']}")
            if result.get('error'):
                print(f"❌ Error: {result['error']}")
        else:
            print("❌ Usage: send message <user_id> <message>")
    
    def _show_cases(self):
        """Show all cases"""
        print("\n📋 All Cases:")
        print("-" * 40)
        for case_id, case_data in self.cases_db.items():
            print(f"ID: {case_id}")
            print(f"  Patient: {case_data.get('patient_name')}")
            print(f"  Dentist: {case_data.get('dentist_name')}")
            print(f"  Status: {case_data.get('status')}")
            print(f"  Delivery: {case_data.get('delivery_status')}")
            print()
    
    def _show_users(self):
        """Show all user sessions"""
        print("\n👥 All User Sessions:")
        print("-" * 40)
        for user_id, session in self.user_sessions.items():
            print(f"User: {user_id}")
            print(f"  Stage: {session.get('current_stage')}")
            print(f"  Active Case: {session.get('active_case')}")
            print(f"  Last Activity: {datetime.fromtimestamp(session.get('last_message_time', 0))}")
            print()
    
    def _handle_show_messages(self, command: str):
        """Handle show messages command"""
        parts = command.split()
        if len(parts) >= 3:
            user_id = parts[2]
            messages = self.whatsapp_api.get_sent_messages(user_id)
            print(f"\n📱 Messages for {user_id}:")
            print("-" * 40)
            for msg in messages[-5:]:  # Show last 5 messages
                timestamp = datetime.fromtimestamp(msg['timestamp'])
                print(f"[{timestamp.strftime('%H:%M:%S')}] {msg['content']}")
        else:
            print("❌ Usage: show messages <user_id>")
    
    def _handle_test_scenario(self, command: str):
        """Handle test scenario command"""
        parts = command.split()
        if len(parts) >= 3:
            scenario = parts[2]
            self._run_test_scenario(scenario)
        else:
            print("❌ Usage: test scenario <scenario_name>")
            print("Available scenarios: fit_confirmation, dispatch_choice, full_workflow")
    
    def _run_test_scenario(self, scenario: str):
        """Run predefined test scenarios"""
        user_id = "+1234567890"
        
        if scenario == "fit_confirmation":
            print("🧪 Running Fit Confirmation Test Scenario")
            case_id = self.create_test_case(user_id, "Test Patient")
            
            # Start production
            self.simulate_production_start(case_id)
            
            # Advance to awaiting delivery
            self.cases_db[case_id]["status"] = "AwaitingDelivery"
            self.cases_db[case_id]["delivery_status"] = "delivered"
            self.user_sessions[user_id]["current_stage"] = "awaiting_delivery"
            self.user_sessions[user_id]["active_case"] = case_id
            
            # Test delivery inquiry
            self.simulate_message_processing(user_id, "Has the aligner been delivered?")
            
            # Test fit confirmation
            self.simulate_message_processing(user_id, "Yes, it fits perfectly!")
            
        elif scenario == "dispatch_choice":
            print("🧪 Running Dispatch Choice Test Scenario")
            case_id = self.create_test_case(user_id, "Test Patient 2")
            
            # Set up for dispatch choice
            self.cases_db[case_id]["status"] = "AwaitingFitConfirmation"
            self.user_sessions[user_id]["current_stage"] = "awaiting_dispatch_choice"
            self.user_sessions[user_id]["active_case"] = case_id
            
            # Test dispatch choice
            self.simulate_message_processing(user_id, "I prefer phase-wise delivery")
            
        elif scenario == "full_workflow":
            print("🧪 Running Full Workflow Test Scenario")
            case_id = self.create_test_case(user_id, "Complete Test Patient")
            
            # Run complete workflow
            self.simulate_production_start(case_id)
            
            # Advance through stages
            time.sleep(1)
            self.simulate_production_start(case_id)
            
            # Simulate delivery and fit confirmation
            self.cases_db[case_id]["delivery_status"] = "delivered"
            self.user_sessions[user_id]["current_stage"] = "awaiting_delivery"
            self.user_sessions[user_id]["active_case"] = case_id
            
            self.simulate_message_processing(user_id, "Delivery status?")
            self.simulate_message_processing(user_id, "Yes, fits well")
            self.simulate_message_processing(user_id, "Full case please")
            
        else:
            print(f"❌ Unknown scenario: {scenario}")

def main():
    """Main function to run the simulator"""
    print("🦷 Dental Aligner Production System - Workflow Simulator")
    print("=" * 60)
    
    # Check if OpenAI API key is available
    if not os.getenv("OPENAI_API_KEY"):
        print("❌ OPENAI_API_KEY not found in environment variables")
        print("Please set it in your .env file to use real LLM calls")
        return
    
    # Initialize simulator
    try:
        simulator = WorkflowSimulator()
        print("✅ Simulator initialized successfully")
        
        # Run interactive session
        simulator.run_interactive_session()
        
    except Exception as e:
        logger.error(f"Failed to initialize simulator: {e}", exc_info=True)
        print(f"❌ Failed to initialize simulator: {e}")

if __name__ == "__main__":
    main()
