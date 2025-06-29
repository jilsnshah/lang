# 🦷 Dental Aligner Production System

An end-to-end automated system for dental aligner providers to manage dentist communications, case tracking, and production workflow through WhatsApp Business API integration with Google Calendar scheduling and Firebase database.

## 🌟 Core System Architecture

### Main Components
- **`server.py`** - Advanced WhatsApp Business server with Firebase integration, Google Calendar scheduling, and LLM-powered conversation handling
- **`what.py`** - Simplified WhatsApp webhook handler focused on aligner production workflow
- **`prod_workflow.py`** - Core workflow logic for aligner production stages
- **`google_sheets_manager.py`** - Google Sheets integration for customer management
- **`mainlogic.py`** - Google Calendar and Drive integration utilities

## 📋 Available Tools & Functionalities

### 🤖 Core Server Features (`server.py`)

#### 1. **Dentist Registration & Authentication**
- **Tool**: `DentistRegistrar`
- **Usage**: Automatically registers new dentists through conversational flow
- **Format**: Name, Phone Number, Clinic, License Number
- **Features**:
  - Validates dentist credentials
  - Stores in Firebase database
  - Auto-populates user sessions
  - Handles phone number formatting

#### 2. **WhatsApp Business Integration**
- **Endpoint**: `POST /webhook` (WhatsApp Cloud API)
- **Features**:
  - Message verification and routing
  - Media handling (images, documents, location)
  - Message status tracking (delivered, read)
  - Template message support
  - 24-hour messaging window compliance

#### 3. **Multi-Modal Message Processing**
- **Supported Types**:
  - Text messages
  - Image uploads (with media forwarding)
  - Location sharing
  - Document attachments
- **Media Processing**:
  - Automatic media URL retrieval
  - Content type detection
  - Media forwarding to designated numbers

#### 4. **Conversation Memory Management**
- **Auth Memory**: Tracks authentication conversations
- **Schedule Memory**: Maintains scheduling context
- **Persistent Storage**: Firebase-backed session management
- **Memory Serialization**: Automatic save/restore of conversation states

#### 5. **Google Calendar Integration**
- **Features**:
  - OAuth2 authentication
  - Appointment scheduling
  - Calendar event management
  - Multi-calendar support
- **Tools Available**:
  - Calendar service initialization
  - Event creation and management
  - Availability checking

#### 6. **Firebase Database Operations**
- **User Session Management**: Real-time session updates
- **Data Persistence**: Automatic state synchronization
- **Multi-user Support**: Concurrent session handling
- **Session Recovery**: Automatic memory restoration

### 🔄 Production Workflow Features (`what.py` + `prod_workflow.py`)

#### 1. **Case Management API**
```http
POST /create-case          # Create new aligner case
POST /start-production     # Trigger production workflow
POST /update-case-status   # Update case status
GET /admin/cases          # View all cases
GET /admin/users          # View user sessions
```

#### 2. **Google Sheets Integration**
```http
POST /sync-customers      # Sync customer data from sheets
```
- **Customer Management**: Real-time sync with Google Sheets
- **Case Tracking**: Automated status updates
- **Production Scheduling**: Integrated production planning

#### 3. **Automated Production Workflow**
- **Stages**:
  1. `ApprovedForProduction` → Planning notification
  2. `CasePlanningComplete` → Training aligner dispatch
  3. `AwaitingDelivery` → Delivery tracking
  4. `AwaitingFitConfirmation` → LLM-powered fit assessment
  5. `FitConfirmed_PhaseWise/FullCase` → Final production

#### 4. **LLM-Powered Response Classification**
- **Fit Confirmation**: Yes/No/Unknown classification
- **Dispatch Choice**: Phase-Wise vs Full Case detection
- **Intent Recognition**: Natural language understanding
- **Context Awareness**: Multi-turn conversation handling

### 📊 Google Sheets Management (`google_sheets_manager.py`)

#### Available Operations
- **`get_customers()`** - Retrieve all customer data
- **`get_cases()`** - Fetch case information
- **`add_case(case_data)`** - Create new case entries
- **`update_case_status(case_id, status)`** - Update case progress
- **`sync_cases_to_sheet(cases)`** - Bulk case synchronization
- **`get_production_schedule()`** - Production planning data
- **`create_sheets_if_not_exist()`** - Auto-setup sheet structure

