import os
import pymongo
from bson import ObjectId
from dotenv import load_dotenv

load_dotenv("/Users/zainab/Meeting Platform/Ideora/ideora-ai-service/.env")
db_url = os.getenv("MONGODB_URL")
client = pymongo.MongoClient(db_url)
db = client.get_database()

print("Collections:", db.list_collection_names())
m = db.meetings.find_one({}, {"_id": 1, "createdBy": 1})
print("Sample meeting:", m)
if m:
    print("createdBy type:", type(m.get("createdBy")))
    u = db.users.find_one({"_id": m.get("createdBy")})
    print("User for createdBy:", u)

p = db.participants.find_one({"userId": {"$exists": True}})
print("Sample participant:", p)
if p:
    print("userId type:", type(p.get("userId")))
    u_p = db.users.find_one({"_id": p.get("userId")})
    print("User for userId:", u_p)

# Let's see if there are any users that are stored with string ID or something
string_users = list(db.users.find({"_id": {"$type": "string"}}).limit(5))
print("Users with string _id:", string_users)
