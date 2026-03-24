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
import traceback
from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
from dotenv import load_dotenv
from typing import List, Optional
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart, MIMEBase
from email.mime.application import MIMEApplication
from bson import ObjectId
from groq import Groq

# Conditional import for WeasyPrint
try:
    from weasyprint import HTML, CSS
    WEASYPRINT_AVAILABLE = True
except Exception as e:
    print(f"Warning: WeasyPrint not fully available: {e}")
    WEASYPRINT_AVAILABLE = False

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
db_url = os.getenv("MONGODB_URL")
db_client = pymongo.MongoClient(db_url)
db = db_client.get_database()
print(f"Connected to MongoDB: {db.name}", flush=True)

# Groq Configuration
groq_api_key = os.getenv("GROQ_API_KEY")
groq_client = Groq(api_key=groq_api_key)

app = FastAPI(title="Ideora AI Service (Groq Edition)")

class RetrievalRequest(BaseModel):
    meetingId: str
    audioUrl: str
    brainstormingUrl: Optional[str] = ""

def transcribe_audio(audio_path: str) -> str:
    print(f"Step 3: Transcribing {os.path.basename(audio_path)} using Groq Whisper...", flush=True)
    try:
        with open(audio_path, "rb") as file:
            transcription = groq_client.audio.transcriptions.create(
                file=(os.path.basename(audio_path), file.read()),
                model="whisper-large-v3",
                response_format="text",
            )
        return str(transcription)
    except Exception as e:
        print(f"Transcription error: {e}", flush=True)
        raise e

def generate_mom(transcript: str, brainstorming: str, date: str, participants: List[str]) -> str:
    print(f"Step 5: Generating MoM using Groq Llama 3 for {len(participants)} participants...", flush=True)
    participants_str = "\n".join([f"- {p}" for p in participants])
    
    prompt = f"""
    Generate a high-quality, professional Minutes of Meeting (MoM) from the following meeting data.
    
    MEETING DATE: {date}
    PARTICIPANTS: {participants_str}
    TRANSCRIPT: {transcript}
    BRAINSTORMING REPORT: {brainstorming}
    
    Structure:
    # Minutes of Meeting: Title
    ## 1. General Information
    ## 2. Executive Summary
    ## 3. Key Discussion Points
    ## 4. Decisions Made
    ## 5. Action Items (Table)
    ## 6. Next Steps
    """
    
    try:
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=4096
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"LLM error: {e}", flush=True)
        raise e

def get_meeting_metadata(meeting_id: str):
    print(f"Step 4: Fetching metadata for meeting {meeting_id}...", flush=True)
    participants_info = []
    meeting_date = "Not specified"
    try:
        meeting = db.meetings.find_one({"_id": ObjectId(meeting_id)})
        if meeting and meeting.get("startTime"):
            meeting_date = str(meeting["startTime"])

        participants_cursor = db.participants.find({"meetingId": ObjectId(meeting_id)})
        for participant in participants_cursor:
            name = participant.get("name", "Unknown")
            email = participant.get("email") or "Not available"
            if participant.get("userId"):
                user = db.users.find_one({"_id": participant["userId"]})
                if user and user.get("email"):
                    email = user["email"]
            participants_info.append(f"{name} ({email})")
            
    except Exception as e:
        print(f"Error fetching metadata: {e}", flush=True)
    return meeting_date, list(set(participants_info))

def create_pdf(mom_html_content: str, output_path: str):
    if not WEASYPRINT_AVAILABLE:
        print("Warning: Skipping PDF generation (WeasyPrint not available)", flush=True)
        return False
    
    print(f"Step 7: Creating PDF at {output_path}...", flush=True)
    try:
        css_styles = """
        @page { margin: 2cm; }
        body { font-family: sans-serif; font-size: 11pt; line-height: 1.6; color: #1e293b; }
        h1 { color: #4f46e5; border-bottom: 2px solid #e2e8f0; }
        h2 { color: #334155; border-left: 4px solid #4f46e5; padding-left: 0.3cm; margin-top: 1cm; }
        table { width: 100%; border-collapse: collapse; margin: 0.8cm 0; }
        th { background-color: #f8fafc; padding: 12px; border: 1px solid #e2e8f0; }
        td { padding: 10px; border: 1px solid #e2e8f0; }
        """
        full_html = f"<html><head><style>{css_styles}</style></head><body>{mom_html_content}</body></html>"
        HTML(string=full_html).write_pdf(output_path)
        return True
    except Exception as e:
        print(f"PDF creation error: {e}", flush=True)
        return False

