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
    }
    return call_sid
