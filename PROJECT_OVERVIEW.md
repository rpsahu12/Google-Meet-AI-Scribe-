# Google Meet AI Scribe - Project Overview

## Project Description

**Google Meet AI Scribe** is an automated meeting assistant that joins Google Meet calls, transcribes conversations in real-time, and generates AI-powered summaries with actionable items. The system eliminates the need for manual note-taking and ensures no important detail is missed during meetings.

---

## Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   React Frontend│────▶│   FastAPI Backend│────▶│  Playwright Bot │
│   (Port 5173)   │◀────│   (Port 8000)    │◀────│  (Automation)   │
└─────────────────┘     └──────────────────┘     └─────────────────┘
         │                       │                        │
         ▼                       ▼                        ▼
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  Live UI Display│     │  AI Processing   │     │  Google Meet    │
│  Status Tracker │     │  Summary Gen     │     │  Meeting Room   │
└─────────────────┘     └──────────────────┘     └─────────────────┘
```

---

## Tech Stack

### Frontend
| Technology | Purpose |
|------------|---------|
| React 18 | UI framework |
| Vite | Build tool & dev server |
| Lucide React | Icon library |
| CSS3 | Styling with CSS variables |

### Backend
| Technology | Purpose |
|------------|---------|
| FastAPI | REST API framework |
| Python 3.13+ | Runtime |
| Pydantic | Data validation |
| Uvicorn | ASGI server |

### Automation (Phase 2)
| Technology | Purpose |
|------------|---------|
| Playwright | Browser automation |
| WebSockets | Real-time transcription streaming |

---

## Project Structure

```
Chi_SquareX/
├── app.py                 # FastAPI backend server
├── requirements.txt       # Python dependencies
├── frontend/              # React application
│   ├── src/
│   │   ├── App.jsx       # Main component with UI logic
│   │   ├── App.css       # Component styles
│   │   ├── index.css     # Global styles
│   │   └── main.jsx      # React entry point
│   ├── package.json
│   └── vite.config.js
└── PROJECT_OVERVIEW.md   # This documentation
```

---

## How It Works

### User Flow

1. **User Input**: User pastes a Google Meet URL into the frontend
2. **Bot Deployment**: Frontend sends POST request to `/deploy-bot` endpoint
3. **Bot Joins**: Backend triggers Playwright script to join the meeting
4. **Live Transcription**: Audio is captured and converted to text in real-time
5. **AI Processing**: Transcription is sent to LLM for summarization
6. **Results Display**: Summary with action items shown to user

### API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/deploy-bot` | POST | Deploy bot to a Google Meet URL |
| `/health` | GET | Health check for the service |

### Request/Response Format

**Request:**
```json
{
  "url": "https://meet.google.com/abc-defg-hij"
}
```

**Response:**
```json
{
  "executive": "Meeting summary text...",
  "actionItems": [
    {
      "assignee": "Alice",
      "task": "Complete the report by Friday",
      "priority": "high"
    }
  ],
  "duration": "45 minutes",
  "participants": ["Alice", "Bob", "Carol"]
}
```

---

## Key Features Implemented

### Frontend Features
- **Real-time Status Tracking**: Visual indicators for joining, listening, processing states
- **Live Transcription Display**: Shows transcribed text with timestamps
- **Progress Bar**: Visual feedback during bot operations
- **Meeting History**: Stores past meetings in localStorage
- **Copy & Export**: One-click copy or download summaries
- **Error Handling**: User-friendly error messages
- **Responsive Design**: Works on desktop, tablet, and mobile

### Backend Features
- **CORS Configuration**: Secure cross-origin requests
- **Input Validation**: Pydantic models for request validation
- **Async Processing**: Non-blocking API endpoints
- **Health Check**: Service monitoring endpoint

---

## Installation & Setup

### Prerequisites
- Node.js 18+ and npm
- Python 3.13+
- Virtual environment (recommended)

### Frontend Setup
```bash
cd frontend
npm install
npm run dev
```
Frontend runs on: `http://localhost:5173`

