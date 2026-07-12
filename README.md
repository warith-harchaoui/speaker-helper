# speaker-helper

**Professional text-to-speech — offline and streaming — over a local
[Voicebox](https://github.com/jamiepine/voicebox) engine.**

speaker-helper is the inverse of
[`vocal-helper`](https://github.com/warith-harchaoui): where vocal-helper turns
*speech into text*, speaker-helper turns **text into speech**. It gives you a
small, typed Python API, a CLI, and a REST API — runnable locally (conda + pip)
or as a Docker server.

- **Two modes.** *Offline* (whole text → one audio) and *streaming*
  (sentence-split, low time-to-first-audio).
- **Real-time on CPU.** The default `kokoro` engine synthesises faster than
  real time (real-time factor well below 1.0) — no GPU required.
- **Batteries included.** Library, CLI, REST API, Docker.

See [`EXAMPLES.md`](EXAMPLES.md) for a runnable cookbook, and
[`LISEZMOI.md`](LISEZMOI.md) for the French version.

---

## How it fits together

```
your text ──▶ speaker-helper ──HTTP──▶ Voicebox engine ──▶ WAV audio
             (API / CLI / server)      (kokoro, …)
```

speaker-helper is a **client** of a Voicebox engine. Start Voicebox once, then
point speaker-helper at it.

---

## Install

### 1. System dependency: libsndfile

`soundfile` (used to measure and concatenate audio) needs the native
`libsndfile` library.

- macOS 🍎 : `brew install libsndfile`
  (install `brew` thanks to [brew.sh](https://brew.sh/))
- Ubuntu 🐧 : `sudo apt install libsndfile1`
- Windows 🪟 : bundled with the `soundfile` wheel — no separate install.

### 2. The package (conda + pip, local)

```bash
conda create -n speaker-helper python=3.11 -y
conda activate speaker-helper
pip install -e ".[server]"     # add ",dev" for the test/lint toolchain
```

### 3. A Voicebox engine

speaker-helper needs a running Voicebox. Either run Voicebox natively (MLX,
fastest on Apple Silicon — see the Voicebox repo) on its default port `17493`,
or with Docker on host port `17600`:

```bash
git clone https://github.com/jamiepine/voicebox && cd voicebox
docker compose up --build            # serves on 127.0.0.1:17600
```

Then tell speaker-helper where it is (`--port`, `settings.yaml`, or
`SPEAKER_HELPER_VOICEBOX_PORT`).

---

## Quickstart

### Python

```python
from speaker_helper import Speaker, Settings

spk = Speaker(Settings.from_mapping({
    "engine": "kokoro", "language": "fr", "voicebox": {"port": 17600},
}))
result = spk.save("Bonjour le monde.", "hello.wav")
print(f"{result.duration_s:.2f}s audio, RTF {result.rtf:.2f}")
# 2.80s audio, RTF 0.43
```

### CLI

```bash
speaker-helper --port 17600 voices --engine kokoro
speaker-helper --port 17600 synth "Bonjour le monde." -o hello.wav
speaker-helper --port 17600 synth "Une. Deux. Trois." -o out.wav --stream
```

### REST API server

```bash
speaker-helper --port 17600 serve --host 0.0.0.0 --port 8080
curl -s -X POST localhost:8080/synth -H 'content-type: application/json' \
     -d '{"text": "Bonjour."}' -o out.wav
```

Or with Docker (server points at a Voicebox on the host):

```bash
docker compose up --build            # speaker-helper API on :8080
```

---

## Configuration

Copy [`settings.yaml.example`](settings.yaml.example) to `settings.yaml` (it is
gitignored) or use [`speaker_config.json.example`](speaker_config.json.example)
as a reference. Every key can be overridden by a `SPEAKER_HELPER_*` environment
variable; `${VAR}` references inside the YAML are expanded from the environment.

---

## Development

```bash
pip install -e ".[dev,server]"
pytest -q -m "not slow"       # fast, deterministic suite (no engine needed)
pytest -q                     # also runs @slow live tests (needs Voicebox)
ruff check speaker_helper tests
```

CI runs the fast suite on Python 3.10–3.13; a failing test blocks merges.

---

## Acknowledgements

Special thanks to the contributors, reviewers, and users who helped improve
this project — and to the [Voicebox](https://github.com/jamiepine/voicebox)
authors for the engine speaker-helper builds on.

## License

BSD-3-Clause © Warith HARCHAOUI.
