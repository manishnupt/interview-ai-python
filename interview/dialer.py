import threading
from interview.providers import get_provider


def place_call(
    to_phone: str,
    candidate_name: str,
    resume_text: str = "",
    job_description: str = "",
    candidate_id: int = None,
) -> str:
    from interview import call_manager
    call_sid = get_provider().place_call(to_phone, candidate_name)
    call_manager.active_call_data[call_sid] = {
        "resume_text": resume_text,
        "job_description": job_description,
        "candidate_id": candidate_id,
        "opening_audio": None,
    }

    def _prefetch_opening():
        from interview.voice import VoiceSynthesiser
        synth = VoiceSynthesiser()
        opening_text = f"Hello, am I speaking with {candidate_name}?"
        audio = synth.text_to_mulaw(opening_text)
        call_manager.active_call_data[call_sid]["opening_audio"] = audio
        print(f"[Dialer] Opening audio pre-cached for {call_sid}")

    threading.Thread(target=_prefetch_opening, daemon=True).start()
    return call_sid
