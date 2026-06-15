"""Voice layer (Phase 4) — streaming TTS + the voice-turn orchestration helpers.

The brain is untouched: voice is an I/O shell. `tts.synthesize` turns a chunk of
text into audio bytes; `chunker.SentenceChunker` slices the token stream into
speakable sentences so TTS starts on the first sentence, not the whole turn.
The voice-turn generator itself lives in `app.agent.runner.voice_turn`,
alongside `stream_turn`, so it reuses the same envelope/interrupt plumbing.
"""
