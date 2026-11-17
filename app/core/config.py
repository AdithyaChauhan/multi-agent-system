import os
from dotenv import load_dotenv

load_dotenv()

SESSION_EXPIRY_MINUTES = int(os.getenv("SESSION_EXPIRY_MINUTES", "30"))

# The one place the chat model is named. Checked against https://api.groq.com/openai/v1/models
# on 2026-11-17 (active). Deliberately not read from LLM_MODEL: older .env files set that to a
# retired Groq model that would break every agent at once.
GROQ_MODEL = os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b")
