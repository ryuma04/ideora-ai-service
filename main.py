import os
import time
import datetime
import sys
import requests
import uvicorn
import pymongo
import cloudinary
import cloudinary.uploader
import markdown
import traceback
import base64
from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
from dotenv import load_dotenv
from typing import List, Optional
from fpdf import FPDF
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
groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))

app = FastAPI(title="Ideora AI Service (Groq Proxy Edition)")

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
    print(f"Step 7: Creating PDF (Professional HTML format)...", flush=True)
    try:
        from fpdf import FPDF, HTMLMixin
        
        # We use a mixin class to support HTML rendering
        class MyPDF(FPDF, HTMLMixin):
            pass

        pdf = MyPDF()
        pdf.add_page()
        
        # Convert Markdown to basic HTML for better PDF support
        # FPDF HTML only supports a subset: h1-h6, b, u, i, p, br, a, img
        html_content = markdown.markdown(mom_text)
        
        # Basic cleanup: remove bold tags as they sometimes cause issues in old fpdf2 versions
        # or replace them with something safer if needed, but let's try standard first.
        
        pdf.write_html(f"""
            <font family="helvetica" size="14">
                {html_content}
            </font>
        """)
        
        pdf.output(output_path)
        print(f"PDF created successfully at {output_path}", flush=True)
        return True
    except Exception as e:
        print(f"PDF creation error: {e}", flush=True)
        traceback.print_exc()
        # Fallback to simple text if HTML fails
        return create_pdf_simple(mom_text, output_path)

def create_pdf_simple(mom_text: str, output_path: str):
    try:
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Helvetica", size=12)
        clean_text = mom_text.replace("•", "-").replace("—", "-").replace("**", "")
        for line in clean_text.split('\n'):
            pdf.multi_cell(w=190, h=8, txt=line.encode('latin-1', 'replace').decode('latin-1'), align='L')
        pdf.output(output_path)
        return True
    except: return False

