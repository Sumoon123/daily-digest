# -*- coding: utf-8 -*-
import os
from dotenv import load_dotenv
import google.generativeai as genai

load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

print("Checking available Gemini models...")
print("=" * 60)

try:
    models = genai.list_models()
    print("Available models:")
    for model in models:
        if 'generateContent' in model.supported_generation_methods:
            print(f"[OK] {model.name}")
except Exception as e:
    print(f"Failed to list models: {e}")

print("\nTesting common model names...")
print("=" * 60)

# Try common models
test_models = [
    "gemini-1.5-flash-latest",
    "gemini-1.5-pro-latest", 
    "gemini-1.0-pro-latest",
    "gemini-1.5-flash-8b-latest",
    "gemini-1.5-pro-002",
    "gemini-1.5-flash-002"
]

for model_name in test_models:
    try:
        model = genai.GenerativeModel(model_name)
        response = model.generate_content("Say hello")
        print(f"[OK] {model_name} - Working!")
        break
    except Exception as e:
        error_msg = str(e)
        if "404" in error_msg:
            print(f"[X] {model_name} - Not found")
        elif "400" in error_msg:
            print(f"[X] {model_name} - Bad request / API key issue")
        else:
            print(f"[X] {model_name} - Error: {error_msg[:60]}")
