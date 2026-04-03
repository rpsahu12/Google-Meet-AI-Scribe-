# 🎙️ Google Meet AI Scribe

> An AI-powered bot that joins your Google Meet, records the audio, and automatically generates a structured meeting summary using Google Gemini.

![Tech Stack](https://img.shields.io/badge/FastAPI-009688?style=flat&logo=fastapi&logoColor=white)
![Firebase](https://img.shields.io/badge/Firebase-FFCA28?style=flat&logo=firebase&logoColor=black)
![AWS](https://img.shields.io/badge/AWS-232F3E?style=flat&logo=amazon-aws&logoColor=white)
![Selenium](https://img.shields.io/badge/Selenium-43B02A?style=flat&logo=selenium&logoColor=white)
![Python](https://img.shields.io/badge/Python-3.12-3776AB?style=flat&logo=python&logoColor=white)

---

## ✨ Features

- 🤖 **Autonomous bot** — joins Google Meet without any manual intervention
- 🎙️ **Audio recording** — captures full meeting audio via FFmpeg + PulseAudio
- 🧠 **AI-powered summary** — generates structured summaries using Google Gemini
- 📋 **Action items** — extracts tasks with assignees and priorities
- 👤 **User authentication** — secure login via Firebase Auth (Google OAuth)
- 📅 **Meeting history** — view all past summaries per user
- ☁️ **Cloud storage** — audio and summaries stored in AWS S3
- 🔒 **HTTPS** — production-ready with Nginx + Let's Encrypt SSL

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    User's Browser                       │
│            React Frontend (Firebase Hosting)            │
│         https://ai-scribe-21776.web.app                 │
└─────────────────┬───────────────────────────────────────┘
                  │ HTTPS (Firebase Auth Token)
                  ▼
┌─────────────────────────────────────────────────────────┐
│              AWS EC2 (Ubuntu 24, eu-north-1)            │
│                                                         │
│  Nginx (443) ──► FastAPI/Uvicorn (8000)                │
│                        │                               │
│              ┌─────────▼──────────┐                   │
│              │   Bot (Selenium)   │                   │
│              │  Chrome + Xvfb:99  │                   │
│              │  FFmpeg + PulseAudio│                  │
│              └─────────┬──────────┘                   │
│                        │                               │
│              ┌─────────▼──────────┐                   │
│              │   Google Gemini AI  │                   │
│              │  (Meeting Summary)  │                   │
│              └─────────┬──────────┘                   │
│                        │                               │
└────────────────────────┼────────────────────────────────┘
                         │
              ┌──────────▼──────────┐
              │      AWS S3         │
              │  Audio + Summary    │
              └─────────────────────┘
```

---

## 🛠️ Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | React, Firebase Hosting |
| Authentication | Firebase Auth (Google OAuth) |
| Backend API | FastAPI, Uvicorn |
| Bot Engine | Selenium, undetected-chromedriver |
| Audio Capture | FFmpeg, PulseAudio |
| AI Summary | Google Gemini (google-generativeai) |
| Storage | AWS S3 |
| Server | AWS EC2 (Ubuntu 24) |
| Reverse Proxy | Nginx + Let's Encrypt |
| Virtual Display | Xvfb |
| Process Manager | systemd |

---

## 📁 Project Structure

```
Google-Meet-AI-Scribe/
├── app.py                  # FastAPI backend — API endpoints & auth
├── meet_boot.py            # Bot engine — Selenium + Chrome automation
├── ai_summary.py           # Google Gemini integration
├── cloud_storage.py        # AWS S3 upload logic
├── requirements.txt        # Python dependencies
├── .env                    # Environment variables (not committed)
├── firebase-credentials.json  # Firebase Admin SDK (not committed)
└── frontend/               # React frontend source
```

---

## ⚙️ How the Bot Works

The bot (`meet_boot.py`) automates a real Chrome browser on the server:

1. **Launches Chrome** on a virtual display (Xvfb :99) with PulseAudio audio
2. **Navigates** to the Google Meet URL
3. **Enters name** ("AI Scribe Bot") in the pre-join lobby
4. **Clicks "Ask to join"** and waits to be admitted by the host
5. **Detects admission** using 6 independent DOM signals:
   - Leave/End call button presence
   - Participant tile DOM nodes
   - Mute/unmute button presence
   - Meeting controls toolbar
   - Page title change
   - Live JavaScript keyword scan across all buttons
6. **Records audio** via FFmpeg from the PulseAudio virtual sink
7. **Monitors for meeting end** using URL changes, page text, and button disappearance
8. **Stops recording** and passes the WAV file to Gemini for summarization

---

## 🚀 Self-Hosting Guide

### Prerequisites

- Ubuntu 22.04+ server (AWS EC2 t3.micro or larger recommended)
- Python 3.12+
- Google Chrome installed
- AWS account (for S3)
- Firebase project
- Google Cloud API key (for Gemini)

### 1. Clone the Repository

```bash
git clone https://github.com/YOUR_USERNAME/Google-Meet-AI-Scribe.git
cd Google-Meet-AI-Scribe
```

### 2. Install System Dependencies

```bash
# Install Chrome
wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
sudo apt install ./google-chrome-stable_current_amd64.deb -y

# Install audio/display dependencies
sudo apt-get install -y xvfb pulseaudio ffmpeg nginx

# Install Certbot for SSL
sudo apt-get install -y certbot python3-certbot-nginx
```

### 3. Set Up Virtual Environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 4. Configure Environment Variables

Create a `.env` file:

```env
GEMINI_API_KEY=your_google_gemini_api_key
AWS_ACCESS_KEY_ID=your_aws_access_key
AWS_SECRET_ACCESS_KEY=your_aws_secret_key
AWS_REGION=eu-north-1
S3_BUCKET_NAME=your_s3_bucket_name
DISPLAY=:99
```

### 5. Add Firebase Credentials

Place your Firebase Admin SDK JSON file as `firebase-credentials.json` in the project root.

### 6. Set Up Virtual Display & Audio

```bash
# Start Xvfb
Xvfb :99 -screen 0 1920x1080x24 &

# Set up PulseAudio virtual sink
pulseaudio --start
pactl load-module module-null-sink sink_name=virtual_speaker
pactl set-default-source virtual_speaker.monitor
```

### 7. Set Up systemd Services (24/7 operation)

```bash
# Xvfb service
sudo tee /etc/systemd/system/xvfb.service > /dev/null <<EOF
[Unit]
Description=Xvfb Virtual Display
After=network.target

[Service]
ExecStart=/usr/bin/Xvfb :99 -screen 0 1920x1080x24
Restart=always
User=ubuntu

[Install]
WantedBy=multi-user.target
EOF

# PulseAudio service
sudo tee /etc/systemd/system/pulseaudio-bot.service > /dev/null <<EOF
[Unit]
Description=PulseAudio for Bot
After=xvfb.service

[Service]
ExecStart=/usr/bin/pulseaudio --daemonize=no --log-target=syslog
Restart=always
User=ubuntu
Environment=DISPLAY=:99
Environment=XDG_RUNTIME_DIR=/run/user/1000

[Install]
WantedBy=multi-user.target
EOF

# FastAPI service
sudo tee /etc/systemd/system/aiscribe.service > /dev/null <<EOF
[Unit]
Description=AI Scribe FastAPI
After=xvfb.service pulseaudio-bot.service network.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/Google-Meet-AI-Scribe
Environment=DISPLAY=:99
Environment=XDG_RUNTIME_DIR=/run/user/1000
ExecStart=/home/ubuntu/Google-Meet-AI-Scribe/.venv/bin/uvicorn app:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# Enable and start all services
sudo systemctl daemon-reload
sudo systemctl enable xvfb pulseaudio-bot aiscribe nginx
sudo systemctl start xvfb pulseaudio-bot aiscribe
```

### 8. Configure Nginx + HTTPS

```bash
# Configure Nginx
sudo tee /etc/nginx/sites-available/aiscribe <<EOF
server {
    listen 80;
    server_name your-domain.com;
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_read_timeout 300s;
    }
}
EOF

sudo ln -s /etc/nginx/sites-available/aiscribe /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl restart nginx

# Get SSL certificate
sudo certbot --nginx -d your-domain.com
```

### 9. Add Swap Memory (important for t3.micro)

```bash
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

---

## 🔑 Environment Variables Reference

| Variable | Description |
|----------|-------------|
| `GEMINI_API_KEY` | Google Gemini API key for AI summarization |
| `AWS_ACCESS_KEY_ID` | AWS IAM access key |
| `AWS_SECRET_ACCESS_KEY` | AWS IAM secret key |
| `AWS_REGION` | AWS region (e.g. eu-north-1) |
| `S3_BUCKET_NAME` | S3 bucket for storing audio and summaries |
| `DISPLAY` | Virtual display (set to :99) |

---

## 📡 API Endpoints

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/deploy-bot` | POST | ✅ Required | Deploy bot to a Google Meet URL |
| `/job-status/{job_id}` | GET | ❌ Public | Poll bot/processing status |

### Deploy Bot Request

```json
POST /deploy-bot
Authorization: Bearer <firebase_id_token>
Content-Type: application/json

{
  "url": "https://meet.google.com/abc-defg-hij"
}
```

### Job Status Response

```json
{
  "job_id": "uuid",
  "status": "completed",
  "result": {
    "executive": "The team discussed Q2 roadmap...",
    "actionItems": [
      { "assignee": "John", "task": "Deploy new feature", "priority": "High" }
    ],
    "duration": "45 minutes",
    "participants": ["John", "Sarah", "Mike"]
  }
}
```

---

## 🔒 Security Notes

- `firebase-credentials.json` and `.env` are **never committed** (in `.gitignore`)
- All API endpoints require a valid Firebase ID token
- HTTPS enforced via Nginx + Let's Encrypt
- Bot name clearly identifies itself as "AI Scribe Bot" in meetings

---

## 📊 Summary Output Format

```json
{
  "executive": "Brief paragraph summary of the meeting",
  "actionItems": [
    {
      "assignee": "Person responsible",
      "task": "What needs to be done",
      "priority": "High | Medium | Low"
    }
  ],
  "duration": "Estimated meeting length",
  "participants": ["List of detected participants"]
}
```

---

## ⚠️ Known Limitations

- One bot per server instance (concurrent meetings require multiple EC2 instances)
- Bot must be **manually admitted** by the meeting host
- Google Meet UI changes may require updating DOM selectors in `meet_boot.py`
- Free tier EC2 (t3.micro) has limited RAM — 2GB swap recommended

---

## 📄 License

MIT License — feel free to use, modify, and distribute.

---

## 🙏 Acknowledgements

- [undetected-chromedriver](https://github.com/ultrafunkamsterdam/undetected-chromedriver) — for bypassing bot detection
- [Google Gemini](https://deepmind.google/technologies/gemini/) — for AI summarization
- [FastAPI](https://fastapi.tiangolo.com/) — for the backend framework
- [Firebase](https://firebase.google.com/) — for authentication and hosting
