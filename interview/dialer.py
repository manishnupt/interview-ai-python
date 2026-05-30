from interview.providers import get_provider


def place_call(to_phone: str, candidate_name: str) -> str:
    return get_provider().place_call(to_phone, candidate_name)
