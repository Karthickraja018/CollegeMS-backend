import google.generativeai as genai
import os
from dotenv import load_dotenv

load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

models = genai.list_models()
for m in models:
    if 'embedContent' in m.supported_generation_methods:
        print(f"Model: {m.name}, Methods: {m.supported_generation_methods}")
