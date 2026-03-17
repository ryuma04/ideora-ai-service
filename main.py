import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import cloudinary
import cloudinary.api
import requests
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Cloudinary Configuration
cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET"),
    secure=True
)

app = FastAPI(title="Ideora AI Service")

class RetrievalRequest(BaseModel):
    meetingId: str
    audioUrl: str
    brainstormingUrl: str

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

@app.post("/process-meeting")
async def process_meeting(request: RetrievalRequest):
    try:
        # 1. Retrieve Audio File
        audio_response = requests.get(request.audioUrl)
        if audio_response.status_code != 200:
            raise HTTPException(status_code=400, detail=f"Failed to retrieve audio from {request.audioUrl}")
        
        audio_content = audio_response.content
        # For now, we just log the size as a placeholder for processing
        print(f"Retrieved audio file: {len(audio_content)} bytes")

        # 2. Retrieve Brainstorming Doc
        doc_response = requests.get(request.brainstormingUrl)
        if doc_response.status_code != 200:
            raise HTTPException(status_code=400, detail=f"Failed to retrieve brainstorming doc from {request.brainstormingUrl}")
        
        doc_content = doc_response.content
        print(f"Retrieved brainstorming doc: {len(doc_content)} bytes")

        # Placeholder for AI logic (Summarization, Transcription, etc.) using the retrieved content
        
        return {
            "success": True,
            "message": "Files retrieved successfully and ready for processing",
            "audio_size": len(audio_content),
            "doc_size": len(doc_content)
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
