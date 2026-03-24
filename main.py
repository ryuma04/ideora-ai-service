import os
import datetime
import sys
import time

# --- Cross-Platform Library Configuration ---
# This ensures WeasyPrint and other tools find their dependencies on both Mac and Linux
if sys.platform == "darwin":
    # Help WeasyPrint find Homebrew libraries on Mac
    hb_paths = ["/opt/homebrew/lib", "/usr/local/lib"]
    for path in hb_paths:
        if os.path.exists(path):
            os.environ["DYLD_LIBRARY_PATH"] = path + (":" + os.environ.get("DYLD_LIBRARY_PATH", "") if "DYLD_LIBRARY_PATH" in os.environ else "")
            os.environ["PATH"] = path + ":" + os.environ.get("PATH", "")
# -----------------------------------------------

import requests
import uvicorn
import whisper
import pymongo
import smtplib
import cloudinary
import cloudinary.uploader
from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
from dotenv import load_dotenv
from typing import List, Optional
import markdown
from weasyprint import HTML, CSS
from langchain_ollama import OllamaLLM
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart, MIMEBase
from email.mime.application import MIMEApplication
from bson import ObjectId

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
client = pymongo.MongoClient(os.getenv("MONGODB_URL"))
db = client.get_database() # This will use the database name from the URL if provided, or 'test'
# If the URL doesn't specify, we might need a backup. Let's try to get it from the URL.
# The .env says: mongodb+srv://Ryuma:reze04102006@ideora-cluster.ks8eull.mongodb.net/ideora_db
# So db is indeed 'ideora_db'

app = FastAPI(title="Ideora AI Service")

# Models and API Config
OLLAMA_URL = os.getenv("OLLAMA_API_URL", "http://localhost:11434")

# Initialize LLM
llm = OllamaLLM(model="ministral-3:3b", base_url=OLLAMA_URL)

def check_ollama_health():
    print(f"Checking Ollama health at {OLLAMA_URL}...")
    try:
        response = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        if response.status_code == 200:
            print("Ollama is reachable.")
            models = response.json().get("models", [])
            model_names = [m["name"] for m in models]
            if "ministral-3:3b" in model_names:
                print("Model 'ministral-3:3b' is available.")
            else:
                print(f"Warning: 'ministral-3:3b' not found in models: {model_names}")
        else:
            print(f"Ollama returned error: {response.status_code}")
    except Exception as e:
        print(f"Failed to connect to Ollama at {OLLAMA_URL}: {e}")

class RetrievalRequest(BaseModel):
    meetingId: str
    audioUrl: str
    brainstormingUrl: Optional[str] = ""

def transcribe_audio(audio_path: str) -> str:
    # Memory Optimization: Load model on-demand and use 'tiny' version for free tier
    print(f"Loading Whisper model (tiny)...")
    temp_model = whisper.load_model("tiny")
    print(f"Transcribing {audio_path}...")
    result = temp_model.transcribe(audio_path)
    
    # Explicitly clear memory after task
    del temp_model
    import gc
    gc.collect()
    
    return result["text"]

def generate_mom(transcript: str, brainstorming: str, date: str, participants: List[str]) -> str:
    print(f"Generating MoM for participants: {participants}")
    participants_str = "\n".join([f"- {p}" for p in participants])
    
    prompt = f"""
    Generate a high-quality, professional Minutes of Meeting (MoM) from the following meeting data.
    
    ---
    INTELLIGENT TRANSCRIPTION CLEANING:
    1. The provided TRANSCRIPT is raw speech-to-text and contains phonetic errors (e.g., misheard names, project titles, or technical terms).
    2. CROSS-REFERENCE: Use the BRAINSTORMING REPORT as your primary source of truth for correct spellings of project names, tools, and technical vocabulary mentioned in this specific meeting.
    3. PHONETIC CORRECTION: If a word in the transcript sounds like a technical term or project name from the brainstorming report but is spelled differently, use the correct version (e.g., if you see "BISPER" and the report mentions "Whisper", use "Whisper").
    4. GENERAL POLISHING: Remove filler words (um, ah, like), fix grammatical errors, and ensure the text is clear and professional.
    
    STRICT FORMATTING RULES:
    1. NO META-COMMENTS: Do not include phrases like "(likely a placeholder)", "(inferred)", or "(corrected)".
    2. CONSISTENT ORDERING: Use exactly the structure provided below with clean spacing.
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
    - **Participants:list of participants
    
    ## 2. Executive Summary
    - [A 2-3 sentence overview of the meeting's purpose and key outcomes]
    
    ## 3. Key Discussion Points
    - [Well-structured summary of point 1]
    - [Well-structured summary of point 2]
    
    ## 4. Decisions Made
    - [Formal list of any decisions reached]
    
    ## 5. Action Items
    | Task | Assigned To | Status |
    |------|-------------|--------|
    | [Clear actionable task] | [Name] | Pending |
    
    ## 6. Next Steps
    - [Upcoming milestones or follow-up meetings]
    
    Format as clean, professional Markdown.
    """
    return llm.invoke(prompt)




