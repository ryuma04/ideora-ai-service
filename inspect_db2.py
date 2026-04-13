import os
import pymongo
from dotenv import load_dotenv

load_dotenv("/Users/zainab/Meeting Platform/Ideora/ideora-ai-service/.env")
db_url = os.getenv("MONGODB_URL")
client = pymongo.MongoClient(db_url)
db = client.get_database()

string_created_by = list(db.meetings.find({"createdBy": {"$type": "string"}}).limit(5))
print("Meetings with string createdBy:", string_created_by)

string_user_id = list(db.participants.find({"userId": {"$type": "string"}}).limit(5))
print("Participants with string userId:", string_user_id)
