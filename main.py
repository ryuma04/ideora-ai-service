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
from fpdf import FPDF
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart, MIMEBase
from email.mime.application import MIMEApplication
from bson import ObjectId
from groq import Groq

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
    print(f"Step 3: Transcribing using Groq Whisper...", flush=True)
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
    print(f"Step 5: Generating MoM using Groq Llama 3...", flush=True)
    participants_str = "\n".join([f"- {p}" for p in participants])
    
    prompt = f"""
    Generate a high-quality, professional Minutes of Meeting (MoM) from the following meeting data.
    
    ---
    INTELLIGENT TRANSCRIPTION CLEANING:
    1. Use BRAINSTORMING REPORT as primary source for spellings.
    2. Remove fillers (um, ah), fix grammar, ensure professional tone.
    
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
    ## 5. Action Items
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

def create_pdf(mom_text: str, output_path: str):
    print(f"Step 7: Creating PDF (FPDF2)...", flush=True)
    try:
        # FPDF2 allows for better UTF-8 handling if we use a standard font
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Helvetica", size=12)
        
        # Clean up text for latin-1 which is the default for standard PDF fonts
        # Better: Replace bullet points and special characters that Llama 3 often uses
        clean_text = mom_text.replace("•", "-").replace("—", "-").replace("**", "")
        
        # Split into lines and write to PDF
        lines = clean_text.split('\n')
        for line in lines:
            # We encode to latin-1 and ignore errors to prevent crashes, 
            # while still trying to preserve as much as possible
            safe_line = line.encode('latin-1', 'replace').decode('latin-1')
            pdf.multi_cell(w=190, h=8, txt=safe_line, align='L')
            
        pdf.output(output_path)
        print(f"PDF created successfully at {output_path}", flush=True)
        return True
    except Exception as e:
        print(f"PDF creation error: {e}", flush=True)
        traceback.print_exc()
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
    msg['To'] = ", ".join(emails) # Good practice to include To header
    msg['Subject'] = "Meeting Minutes Ready - Ideora"
    
    html_body = f"""
    <div style="font-family: sans-serif; color: #1e293b;">
        <h2 style="color: #4f46e5;">Meeting Minutes Ready</h2>
        <p>The Minutes of Meeting (MoM) have been generated and are attached as a PDF.</p>
        <p>Best regards,<br>The Ideora Team</p>
    </div>
    """
    msg.attach(MIMEText(html_body, 'html'))

    try:
        if os.path.exists(pdf_path):
            with open(pdf_path, "rb") as f:
                part = MIMEApplication(f.read(), Name=os.path.basename(pdf_path))
                part['Content-Disposition'] = f'attachment; filename="{os.path.basename(pdf_path)}"'
                msg.attach(part)
        
        print("Connecting to gmail (SMTP 587)...", flush=True)
        # Using 587 with STARTTLS is generally more robust on cloud servers
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=15) as server:
            print("Starting TLS...", flush=True)
            server.starttls()
            print("Logging in...", flush=True)
            server.login(sender_email, sender_password)
            print("Sending mail...", flush=True)
            server.sendmail(sender_email, emails, msg.as_string())
            
        print("Emails sent successfully!", flush=True)
    except Exception as e:
        print(f"!!! Email delivery error: {e}", flush=True)
        traceback.print_exc()

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
        
        brainstorming_content = ""
        if brainstormingUrl:
            b_resp = requests.get(brainstormingUrl, timeout=10)
            if b_resp.status_code == 200: brainstorming_content = b_resp.text
        
        # 2. Transcribe
        transcript = transcribe_audio(audio_path)
        
        # 3. Metadata & MoM
        # Fetch metadata using our custom logic
        meeting_date = "Not specified"
        participants_info = []
        try:
            m_doc = db.meetings.find_one({"_id": ObjectId(meetingId)})
            if m_doc and m_doc.get("startTime"): meeting_date = str(m_doc["startTime"])
            
            p_cursor = db.participants.find({"meetingId": ObjectId(meetingId)})
            for p in p_cursor:
                name = p.get("name", "Unknown")
                email = p.get("email") or "Not available"
                if p.get("userId"):
                    u = db.users.find_one({"_id": p["userId"]})
                    if u and u.get("email"): email = u["email"]
                participants_info.append(f"{name} ({email})")
            participants_info = list(set(participants_info))
        except Exception as e:
            print(f"Metadata error: {e}", flush=True)
            
        mom_text = generate_mom(transcript, brainstorming_content, meeting_date, participants_info)
        
        # 4. PDF & Cloudinary
        pdf_path = f"{temp_dir}/{meetingId}_MoM.pdf"
        pdf_success = create_pdf(mom_text, pdf_path)
        
        mom_url = ""
        if pdf_success:
            print(f"Step 8: Uploading PDF...", flush=True)
            upload = cloudinary.uploader.upload(pdf_path, resource_type="raw", folder="meeting_mom", public_id=f"{meetingId}_MoM")
            mom_url = upload["secure_url"]
            print(f"Uploaded: {mom_url}", flush=True)
        
        # 5. DB Update
        print(f"Step 9: Updating MongoDB collection 'meetingresources'...", flush=True)
        update_data = {"$set": {"momReportUrl": mom_url}}
        
        # Using plural 'meetingresources' as requested
        res = db.meetingresources.update_one({"meetingId": ObjectId(meetingId)}, update_data, upsert=True)
        print(f"Update Result: matched={res.matched_count}, modified={res.modified_count}", flush=True)
        
        # 6. Emails
        emails = []
        for info in participants_info:
            if "(" in info and "@" in info:
                email = info.split("(")[-1].split(")")[0]
                if "@" in email: emails.append(email)
        
        if emails: send_mom_emails(emails, mom_text, pdf_path)
        
        print(f"--- [DONE] Total time: {time.time() - start_time:.2f}s ---", flush=True)
        if os.path.exists(audio_path): os.remove(audio_path)
        if os.path.exists(pdf_path): os.remove(pdf_path)
        
    except Exception as e:
        print(f"!!! CRITICAL ERROR in process_task: {e}", flush=True)
        traceback.print_exc()

@app.get("/health")
async def health(): return {"status": "healthy", "engine": "groq"}

@app.post("/process-meeting")
async def process_meeting(request: RetrievalRequest, background_tasks: BackgroundTasks):
    print(f"--> Received Request for meeting ID: {request.meetingId}", flush=True)
    background_tasks.add_task(process_task, request.meetingId, request.audioUrl, request.brainstormingUrl)
    return {"success": True, "message": "Groq AI processing started"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
