# The five surfaces, and which one to reach for

The engine is written once. Each surface below is a thin wrapper over it, and
the moment one starts holding logic of its own there are two versions of the
truth and one of them is wrong.

| # | Surface | How you reach it | Who it is for |
|---|---|---|---|
| 1 | **Library** | `import speaker_helper` | another program |
| 2 | **Command line** | `speaker-helper` (click) and `speaker-helper-argparse` | a human at a terminal |
| 3 | **HTTP API** | `speaker-helper serve`, or the container | a service, a colleague's stack |
| 4 | **MCP** | `speaker-helper-mcp`, or `/mcp` on the API | an agent |
| 5 | **Skill** | the `SKILL.md` beside this file | Claude, OpenCode |

## 1. Library

```python
import asyncio
from speaker_helper import Speaker, Settings, Segment

async def main():
    async with Speaker(Settings.from_mapping({"language": "fr"})) as spk:
        one = await spk.say("Bonjour.")                 # AudioResult
        async for chunk in spk.stream("Une réponse."):  # StreamChunk
            ...
        doc = await spk.narrate([Segment(text="Un."), Segment(text="Deux.")])
        open("post.vtt", "w").write(doc.to_vtt())

asyncio.run(main())
```

A bare install imports, reads a settings file, parses segments and writes
WebVTT — with no ONNX runtime and no torch anywhere. The model arrives with
`pip install 'speaker-helper[kokoro]'`.

## 2. Two command lines

Both, over the same handlers: `argparse` because it is in the standard library
and therefore always available, `click` because its sub-commands and types
carry the richer shapes without hand-rolling them. A handler cannot tell which
front door called it.

```bash
speaker-helper health
speaker-helper install-voice --engine kokoro
speaker-helper synth "Bonjour." -o hello.wav
speaker-helper synth --stream "A longer reply."
speaker-helper narrate post.json -o post.wav --read-math fr
speaker-helper voices
speaker-helper eval                     # measure, don't guess
speaker-helper route --condition online # which engine, and why, in numbers
```

## 3. HTTP API

```bash
speaker-helper serve --host 0.0.0.0 --port 8080
```

| Route | What it does |
|---|---|
| `GET /health` | liveness, plus whether the backend could actually run |
| `GET /voices` | the catalogue |
| `POST /synth` | text in, `audio/wav` out, duration and RTF in headers |
| `POST /synth/stream` | Server-Sent Events, one per sentence-sized chunk |
| `POST /narrate` | blocks in; audio **and cues** out, as JSON |
| `POST /clone` | a reference recording in, a voice id out |
| `POST /route` | the engine choice, with the numbers behind it |
| `GET /` | a dependency-free single-page GUI over all of the above |

`/narrate` answers JSON where `/synth` answers audio, and the asymmetry is
deliberate: the cues are the reason that route exists, and a caller who only
wanted sound already has `/synth`.

## 4. MCP

```bash
speaker-helper-mcp --host 127.0.0.1 --port 8080
```

No second implementation: `fastapi-mcp` republishes the routes above from
their own descriptions, so an agent calling `narrate` and a shell calling
`POST /narrate` reach the same function.

This surface was removed in 0.7.5 and brought back. `fastapi-mcp` 0.4.0 called
the `mcp` SDK with an argument count it no longer accepted, and the mount was
guarded by `except ImportError` alone — so a `TypeError` escaped `create_app()`
and broke every API test, not only the MCP ones. The pairing is pinned in the
`mcp` extra now, and the mount catches more than `ImportError`: an optional
surface must never be able to take the HTTP API down.

## 5. Skill

`skills/speaker-helper/SKILL.md`, read by Claude and OpenCode alike.

## And the container

```bash
docker compose up -d
```

One service. This used to be two — a thin client here, the engine somewhere
else — and most of the configuration existed to find the other one. The
weights are fetched at **build** time, because an image that downloads 340 MB
on its first request is an image whose first request times out, and in a
scaled deployment every replica downloads it again.
