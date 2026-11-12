"""Fish Audio's speech synthesis endpoint, whoever's key a request runs on: the
deployer's or the user's own (ADR-0017)."""

FISH_TTS_HTTP_URL = "https://api.fish.audio/v1/tts"
"""Where text is voiced: one request per block of speech, the voice by its `reference_id`."""