def send_mom_emails(emails: List[str], mom_text: str, pdf_path: str, mom_url: str):
    print(f"Step 10: Sending emails to {emails} via Google Proxy...", flush=True)
    proxy_url = os.getenv("GMAIL_PROXY_URL")
    if not proxy_url:
        print("Skipping email: GMAIL_PROXY_URL not set.", flush=True)
        return

    try:
        pdf_base64 = ""
        if os.path.exists(pdf_path):
            with open(pdf_path, "rb") as f:
                pdf_base64 = base64.b64encode(f.read()).decode('utf-8')
        
        # Ideora Branding Styles
        base_styles = "font-family: 'Inter', system-ui, -apple-system, sans-serif; background-color: #f4f7fa; padding: 40px 20px; color: #1e293b; line-height: 1.6;"
        card_styles = "max-width: 600px; margin: 0 auto; background: #ffffff; border-radius: 16px; overflow: hidden; box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1);"
        header_styles = "background-color: #4f46e5; padding: 32px 20px; text-align: center;"
        content_styles = "padding: 40px 32px;"
        button_styles = "display: inline-block; background-color: #4f46e5; color: #ffffff !important; padding: 14px 32px; border-radius: 10px; text-decoration: none; font-weight: 600; font-size: 16px;"
        footer_styles = "background-color: #f8fafc; padding: 24px 32px; text-align: center; border-top: 1px solid #f1f5f9;"
        current_year = datetime.datetime.now().year

        html_body = f"""
        <div style="{base_styles}">
            <div style="{card_styles}">
                <div style="{header_styles}"><h1 style="color: #ffffff; margin: 0; font-size: 28px; font-weight: 800;">Ideora</h1></div>
                <div style="{content_styles}">
                    <h2 style="margin-top: 0; color: #0f172a; font-size: 20px; font-weight: 700;">Meeting Minutes Ready</h2>
                    <p style="color: #475569; margin-bottom: 32px;">The Minutes of Meeting (MoM) for your recent session have been generated. You can find the summary below and the full PDF attached to this email.</p>
                    <div style="text-align: center;">
                        <a href="{mom_url}" style="{button_styles}">View MoM Online</a>
                    </div>
                    <p style="margin-top: 32px; padding-top: 24px; border-top: 1px solid #f1f5f9; color: #94a3b8; font-size: 14px;">
                        This report was automatically generated by Ideora AI.
                    </p>
                </div>
                <div style="{footer_styles}"><p style="margin: 0; color: #64748b; font-size: 12px;">&copy; {current_year} Ideora. All rights reserved.</p></div>
            </div>
        </div>
        """
        
        payload = {
            "to": emails,
            "subject": "Meeting Minutes Ready - Ideora",
            "body": html_body,
            "pdfBase64": pdf_base64,
            "pdfName": os.path.basename(pdf_path),
            "token": "ideora_secret" # Must match Google Script token
        }
        
        resp = requests.post(proxy_url, json=payload, timeout=30)
        print(f"Proxy response: {resp.text}", flush=True)
        
        if resp.status_code == 200 and "success" in resp.text:
            print("Emails sent successfully via Gmail Proxy!", flush=True)
        else:
            print(f"!!! Proxy delivery failure: {resp.text}", flush=True)
            
    except Exception as e:
        print(f"!!! Error calling Gmail Proxy: {e}", flush=True)
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
            print(f"Step 2: Downloading brainstorming...", flush=True)
            b_resp = requests.get(brainstormingUrl, timeout=10)
            if b_resp.status_code == 200: brainstorming_content = b_resp.text
        
        # 2. Transcribe
        transcript = transcribe_audio(audio_path)
        print(f"--- TRANSCRIPTION START ---\n{transcript}\n--- TRANSCRIPTION END ---", flush=True)
        
        # 3. Metadata & MoM
        meeting_date = "Not specified"
        participants_info = []
        host_email = ""
        try:
            m_doc = db.meetings.find_one({"_id": ObjectId(meetingId)})
            if m_doc:
                if m_doc.get("startTime"): meeting_date = str(m_doc["startTime"])
                
                # Fetch Host Email directly from meeting creator
                host_id = m_doc.get("createdBy")
                if host_id:
                    host_user = db.users.find_one({"_id": host_id})
                    if host_user and host_user.get("email"):
                        host_email = host_user["email"]
                        print(f"Host identified: {host_email}", flush=True)
            
            p_cursor = db.participants.find({"meetingId": ObjectId(meetingId)})
            for p in p_cursor:
                name = p.get("name", "Unknown")
                # Priority: Participant collection email -> linked User email
                email = p.get("email")
                if not email and p.get("userId"):
                    u = db.users.find_one({"_id": p["userId"]})
                    if u and u.get("email"): email = u["email"]
                
                email = email or "Not available"
                participants_info.append(f"{name} ({email})")
                print(f"Participant processed: {name} <{email}>", flush=True)
            
            # Ensure host is in the list with their email
            if host_email:
                host_entry = f"Host ({host_email})"
                if not any(host_email in p for p in participants_info):
                    participants_info.append(host_entry)
                
            participants_info = list(set(participants_info))
            print(f"Final participant list for MoM: {participants_info}", flush=True)
        except Exception as e:
            print(f"CRITICAL Metadata fetching error: {e}", flush=True)
            traceback.print_exc()
            
        mom_text = generate_mom(transcript, brainstorming_content, meeting_date, participants_info)
        
        # 4. PDF & Cloudinary
        pdf_path = f"{temp_dir}/{meetingId}_MoM.pdf"
        pdf_success = create_pdf(mom_text, pdf_path)
        
        mom_url = ""
        if pdf_success:
            print(f"Step 8: Uploading PDF to Cloudinary...", flush=True)
            # Ensure a unique filename to bypass cached private settings
            unique_name = f"{meetingId}_MoM_{int(time.time())}.pdf"
            
            upload = cloudinary.uploader.upload(
                pdf_path, 
                resource_type="raw", 
                folder="meeting_mom", 
                public_id=unique_name,
                access_mode="public"
            )
            mom_url = upload.get("secure_url")
            print(f"MoM Uploaded: {mom_url}", flush=True)
        
        # 5. DB Update
        print(f"Step 9: Updating MongoDB collection 'meetingresources'...", flush=True)
        update_data = {"$set": {"momReportUrl": mom_url}}
        res = db.meetingresources.update_one({"meetingId": ObjectId(meetingId)}, update_data, upsert=True)
        print(f"Update Result: matched={res.matched_count}, modified={res.modified_count}", flush=True)
        
        # 6. Emails
        emails = []
        for info in participants_info:
            if "(" in info and "@" in info:
                email = info.split("(")[-1].split(")")[0]
                if "@" in email: emails.append(email)
        
        if emails: send_mom_emails(emails, mom_text, pdf_path, mom_url)
        
        print(f"--- [DONE] Total time: {time.time() - start_time:.2f}s ---", flush=True)
        if os.path.exists(audio_path): os.remove(audio_path)
        if os.path.exists(pdf_path): os.remove(pdf_path)
        
    except Exception as e:
        print(f"!!! CRITICAL ERROR in process_task: {e}", flush=True)
        traceback.print_exc()

@app.get("/health")
async def health(): return {"status": "healthy", "engines": ["groq", "gmail-proxy"]}

@app.post("/process-meeting")
async def process_meeting(request: RetrievalRequest, background_tasks: BackgroundTasks):
    print(f"--> Received Request for meeting ID: {request.meetingId}", flush=True)
    background_tasks.add_task(process_task, request.meetingId, request.audioUrl, request.brainstormingUrl)
    return {"success": True, "message": "Groq AI processing started"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