#### Sheet Structure
- **Customers**: dentist_name, phone, email, clinic_name, address, subscription_type
- **Cases**: case_id, user_id, patient_name, status, delivery_status, notes
- **Production**: case_id, production_stage, assigned_to, estimated_completion

## 🎯 Usage Scenarios

### Scenario 1: New Dentist Registration
```
1. Dentist sends: "Hi, I want to register"
2. System: Guides through registration process
3. Collects: Name, Phone, Clinic, License
4. Stores in Firebase and updates session
5. Transitions to main conversation flow
```

### Scenario 2: Case Management Workflow
```
1. POST /create-case → Creates new aligner case
2. POST /start-production → Initiates planning phase
3. System sends WhatsApp notification to dentist
4. Tracks delivery, fit confirmation, and dispatch choice
5. Updates Google Sheets automatically
```

### Scenario 3: Multi-Modal Interaction
```
1. Dentist sends images of dental impressions
2. System processes and forwards to clinical team
3. Maintains conversation context
4. Provides real-time updates on case progress
```

## �️ System Configuration

### Environment Variables Required
```env
# WhatsApp Business API
VERIFY_TOKEN=your_webhook_verify_token
ACCESS_TOKEN=your_whatsapp_access_token
PHONE_NUMBER_ID=your_phone_number_id

# Firebase Configuration
FIREBASE_PROJECT_ID=your_firebase_project
FIREBASE_PRIVATE_KEY=your_firebase_private_key
FIREBASE_CLIENT_EMAIL=your_firebase_client_email

# Google APIs
GOOGLE_SHEETS_ID=your_sheets_id
GOOGLE_CREDENTIALS_FILE=credentials.json

# LLM Configuration
OPENAI_API_KEY=your_openai_key
```

### Firebase Database Structure
```json
{
  "user_sessions": {
    "whatsapp:+1234567890": {
      "name": "Dr. Smith",
      "clinic": "Smith Dental",
      "license": "DL12345",
      "current_stage": "auth",
      "app_state": "active",
      "auth_memory": [...],
      "sched_memory": [...],
      "image_count": 0,
      "expected_images": 0
    }
  }
}
```

## � Deployment Options

### Firebase Deployment
- **Server**: Deploy `server.py` to Firebase Functions
- **Database**: Use Firebase Realtime Database
- **Storage**: Firebase Storage for media files
- **Webhook**: Configure WhatsApp webhook URL

### Local Development
- **Testing**: Use local simulator (see `workflow_simulator.py`)
- **Debugging**: Built-in console logging
- **Media**: ngrok for webhook tunneling

## 🔧 Advanced Features

### Message Routing Logic
- **Stage-based routing**: Different handlers per conversation stage
- **Context preservation**: Maintains conversation state across sessions
- **Error handling**: Graceful degradation and recovery
- **Concurrent users**: Multi-user session management

### Media Processing Pipeline
- **Automatic forwarding**: Routes media to designated numbers
- **Content type detection**: Handles various file formats
- **URL management**: Secure media URL generation
- **Storage integration**: Optional cloud storage backup

### Production Workflow Intelligence
- **Smart scheduling**: Automated production timeline management
- **Status synchronization**: Real-time updates across all systems
- **Escalation handling**: Automatic clinical team notifications
- **Quality assurance**: Built-in checkpoints and validations

## 📈 Monitoring & Analytics

### Built-in Logging
- **Conversation tracking**: Full message history
- **Error monitoring**: Detailed error logs with stack traces
- **Performance metrics**: Response time tracking
- **User analytics**: Session duration and engagement metrics

### Integration Points
- **Google Sheets**: Real-time dashboard updates
- **Firebase**: Live session monitoring
- **WhatsApp**: Message delivery confirmation
- **External APIs**: Production system integration

## 🔒 Security Features

- **Token validation**: WhatsApp webhook verification
- **Session encryption**: Secure conversation storage
- **Access control**: Role-based permissions
- **Data privacy**: HIPAA-compliant data handling
- **Audit trails**: Complete interaction logging

---

**This system provides a complete end-to-end solution for dental aligner providers, from initial dentist registration through final product delivery, with intelligent automation and comprehensive tracking capabilities.**
