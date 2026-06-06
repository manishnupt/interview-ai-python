## Platform API (Sprint 13)
A new file platform_api.py exposes the Python AI pipeline
as HTTP endpoints so Spring Boot can call it.

Endpoints:
  POST /screen     → runs resume screener, returns JSON result
  POST /interview  → places outbound call, returns call_sid immediately
  POST /health     → health check

The existing main.py, screener.py, call_manager.py etc
are NOT modified. platform_api.py imports and wraps them.

Spring Boot calls these endpoints via WebClient.
After an interview completes, Python calls Spring Boot back at:
  POST {SPRING_BOOT_URL}/api/callbacks/interview-complete

New env vars needed:
  SPRING_BOOT_URL=http://localhost:8080
  PLATFORM_API_PORT=8001  ← different port from call_manager (8000)
