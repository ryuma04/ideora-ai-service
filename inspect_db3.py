import os
import pymongo
from dotenv import load_dotenv

load_dotenv("/Users/zainab/Meeting Platform/Ideora/ideora-ai-service/.env")
db_url = os.getenv("MONGODB_URL")
client = pymongo.MongoClient(db_url)
db = client.get_database()

users_count = db.users.count_documents({})
print("Total users:", users_count)

# let's see how many users dont have email
no_email_users_count = db.users.count_documents({"email": {"$exists": False}})
print("Users without email:", no_email_users_count)

# what about users that have email but we can't find them by objectId?
