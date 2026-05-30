from interview.providers.base import CallProvider
import config

_provider: CallProvider | None = None


def get_provider() -> CallProvider:
    global _provider
    if _provider is None:
        if config.CALL_PROVIDER == "plivo":
            from interview.providers.plivo_provider import PlivoProvider
            _provider = PlivoProvider()
        else:
            from interview.providers.twilio_provider import TwilioProvider
            _provider = TwilioProvider()
    return _provider
