import pymongo
from bson import ObjectId

db_url = "mongodb+srv://Ryuma:reze04102006@ideora-cluster.ks8eull.mongodb.net/ideora_db"
client = pymongo.MongoClient(db_url)
db = client.get_database()

res = db.meetingresources.find_one({"meetingId": ObjectId("69db72009a2e28c9d40806cb")})
print("Resource:", res)
