import os
from dotenv import load_dotenv

load_dotenv()
print(f"Current working directory: {os.getcwd()}")
print(f"Is .env file present in CWD? {os.path.exists('.env')}")