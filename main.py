import os
import datetime
import sys
import time
import requests
import uvicorn
import pymongo
import smtplib
import cloudinary
import cloudinary.uploader
import markdown
from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
from dotenv import load_dotenv
from typing import List, Optional
from weasyprint import HTML, CSS
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart, MIMEBase
from email.mime.application import MIMEApplication
from bson import ObjectId
from groq import Groq

# --- Cross-Platform Library Configuration ---
if sys.platform == "darwin":
    hb_paths = ["/opt/homebrew/lib", "/usr/local/lib"]
    for path in hb_paths:
        if os.path.exists(path):
            os.environ["DYLD_LIBRARY_PATH"] = path + (":" + os.environ.get("DYLD_LIBRARY_PATH", "") if "DYLD_LIBRARY_PATH" in os.environ else "")
            os.environ["PATH"] = path + ":" + os.environ.get("PATH", "")
# -----------------------------------------------

# Load environment variables
load_dotenv()

# Cloudinary Configuration
cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET"),
    secure=True
)

# MongoDB Configuration
db_client = pymongo.MongoClient(os.getenv("MONGODB_URL"))
db = db_client.get_database()

# Groq Configuration
groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))

app = FastAPI(title="Ideora AI Service (Groq Edition)")

class RetrievalRequest(BaseModel):
    meetingId: str
    audioUrl: str
    brainstormingUrl: Optional[str] = ""

def transcribe_audio(audio_path: str) -> str:
    print(f"Transcribing {audio_path} using Groq Whisper...")
    with open(audio_path, "rb") as file:
        transcription = groq_client.audio.transcriptions.create(
            file=(os.path.basename(audio_path), file.read()),
            model="distil-whisper-large-v3-en",
            response_format="text",
        )
    return str(transcription)

def generate_mom(transcript: str, brainstorming: str, date: str, participants: List[str]) -> str:
    print(f"Generating MoM using Groq Llama 3 for participants: {participants}")
    participants_str = "\n".join([f"- {p}" for p in participants])
    
    prompt = f"""
    Generate a high-quality, professional Minutes of Meeting (MoM) from the following meeting data.
    
    ---
    INTELLIGENT TRANSCRIPTION CLEANING:
    1. The provided TRANSCRIPT is raw speech-to-text and contains phonetic errors.
    2. CROSS-REFERENCE: Use the BRAINSTORMING REPORT as your primary source of truth for correct spellings.
    3. PHONETIC CORRECTION: Fix names/terms based on the report.
    4. GENERAL POLISHING: Remove fillers, fix grammar, ensure professional tone.
    
    STRICT FORMATTING RULES:
    1. NO META-COMMENTS.
    2. CONSISTENT ORDERING.
    3. NO HALLUCINATIONS: Use ONLY the provided MEETING DATE and ONLY the listed PARTICIPANTS.
    ---

    MEETING DATE: {date}
    PARTICIPANTS:
    {participants_str}
    
    TRANSCRIPT:
    {transcript}
    
    BRAINSTORMING REPORT:
    {brainstorming}
    
    REQUIRED STRUCTURE:
    # Minutes of Meeting: [A Professional, Descriptive Title]
    
    ## 1. General Information
    - **Date:** [Meeting Date]
    - **Participants:** [List]
    
    ## 2. Executive Summary
    - [A 2-3 sentence overview]
    
    ## 3. Key Discussion Points
    - [Summary point 1]
    - [Summary point 2]
    
    ## 4. Decisions Made
    - [Formal list of decisions]
    
    ## 5. Action Items
    | Task | Assigned To | Status |
    |------|-------------|--------|
    | [Task] | [Name] | Pending |
    
    ## 6. Next Steps
    - [Upcoming milestones]
    
    Format as clean, professional Markdown.
    """
    
    response = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
        max_tokens=4096
    )
    return response.choices[0].message.content

def get_meeting_metadata(meeting_id: str):
    print(f"Fetching metadata for meeting {meeting_id}...")
    participants_info = []
    meeting_date = "Not specified"
    try:
        meeting = db.meetings.find_one({"_id": ObjectId(meeting_id)})
        if meeting and meeting.get("startTime"):
            meeting_date = str(meeting["startTime"])

        participants_cursor = db.participants.find({"meetingId": ObjectId(meeting_id)})
        for participant in participants_cursor:
            name = participant.get("name", "Unknown")
            email = "Not available"
            if participant.get("userId"):
                user = db.users.find_one({"_id": participant["userId"]})
                if user and user.get("email"):
                    email = user["email"]
            elif participant.get("email"):
                email = participant["email"]
            participants_info.append(f"{name} ({email})")
            
    except Exception as e:
        print(f"Error fetching metadata: {e}")
    return meeting_date, list(set(participants_info))

