"""
Quickstart — offline and streaming synthesis with speaker-helper.

Run it against a live Voicebox engine::

    SPEAKER_HELPER_VOICEBOX_PORT=17600 python examples/quickstart.py

Author
------
Warith HARCHAOUI — https://linkedin.com/in/warith-harchaoui
"""

from __future__ import annotations

import asyncio

from speaker_helper import Settings, Speaker


async def main() -> None:
    """Synthesise one line offline, then a paragraph in streaming mode."""
    settings = Settings.load()  # reads settings.yaml / SPEAKER_HELPER_* env vars

    async with Speaker(settings) as spk:
        # Offline: whole text -> one audio.
        result = await spk.say("Bonjour, ceci est speaker-helper.")
        with open("quickstart_offline.wav", "wb") as f:
            f.write(result.wav_bytes)
        print(f"offline: {result.duration_s:.2f}s audio, RTF {result.rtf:.2f}")

        # Streaming: sentence-split, low time-to-first-audio.
        text = "Premier segment. Deuxième segment. Et voici le troisième."
        async for chunk in spk.stream(text):
            if chunk.ttfa_s is not None:
                print(f"time to first audio: {chunk.ttfa_s:.2f}s")
            print(f"  chunk {chunk.seq}: {chunk.audio.duration_s:.2f}s")


if __name__ == "__main__":
    asyncio.run(main())