### Backend Setup
```bash
python -m venv .venv
.venv\Scripts\activate  # Windows
pip install -r requirements.txt
python -m uvicorn app:app --reload
```
Backend runs on: `http://localhost:8000`

---

## Code Explanation

### Frontend - App.jsx

**State Management:**
```javascript
const [meetLink, setMeetLink] = useState('');      // User input
const [status, setStatus] = useState('idle');      // Bot status
const [summary, setSummary] = useState(null);      // AI summary
const [transcription, setTranscription] = useState([]); // Live transcript
const [error, setError] = useState(null);          // Error state
const [elapsedTime, setElapsedTime] = useState(0); // Timer
```

**API Integration:**
```javascript
const response = await fetch('http://localhost:8000/deploy-bot', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ url: meetLink })
});
```

### Backend - app.py

**FastAPI App Setup:**
```python
app = FastAPI(title="Google Meet AI Scribe API")

@app.post("/deploy-bot", response_model=SummaryResponse)
async def deploy_bot(request: MeetRequest):
    # Validate URL
    # Deploy bot (Playwright)
    # Process transcription
    # Generate summary
    return summary
```

**CORS Configuration:**
```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

---

## Interview Q&A

### Q1: What problem does this project solve?
**A:** Manual note-taking during meetings is time-consuming and error-prone. This project automates transcription and summarization, allowing participants to focus on discussion while ensuring accurate records and actionable follow-ups.

### Q2: How does the bot join Google Meet?
**A:** Using Playwright for browser automation. The bot:
1. Navigates to the Meet URL
2. Handles permission dialogs (camera/mic)
3. Joins with camera/mic muted
4. Captures audio for transcription

### Q3: How is transcription handled?
**A:** Two approaches:
- **Google Cloud Speech-to-Text**: Stream audio to GCP API
- **Local Whisper AI**: Run Whisper model locally for privacy

### Q4: How are summaries generated?
**A:** Transcription text is sent to an LLM (Claude/GPT) with prompts like:
```
"Summarize this meeting transcript. Extract:
1. Executive summary (2-3 sentences)
2. Action items with assignees
3. Key decisions made"
```

### Q5: What challenges did you face?
**A:**
- **Real-time audio capture**: Browser security restrictions require careful handling
- **Speaker identification**: Distinguishing between multiple speakers
- **Meeting controls**: Handling reconnection if bot is kicked out
- **Rate limits**: Managing API calls to transcription/LLM services

### Q6: How would you scale this?
**A:**
- **Queue system**: Celery + Redis for handling multiple bots
- **WebSocket streaming**: Real-time transcription updates
- **Database**: PostgreSQL for meeting history
- **Cloud deployment**: Docker containers on AWS/GCP

### Q7: Security considerations?
**A:**
- **Authentication**: Only authorized users can deploy bots
- **Data encryption**: Encrypt stored transcripts
- **Access control**: Meeting participants should be notified of bot presence
- **Compliance**: GDPR considerations for recorded conversations

---

## Future Enhancements

1. **Speaker Diarization**: Identify who said what
2. **Multi-language Support**: Transcribe in multiple languages
3. **Calendar Integration**: Auto-join scheduled meetings
4. **Slack/Teams Integration**: Post summaries to channels
5. **Custom Templates**: Industry-specific summary formats
6. **Analytics Dashboard**: Meeting insights and trends

---

## Lessons Learned

1. **Frontend-Backend Communication**: Proper error handling and loading states improve UX significantly
2. **Async Operations**: Python async/await is crucial for non-blocking API responses
3. **State Management**: Complex UI states require careful planning (idle, joining, listening, processing, complete)
4. **CORS Configuration**: Often overlooked but critical for frontend-backend communication
5. **User Feedback**: Progress indicators and status updates reduce user anxiety during long operations

---

## Contact & Repository

- **Repository**: https://github.com/rpsahu12/Google-Meet-AI-Scribe-
- **Author**: [Your Name]

---

*This document serves as a comprehensive overview for understanding the project architecture, implementation details, and for preparing for technical interviews.*
