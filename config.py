import os
from dotenv import load_dotenv

load_dotenv()


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise EnvironmentError(f"Missing required environment variable: {name}")
    return value


OPENAI_API_KEY = _require("OPENAI_API_KEY")
ELEVENLABS_API_KEY = _require("ELEVENLABS_API_KEY")
TWILIO_ACCOUNT_SID = _require("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = _require("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_NUMBER = _require("TWILIO_PHONE_NUMBER")
DEEPGRAM_API_KEY = _require("DEEPGRAM_API_KEY")
APP_BASE_URL = _require("APP_BASE_URL")
GOOGLE_SHEET_ID = _require("GOOGLE_SHEET_ID")

JOB_DESCRIPTION = """
Role: Backend Software Engineer
Experience: 3+ years
Required skills:

Java or Python
REST API design
SQL databases (PostgreSQL preferred)
Git and code review practices

Nice to have:

Spring Boot or FastAPI
Docker
Message queues (RabbitMQ or Kafka)
Cloud experience (AWS or GCP)

About the role:
You will design and build backend services for our hiring platform.
You will work closely with the frontend team and own full delivery
of API features from design to production.
"""

INTERVIEW_SYSTEM_PROMPT = """
You are a professional technical interviewer conducting a phone
screening for a software engineering role. You have the candidate's
resume and the job description.
Rules:

Ask one question at a time. Wait for the full answer.
Start with a brief warm introduction, then ask 5 to 6 questions.
Base questions on the candidate's actual resume and the role.
Vary question types: technical depth, past experience, problem solving.
Do not repeat questions already asked.
Keep your responses concise — under 40 words each.
When you have asked all questions, say exactly: INTERVIEW_COMPLETE
"""

if __name__ == "__main__":
    print("Config loaded successfully")
    print(f"Sheet ID: {GOOGLE_SHEET_ID}")
    print(f"Twilio number: {TWILIO_PHONE_NUMBER}")
    print(f"App base URL: {APP_BASE_URL}")
    print(f"JD preview: {JOB_DESCRIPTION[:80]}...")
