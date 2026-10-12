import os
from dotenv import load_dotenv
from google import genai

load_dotenv()
client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
r = client.models.generate_content(
    model=os.environ["MODEL"],
    contents="In one sentence, what is an AI agent?",
)
print(r.text)