def send_mom_emails(emails: List[str], mom_text: str, pdf_path: str):
    print(f"Step 10: Sending emails to {emails}...", flush=True)
    sender_email = os.getenv("GMAIL_MAIL")
    sender_password = os.getenv("GMAIL_APP_PASSWORD")
    if not sender_email or not sender_password:
        print("Skipping email: GMAIL credentials not set.", flush=True)
        return

    msg = MIMEMultipart('mixed')
    msg['From'] = f"Ideora Platform <{sender_email}>"
    msg['Subject'] = "Meeting Minutes Ready - Ideora"
    msg.attach(MIMEText(f"<h2>Meeting Minutes Ready</h2><p>Attached is the MoM as a PDF.</p>", 'html'))

    try:
        if os.path.exists(pdf_path):
            with open(pdf_path, "rb") as f:
                part = MIMEApplication(f.read(), Name=os.path.basename(pdf_path))
                part['Content-Disposition'] = f'attachment; filename="{os.path.basename(pdf_path)}"'
                msg.attach(part)

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, emails, msg.as_string())
        print("Emails sent successfully!", flush=True)
    except Exception as e:
        print(f"Failed to send email: {e}", flush=True)

async def process_task(meetingId: str, audioUrl: str, brainstormingUrl: str):
    start_time = time.time()
    print(f"--- [START] process_task for {meetingId} ---", flush=True)
    try:
        temp_dir = "/tmp/meeting_data"
        os.makedirs(temp_dir, exist_ok=True)
        
        # 1. Download
        print(f"Step 1: Downloading audio...", flush=True)
        audio_path = f"{temp_dir}/{meetingId}_audio.webm"
        resp = requests.get(audioUrl, timeout=30)
        with open(audio_path, "wb") as f: f.write(resp.content)
        print(f"Step 1 Done: Audio size {os.path.getsize(audio_path)} bytes", flush=True)
        
        brainstorming_content = ""
        if brainstormingUrl:
            print(f"Step 2: Downloading brainstorming...", flush=True)
            b_resp = requests.get(brainstormingUrl, timeout=10)
            if b_resp.status_code == 200: brainstorming_content = b_resp.text
        
        # 2. Transcribe
        transcript = transcribe_audio(audio_path)
        print(f"Step 3 Done: Transcript length {len(transcript)}", flush=True)
        
        # 3. Metadata & MoM
        meeting_date, participants = get_meeting_metadata(meetingId)
        mom_text = generate_mom(transcript, brainstorming_content, meeting_date, participants)
        print(f"Step 5 Done: MoM length {len(mom_text)}", flush=True)
        
        # 4. PDF & Cloudinary
        pdf_path = f"{temp_dir}/{meetingId}_MoM.pdf"
        pdf_success = create_pdf(markdown.markdown(mom_text, extensions=['tables']), pdf_path)
        
        if pdf_success:
            print(f"Step 8: Uploading PDF...", flush=True)
            upload = cloudinary.uploader.upload(pdf_path, resource_type="raw", folder="meeting_mom", public_id=f"{meetingId}_MoM")
            mom_url = upload["secure_url"]
        else:
            # Fallback: Just save as text or similar if PDF fails
            print("Warning: Continuing without PDF upload", flush=True)
            mom_url = "" # You could upload the text file here as fallback
        
        # 5. DB Update
        print(f"Step 9: Updating MongoDB...", flush=True)
        # Try both 'meetingResources' and 'meetingresources' collection names
        try:
            db.meetingResources.update_one({"meetingId": ObjectId(meetingId)}, {"$set": {"momReportUrl": mom_url}}, upsert=True)
        except:
            db.meetingresources.update_one({"meetingId": ObjectId(meetingId)}, {"$set": {"momReportUrl": mom_url}}, upsert=True)
        print("Step 9 Done: DB updated.", flush=True)
        
        # 6. Emails
        emails = [info.split("(")[-1].split(")")[0] for info in participants if "(" in info and "@" in info]
        if emails: send_mom_emails(emails, mom_text, pdf_path)
        
        print(f"--- [DONE] Total time: {time.time() - start_time:.2f}s ---", flush=True)
        if os.path.exists(audio_path): os.remove(audio_path)
        if os.path.exists(pdf_path): os.remove(pdf_path)
        
    except Exception as e:
        print(f"!!! CRITICAL ERROR in process_task: {e}", flush=True)
        traceback.print_exc()

@app.get("/health")
async def health(): 
    return {"status": "healthy", "engine": "groq", "weasyprint": WEASYPRINT_AVAILABLE}

@app.get("/test-groq")
async def test_groq():
    try:
        resp = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": "hello"}],
            max_tokens=5
        )
        return {"status": "ok", "response": resp.choices[0].message.content}
    except Exception as e:
        return {"status": "failed", "error": str(e)}

@app.get("/test-db")
async def test_db():
    try:
        return {"status": "connected", "collections": db.list_collection_names()}
    except Exception as e: 
        return {"status": "failed", "error": str(e)}

@app.post("/process-meeting")
async def process_meeting(request: RetrievalRequest, background_tasks: BackgroundTasks):
    print(f"--> Received Request for meeting ID: {request.meetingId}", flush=True)
    background_tasks.add_task(process_task, request.meetingId, request.audioUrl, request.brainstormingUrl)
    return {"success": True, "message": "Groq AI processing started"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
