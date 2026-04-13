import pymongo
from bson import ObjectId

db_url = "mongodb+srv://Ryuma:reze04102006@ideora-cluster.ks8eull.mongodb.net/ideora_db"
client = pymongo.MongoClient(db_url)
db = client.get_database()

# Find the latest few meetings
recent_meetings = db.meetings.find().sort("createdAt", -1).limit(5)
print("RECENT MEETINGS:")
for m in recent_meetings:
    print(f"ID: {m['_id']}, Title: {m.get('title')}, Host: {m.get('createdBy')}")
    # check meeting resources
    res = db.meetingresources.find_one({"meetingId": m["_id"]})
    if res:
        print(f"  Resource: audio={res.get('audioRecordingUrl') is not None}, mom={res.get('momReportUrl') is not None}")
    else:
        print("  Resource: NONE")
