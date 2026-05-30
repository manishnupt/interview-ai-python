from dotenv import load_dotenv
load_dotenv()
import sys
import config
from interview.dialer import place_call

if __name__ == "__main__":
    phone = sys.argv[1] if len(sys.argv) > 1 else None
    if not phone:
        print("Usage: python test_call.py +91xxxxxxxxxx")
        sys.exit(1)

    print(f"Placing test call to {phone}")
    print(f"Make sure uvicorn and ngrok are running first!")
    print(f"APP_BASE_URL: {config.APP_BASE_URL}")
    sid = place_call(phone, "Test Candidate")
    print(f"Call placed. SID: {sid}")
    print("Watch Terminal 2 (uvicorn) for WebSocket events...")