def get_meeting_metadata(meeting_id: str):
    print(f"Fetching metadata for meeting {meeting_id}...")
    participants_info = []
    meeting_date = "Not specified"
    try:
        # 1. Get meeting date
        meeting = db.meetings.find_one({"_id": ObjectId(meeting_id)})
        if meeting and meeting.get("startTime"):
            meeting_date = str(meeting["startTime"])

        # 2. Get participants for this meeting
        participants_cursor = db.participants.find({"meetingId": ObjectId(meeting_id)})
        for participant in participants_cursor:
            name = participant.get("name", "Unknown")
            email = "Not available"
            
            # If it's a registered user, get their email
            if participant.get("userId"):
                user = db.users.find_one({"_id": participant["userId"]})
                if user and user.get("email"):
                    email = user["email"]
            # Handle guest users if they have an email
            elif participant.get("email"):
                email = participant["email"]
            
            participants_info.append(f"{name} ({email})")
            
    except Exception as e:
        print(f"Error fetching metadata: {e}")
    
    # Unique list
    return meeting_date, list(set(participants_info))

def create_pdf(mom_html_content: str, output_path: str):
    print(f"Creating professional PDF at {output_path}...")
    
    # Modern professional CSS for the MoM
    css_styles = """
    @page {
        margin: 2cm;
        @bottom-right {
            content: "Page " counter(page) " of " counter(pages);
            font-size: 9pt;
            color: #64748b;
        }
    }
    body {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        font-size: 11pt;
        line-height: 1.6;
        color: #1e293b;
        margin: 0;
        padding: 0;
    }
    h1 {
        color: #4f46e5;
        font-size: 24pt;
        margin-bottom: 0.5cm;
        border-bottom: 2px solid #e2e8f0;
        padding-bottom: 0.2cm;
    }
    h2 {
        color: #334155;
        font-size: 16pt;
        margin-top: 1cm;
        margin-bottom: 0.4cm;
        border-left: 4px solid #4f46e5;
        padding-left: 0.3cm;
    }
    p {
        margin-bottom: 0.4cm;
    }
    ul, ol {
        margin-bottom: 0.5cm;
        padding-left: 0.8cm;
    }
    li {
        margin-bottom: 0.2cm;
    }
    table {
        width: 100%;
        border-collapse: collapse;
        margin: 0.8cm 0;
        font-size: 10pt;
    }
    th {
        background-color: #f8fafc;
        color: #475569;
        font-weight: 600;
        text-align: left;
        padding: 12px;
        border: 1px solid #e2e8f0;
    }
    td {
        padding: 10px 12px;
        border: 1px solid #e2e8f0;
        vertical-align: top;
    }
    tr:nth-child(even) {
        background-color: #f1f5f9;
    }
    .footer {
        margin-top: 2cm;
        padding-top: 0.5cm;
        border-top: 1px solid #e2e8f0;
        font-size: 9pt;
        color: #94a3b8;
        text-align: center;
    }
    """
    
    # Wrap content in a full HTML document
    full_html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <style>{css_styles}</style>
    </head>
    <body>
        {mom_html_content}
        <div class="footer">
            Generated by Ideora AI Platform &copy; {datetime.datetime.now().year}
        </div>
    </body>
    </html>
    """
    
    # Generate PDF
    HTML(string=full_html).write_pdf(output_path)



import markdown

def send_mom_emails(emails: List[str], mom_text: str, pdf_path: str):
    print(f"Sending emails to {emails}...")
    sender_email = os.getenv("GMAIL_MAIL")
    sender_password = os.getenv("GMAIL_APP_PASSWORD")
    
    if not sender_email or not sender_password:
        print("Skipping email: GMAIL credentials not set.")
        return
    
    # Explicitly cast to str for type checker
    sender_email_str: str = str(sender_email)
    sender_pw_str: str = str(sender_password)

    msg = MIMEMultipart('mixed')
    msg['From'] = f"Ideora Platform <{sender_email_str}>"
    msg['Subject'] = "Meeting Minutes Ready - Ideora"
    
    # Ported styles from mailer.ts
    base_styles = "font-family: 'Inter', system-ui, -apple-system, sans-serif; background-color: #f4f7fa; padding: 40px 20px; color: #1e293b; line-height: 1.6;"
    card_styles = "max-width: 600px; margin: 0 auto; background: #ffffff; border-radius: 16px; overflow: hidden; box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1);"
    header_styles = "background-color: #4f46e5; padding: 32px 20px; text-align: center;"
    content_styles = "padding: 40px 32px;"
    footer_styles = "background-color: #f8fafc; padding: 24px 32px; text-align: center; border-top: 1px solid #f1f5f9;"
    current_year = datetime.datetime.now().year

    # Formal email body following mailer.ts structure
    html_body = f"""
    <div style="{base_styles}">
        <div style="{card_styles}">
            <div style="{header_styles}">
                <h1 style="color: #ffffff; margin: 0; font-size: 28px; font-weight: 800;">Ideora</h1>
            </div>
            <div style="{content_styles}">
                <h2 style="margin-top: 0; color: #0f172a; font-size: 20px; font-weight: 700;">Meeting Minutes Ready</h2>
                <p style="color: #475569; margin-bottom: 24px;">
                    Hello, the Minutes of Meeting (MoM) for your recent session have been generated and are now available for review.
                </p>
                <p style="color: #475569; margin-bottom: 32px;">
                    You can find the detailed report attached to this email as a PDF.
                </p>
                <p style="margin-top: 32px; padding-top: 24px; border-top: 1px solid #f1f5f9; color: #94a3b8; font-size: 14px;">
                    If you have any questions regarding these minutes, please contact the meeting organizer.
                </p>
            </div>
            <div style="{footer_styles}">
                <p style="margin: 0; color: #64748b; font-size: 12px;">&copy; {current_year} Ideora. All rights reserved.</p>
            </div>
        </div>
    </div>
    """
    
    msg.attach(MIMEText(html_body, 'html'))

    # Attachment
    try:
        with open(pdf_path, "rb") as f:
            part = MIMEApplication(f.read(), Name=os.path.basename(pdf_path))
            part['Content-Disposition'] = f'attachment; filename="{os.path.basename(pdf_path)}"'
            msg.attach(part)



        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender_email_str, sender_pw_str)
            server.sendmail(sender_email_str, emails, msg.as_string())
        print("Emails sent successfully!")

    except Exception as e:
        print(f"Failed to send emails or attach PDF: {e}")


async def process_task(meetingId: str, audioUrl: str, brainstormingUrl: str):
    start_time = time.time()
    print(f"--- Starting process_task for meeting {meetingId} ---")
    try:
        # Create temp directory
        temp_dir = "/tmp/meeting_data"
        os.makedirs(temp_dir, exist_ok=True)
        
        # 1. Download Audio
        print(f"Step 1: Downloading audio from {audioUrl}...")
        audio_path = f"{temp_dir}/{meetingId}_audio.webm"
        audio_response = requests.get(audioUrl)
        if audio_response.status_code != 200:
            raise Exception(f"Failed to download audio: {audio_response.status_code}")
        with open(audio_path, "wb") as f:
            f.write(audio_response.content)
        print(f"Audio downloaded: {os.path.getsize(audio_path)} bytes")
        
        # 2. Download Brainstorming (if exists)
        brainstorming_content = ""
        if brainstormingUrl:
            print(f"Step 2: Downloading brainstorming report from {brainstormingUrl}...")
            doc_response = requests.get(brainstormingUrl)
            if doc_response.status_code == 200:
                brainstorming_content = doc_response.text
                print(f"Brainstorming content downloaded: {len(brainstorming_content)} chars")
            else:
                print(f"Warning: Brainstorming report not found (status {doc_response.status_code})")
        
        # 3. Transcribe
        print(f"Step 3: Starting transcription with Whisper (tiny)...")
        transcribe_start = time.time()
        transcript = transcribe_audio(audio_path)
        transcribe_end = time.time()
        print(f"Transcription completed in {transcribe_end - transcribe_start:.2f} seconds.")
        print(f"Transcript excerpt: {transcript[:100]}...")
        
        # 4. Get Metadata (Date and Participants)
        print(f"Step 4: Fetching meeting metadata from MongoDB...")
        meeting_date, participants_info = get_meeting_metadata(meetingId)
        print(f"Metadata: Date={meeting_date}, Participants count={len(participants_info)}")
        
        # 5. Generate MoM
        print(f"Step 5: Generating MoM using Ollama ({llm.model})...")
        llm_start = time.time()
        mom_text = generate_mom(transcript, brainstorming_content, meeting_date, participants_info)
        llm_end = time.time()
        print(f"MoM generated in {llm_end - llm_start:.2f} seconds.")
        
        # 6. Generate HTML for PDF styling
        print(f"Step 6: Converting Markdown to HTML...")
        mom_html = markdown.markdown(mom_text, extensions=['tables'])
        
        # 7. Create PDF with HTML styling
        print(f"Step 7: Creating PDF...")
        pdf_path = f"{temp_dir}/{meetingId}_MoM.pdf"
        create_pdf(mom_html, pdf_path)
        print(f"PDF created at {pdf_path}")
        
        # 8. Upload PDF to Cloudinary
        print(f"Step 8: Uploading PDF to Cloudinary...")
        upload_result = cloudinary.uploader.upload(
            pdf_path, 
            resource_type="raw", 
            folder="meeting_mom",
            public_id=f"{meetingId}_MoM"
        )
        mom_url = upload_result["secure_url"]
        print(f"PDF uploaded to Cloudinary: {mom_url}")
        
        # 9. Update MongoDB
        print(f"Step 9: Updating MongoDB collection 'meetingresources'...")
        update_result = db.meetingresources.update_one(
            {"meetingId": ObjectId(meetingId)},
            {"$set": {"momReportUrl": mom_url}},
            upsert=True
        )
        print(f"MongoDB update result: matched={update_result.matched_count}, modified={update_result.modified_count}, upserted_id={update_result.upserted_id}")
        
        # 10. Send Emails
        # Extract just emails from participants_info (format: "Name (email)")
        print(f"Step 10: Sending emails to participants...")
        emails = []
        for info in participants_info:
            if "(" in info and ")" in info:
                email = info.split("(")[-1].split(")")[0]
                if "@" in email:
                    emails.append(email)
        
        if emails:
            send_mom_emails(emails, mom_text, pdf_path)
        else:
            print("No valid emails found to send MoM.")
        
        # Cleanup
        if os.path.exists(audio_path): os.remove(audio_path)
        if os.path.exists(pdf_path): os.remove(pdf_path)
        
        total_time = time.time() - start_time
        print(f"--- Task completed successfully for meeting {meetingId} in {total_time:.2f}s ---")
        
    except Exception as e:
        print(f"!!! Error in process_task for meeting {meetingId}: {e}")
        import traceback
        traceback.print_exc()

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

@app.get("/test-ollama")
async def test_ollama():
    try:
        response = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        return {
            "status": "connected" if response.status_code == 200 else "error",
            "status_code": response.status_code,
            "models": response.json().get("models", [])
        }
    except Exception as e:
        return {"status": "failed", "error": str(e)}

@app.get("/test-db")
async def test_db():
    try:
        # Check connection implicitly by listing collections
        cols = db.list_collection_names()
        return {"status": "connected", "collections": cols}
    except Exception as e:
        return {"status": "failed", "error": str(e)}

@app.post("/process-meeting")
async def process_meeting(request: RetrievalRequest, background_tasks: BackgroundTasks):
    print(f"Received request to process meeting {request.meetingId}")
    # We trigger the processing in the background to avoid blocking the request
    background_tasks.add_task(process_task, request.meetingId, request.audioUrl, request.brainstormingUrl)
    return {
        "success": True,
        "message": "AI processing started in the background"
    }

if __name__ == "__main__":
    check_ollama_health()
    uvicorn.run(app, host="0.0.0.0", port=8000)