def create_pdf(mom_html_content: str, output_path: str):
    print(f"Creating PDF at {output_path}...")
    css_styles = """
    @page { margin: 2cm; @bottom-right { content: "Page " counter(page) " of " counter(pages); font-size: 9pt; color: #64748b; } }
    body { font-family: sans-serif; font-size: 11pt; line-height: 1.6; color: #1e293b; }
    h1 { color: #4f46e5; border-bottom: 2px solid #e2e8f0; }
    h2 { color: #334155; border-left: 4px solid #4f46e5; padding-left: 0.3cm; margin-top: 1cm; }
    table { width: 100%; border-collapse: collapse; margin: 0.8cm 0; }
    th { background-color: #f8fafc; padding: 12px; border: 1px solid #e2e8f0; }
    td { padding: 10px; border: 1px solid #e2e8f0; }
    tr:nth-child(even) { background-color: #f1f5f9; }
    """
    full_html = f"<html><head><style>{css_styles}</style></head><body>{mom_html_content}</body></html>"
    HTML(string=full_html).write_pdf(output_path)

def send_mom_emails(emails: List[str], mom_text: str, pdf_path: str):
    print(f"Sending emails to {emails}...")
    sender_email = os.getenv("GMAIL_MAIL")
    sender_password = os.getenv("GMAIL_APP_PASSWORD")
    if not sender_email or not sender_password:
        print("Skipping email: GMAIL credentials not set.")
        return

    msg = MIMEMultipart('mixed')
    msg['From'] = f"Ideora Platform <{sender_email}>"
    msg['Subject'] = "Meeting Minutes Ready - Ideora"
    
    html_body = f"<div><h2>Meeting Minutes Ready</h2><p>The MoM is attached as a PDF.</p></div>"
    msg.attach(MIMEText(html_body, 'html'))

    try:
        with open(pdf_path, "rb") as f:
            part = MIMEApplication(f.read(), Name=os.path.basename(pdf_path))
            part['Content-Disposition'] = f'attachment; filename="{os.path.basename(pdf_path)}"'
            msg.attach(part)

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, emails, msg.as_string())
        print("Emails sent successfully!")
    except Exception as e:
        print(f"Failed to send email: {e}")

async def process_task(meetingId: str, audioUrl: str, brainstormingUrl: str):
    start_time = time.time()
    print(f"--- Starting process_task (Groq) for meeting {meetingId} ---")
    try:
        temp_dir = "/tmp/meeting_data"
        os.makedirs(temp_dir, exist_ok=True)
        
        # 1. Download
        audio_path = f"{temp_dir}/{meetingId}_audio.webm"
        resp = requests.get(audioUrl)
        with open(audio_path, "wb") as f: f.write(resp.content)
        
        brainstorming_content = ""
        if brainstormingUrl:
            b_resp = requests.get(brainstormingUrl)
            if b_resp.status_code == 200: brainstorming_content = b_resp.text
        
        # 2. Transcribe
        transcript = transcribe_audio(audio_path)
        
        # 3. Metadata & MoM
        meeting_date, participants = get_meeting_metadata(meetingId)
        mom_text = generate_mom(transcript, brainstorming_content, meeting_date, participants)
        
        # 4. PDF
        pdf_path = f"{temp_dir}/{meetingId}_MoM.pdf"
        create_pdf(markdown.markdown(mom_text, extensions=['tables']), pdf_path)
        
        # 5. Cloudinary & DB
        upload = cloudinary.uploader.upload(pdf_path, resource_type="raw", folder="meeting_mom", public_id=f"{meetingId}_MoM")
        db.meetingresources.update_one({"meetingId": ObjectId(meetingId)}, {"$set": {"momReportUrl": upload["secure_url"]}}, upsert=True)
        
        # 6. Emails
        emails = [info.split("(")[-1].split(")")[0] for info in participants if "(" in info and "@" in info]
        if emails: send_mom_emails(emails, mom_text, pdf_path)
        
        print(f"--- Task completed in {time.time() - start_time:.2f}s ---")
        if os.path.exists(audio_path): os.remove(audio_path)
        if os.path.exists(pdf_path): os.remove(pdf_path)
        
    except Exception as e:
        print(f"!!! Error: {e}")

@app.get("/health")
async def health(): return {"status": "healthy", "engine": "groq"}

@app.get("/test-db")
async def test_db():
    try:
        cols = db.list_collection_names()
        return {"status": "connected", "collections": cols}
    except Exception as e: return {"status": "failed", "error": str(e)}

@app.post("/process-meeting")
async def process_meeting(request: RetrievalRequest, background_tasks: BackgroundTasks):
    print(f"Received meeting {request.meetingId}")
    background_tasks.add_task(process_task, request.meetingId, request.audioUrl, request.brainstormingUrl)
    return {"success": True, "message": "Groq AI processing started"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
