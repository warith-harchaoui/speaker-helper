"""
Targets: what a word *should* sound like, and where that knowledge comes from.

Module summary
--------------
The loop can only correct a pronunciation against a reference. This module
finds that reference, in decreasing order of trust:

1. **The human** — the lexicon entry's own ``ipa:``. Final.
2. **Wiktionary** — the French and English editions carry IPA for a great
   many proper nouns, foreign words and initialisms
   (``{{pron|ɛs.kil|fr}}``, ``{{IPA|en|/ˈfaɪnmən/}}``), and they list every
   accepted variant.
3. **Wikipedia** — the lead sentence of an article about a person or place
   usually gives the name's IPA (``{{IPAc-en|ˈ|f|aɪ|n|m|ə|n}}``,
   ``{{API|…}}``); trusted only when the article's title ends with the word.
4. **espeak-ng** reading the current respelling — a *weak* target: it checks
   that the engine reads the respelling the way it was designed to be read,
   not that the respelling was right in the first place. Reported as such.

Web lookups go through one keep-alive client, paced with a random pause
between requests, backed off with full jitter on 429 / 503, with an honest
User-Agent; every answer, found or not, is cached on disk
(``~/.cache/speaker-helper/eardrum/targets.yaml``) so a word is looked up once
per machine, ever.

Usage example
-------------
>>> wiktionary_ipas("{{pron|e.ʃil|ɛs.kil|fr}}", "fr")
[('e.ʃil', 'fr'), ('ɛs.kil', 'fr')]

Author
------
Warith HARCHAOUI — https://linkedin.com/in/warith-harchaoui
"""

from __future__ import annotations

import datetime as _dt
import json
import random
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import os_helper as osh
import yaml

from speaker_helper import __version__

#: Where looked-up targets persist, one file per machine.
TARGET_CACHE: Path = Path.home() / ".cache" / "speaker-helper" / "eardrum" / "targets.yaml"

#: Honest identification, as the Wikimedia API policy asks.
USER_AGENT = (
    f"speaker-helper-eardrum/{__version__} "
    "(https://github.com/warith-harchaoui/speaker-helper; warithmetics@deraison.ai)"
)

#: Trust order of the sources, most trusted first. Used to sort candidates
#: and printed in reports.
SOURCES = ("lexicon", "wiktionary", "wikipedia", "espeak")


@dataclass
class Target:
    """The pronunciation a word should have, with its provenance.

    Attributes
    ----------
    variants : list of str
        Accepted IPA transcriptions (any of them is a correct reading).
    language : str
        Language the transcription is written for (``"en"`` for an English
        name read by a French voice: the target is then the original).
    source : str
        One of :data:`SOURCES`.
    url : str
        Where it was read, for the report (empty for the lexicon / espeak).
    weak : bool
        ``True`` when the target only restates the current respelling
        (espeak), so a perfect score proves consistency, not correctness.
    """

    variants: list[str]
    language: str
    source: str
    url: str = ""
    weak: bool = False


# ---------------------------------------------------------------------------
# Wikitext parsing (pure, tested without a network)
# ---------------------------------------------------------------------------

#: ``{{pron|…|fr}}`` on fr.wiktionary: transcriptions, then the language code.
_FR_PRON = re.compile(r"\{\{\s*(?:pron|phon|phono)\s*\|([^{}]*)\}\}")
#: ``{{IPA|en|/…/|/…/}}`` on en.wiktionary: the language code, then transcriptions.
_EN_IPA = re.compile(r"\{\{\s*IPA\s*\|([^{}]*)\}\}")
#: ``{{IPAc-en|ˈ|f|aɪ|…}}`` on en.wikipedia: one phoneme group per parameter.
_IPAC = re.compile(r"\{\{\s*IPAc-([a-z]{2,3})\s*\|([^{}]*)\}\}")
#: ``{{API|…}}`` on fr.wikipedia and the legacy ``{{IPA-fr|…}}`` elsewhere.
_WP_IPA = re.compile(r"\{\{\s*(?:API|IPA-([a-z]{2,3}))\s*\|([^{}|]*)")


def _looks_like_ipa(text: str) -> bool:
    """Whether a template parameter is a transcription rather than a label.

    Parameters
    ----------
    text : str
        One template parameter.

    Returns
    -------
    bool
        ``False`` for named parameters (``a=…``), labels (``UK``, ``US``,
        ``local``) and empty strings.

    Examples
    --------
    >>> _looks_like_ipa("ˈfaɪnmən"), _looks_like_ipa("US"), _looks_like_ipa("lang=fr")
    (True, False, False)
    """
    stripped = text.strip().strip("/[]")
    if not stripped or "=" in stripped:
        return False
    # Labels are written in capitals or as plain English words; a
    # transcription carries at least one non-ASCII IPA letter or is all
    # lowercase ASCII phonemes (rare but valid: "kat").
    if any(ch.isupper() for ch in stripped):
        return False
    return stripped not in {"local", "also", "pron", "lang", "audio", "we"}


def wiktionary_ipas(wikitext: str, edition: str) -> list[tuple[str, str]]:
    """Every IPA transcription in a Wiktionary page, with its language.

    Parameters
    ----------
    wikitext : str
        The page's wikitext.
    edition : str
        ``"fr"`` or ``"en"`` — the two editions use different templates.

    Returns
    -------
    list of (str, str)
        ``(ipa, language)`` pairs in page order, duplicates removed.

    Examples
    --------
    >>> wiktionary_ipas("{{IPA|en|/ˈfaɪnmən/|/ˈfeɪnmən/}}", "en")
    [('ˈfaɪnmən', 'en'), ('ˈfeɪnmən', 'en')]
    """
    found: list[tuple[str, str]] = []
    if edition == "fr":
        for match in _FR_PRON.finditer(wikitext):
            params = [p.strip() for p in match.group(1).split("|")]
            # The last positional parameter is the language code; named ones
            # (lang=fr) are accepted too.
            language = next((p.split("=", 1)[1] for p in params if p.startswith("lang=")), "")
            positional = [p for p in params if "=" not in p]
            if not language and positional and re.fullmatch(r"[a-z]{2,3}", positional[-1]):
                language = positional.pop()
            found += [(p.strip("/[]"), language) for p in positional if _looks_like_ipa(p)]
    else:
        for match in _EN_IPA.finditer(wikitext):
            params = [p.strip() for p in match.group(1).split("|")]
            if not params:
                continue
            language, rest = params[0], params[1:]
            found += [(p.strip("/[]"), language) for p in rest if _looks_like_ipa(p)]
    unique: list[tuple[str, str]] = []
    for pair in found:
        if pair[0] and pair not in unique:
            unique.append(pair)
    return unique


def wikipedia_lead_ipas(wikitext: str, edition: str) -> list[tuple[str, str]]:
    """IPA transcriptions in the lead of a Wikipedia article.

    Only the first few thousand characters are read: pronunciations further
    down are of other names (relatives, places, works).

    Parameters
    ----------
    wikitext : str
        The article's wikitext.
    edition : str
        The Wikipedia edition (``"fr"``, ``"en"``), the language assumed for
        ``{{API|…}}``.

    Returns
    -------
    list of (str, str)
        ``(ipa, language)`` pairs, duplicates removed.

    Examples
    --------
    >>> wikipedia_lead_ipas("'''Feynman''' ({{IPAc-en|ˈ|f|aɪ|n|m|ə|n}})", "en")
    [('ˈfaɪnmən', 'en')]
    """
    lead = wikitext[:4000]
    found: list[tuple[str, str]] = []
    for match in _IPAC.finditer(lead):
        language = match.group(1)
        pieces = [p.strip() for p in match.group(2).split("|")]
        # IPAc pieces are phoneme groups; labels and named parameters are
        # skipped, and a lone space-like piece marks a word boundary.
        ipa = "".join(
            " " if p in ("_", "") else p
            for p in pieces
            if "=" not in p and p not in {"US", "UK", "local", "lang", "audio", "pron", "also"}
        )  # noqa: E501
        if ipa.strip():
            found.append((" ".join(ipa.split()), language))
    for match in _WP_IPA.finditer(lead):
        language = match.group(1) or edition
        ipa = match.group(2).strip().strip("/[]")
        if _looks_like_ipa(ipa):
            found.append((ipa, language))
    unique: list[tuple[str, str]] = []
    for pair in found:
        if pair not in unique:
            unique.append(pair)
    return unique


def expand_optional(ipa: str) -> list[str]:
    """Spell out the optional sounds a transcription marks in parentheses.

    Wiktionary writes ``k(j)uːbəˈnɛtɪs``: the /j/ may or may not be said.
    Dropping the parentheses would make it mandatory; both readings are
    accepted instead.

    Parameters
    ----------
    ipa : str
        A transcription, possibly with ``(…)`` groups.

    Returns
    -------
    list of str
        Every combination, the fullest first (at most 8, for safety).

    Examples
    --------
    >>> expand_optional("k(j)uːb")
    ['kjuːb', 'kuːb']
    >>> expand_optional("ɡʁas")
    ['ɡʁas']
    """
    match = re.search(r"\(([^()]*)\)", ipa)
    if match is None:
        return [ipa]
    head, tail = ipa[: match.start()], ipa[match.end() :]
    out = expand_optional(head + match.group(1) + tail) + expand_optional(head + tail)
    return list(dict.fromkeys(out))[:8]


def pick_for_word(ipa: str, word: str, title: str) -> str:
    """The part of a full-name transcription that belongs to ``word``.

    A Wikipedia lead transcribes the article's title ("Richard Feynman"),
    sometimes only its unusual part (the surname). This returns the chunk
    for ``word`` when the chunk count and the title's word count agree, the
    whole thing when it is a single chunk and ``word`` ends the title, and
    nothing otherwise — a guess is worse than no target.

    Parameters
    ----------
    ipa : str
        The transcription, chunks separated by spaces.
    word : str
        The word (or phrase) being looked up.
    title : str
        The article's title.

    Returns
    -------
    str
        The chunk(s) for ``word``, or ``""``.

    Examples
    --------
    >>> pick_for_word("ˈrɪtʃərd ˈfaɪnmən", "Feynman", "Richard Feynman")
    'ˈfaɪnmən'
    >>> pick_for_word("ˈfaɪnmən", "Feynman", "Richard Feynman")
    'ˈfaɪnmən'
    >>> pick_for_word("ˈfaɪnmən", "Richard", "Richard Feynman")
    ''
    """
    chunks = ipa.split()
    title_words = [w.casefold() for w in re.split(r"[\s_]+", re.sub(r"\(.*?\)", "", title)) if w]
    word_words = [w.casefold() for w in word.split()]
    if not chunks or not title_words:
        return ""
    if len(chunks) == len(title_words):
        # Find the word's position inside the title and take the same chunks.
        n = len(word_words)
        for start in range(len(title_words) - n + 1):
            if title_words[start : start + n] == word_words:
                return " ".join(chunks[start : start + n])
        return ""
    if len(chunks) == len(word_words) and title_words[-len(word_words) :] == word_words:
        return " ".join(chunks)
    return ""


# ---------------------------------------------------------------------------
# The paced web client
# ---------------------------------------------------------------------------


class PoliteClient:
    """One keep-alive-minded HTTP client that never hammers a server.

    Parameters
    ----------
    min_gap, max_gap : float
        Bounds of the random pause before every request, in seconds.
    attempts : int
        How many times a refused request (429, 503, timeout) is tried in all.
    base, cap : float
        Exponential backoff parameters: the wait before retry ``k`` is
        uniform in ``[0, min(cap, base * 2**k)]``, never below a server's
        ``Retry-After``.
    sleep : callable
        Injected for tests; ``time.sleep`` in real use.
    """

    def __init__(
        self,
        *,
        min_gap: float = 0.3,
        max_gap: float = 1.5,
        attempts: int = 4,
        base: float = 5.0,
        cap: float = 300.0,
        sleep: Any = time.sleep,
    ) -> None:
        """Store the pacing parameters; no connection is opened yet.

        Parameters
        ----------
        min_gap, max_gap, attempts, base, cap, sleep
            See the class docstring.
        """
        self.min_gap, self.max_gap = min_gap, max_gap
        self.attempts, self.base, self.cap = attempts, base, cap
        self._sleep = sleep
        self._last: float = 0.0
        # Once a host refused us past the retries, stop asking it this run.
        self.refused_hosts: set[str] = set()

    def get_json(self, url: str, params: dict[str, Any]) -> dict[str, Any] | None:
        """GET ``url`` with ``params`` and decode the JSON answer.

        Parameters
        ----------
        url : str
            Endpoint (``https://fr.wiktionary.org/w/api.php``).
        params : dict
            Query parameters.

        Returns
        -------
        dict or None
            The decoded body, or ``None`` when the server refused us after
            every retry or the network is down (logged, never raised: a
            missing target degrades the loop, it does not stop it).
        """
        host = urllib.parse.urlparse(url).netloc
        if host in self.refused_hosts:
            return None
        full = f"{url}?{urllib.parse.urlencode(params)}"
        for attempt in range(self.attempts):
            # A random pause before every request, never a fixed rhythm.
            elapsed = time.monotonic() - self._last
            gap = random.uniform(self.min_gap, self.max_gap)
            if elapsed < gap:
                self._sleep(gap - elapsed)
            self._last = time.monotonic()
            request = urllib.request.Request(full, headers={"User-Agent": USER_AGENT})
            retry_after = 0.0
            try:
                with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                if exc.code not in (429, 503):
                    osh.warning("eardrum: %s answered %s for %s", host, exc.code, full)
                    return None
                retry_after = float(exc.headers.get("Retry-After") or 0)
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                osh.warning("eardrum: %s unreachable (%s)", host, exc)
            # Full jitter, with the server's Retry-After as a floor.
            wait = max(retry_after, random.uniform(0, min(self.cap, self.base * 2**attempt)))
            osh.info("eardrum: %s refused, waiting %.1fs before retrying", host, wait)
            self._sleep(wait)
        self.refused_hosts.add(host)
        osh.warning("eardrum: %s kept refusing; no more requests to it this run", host)
        return None


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------


def _wikitext(client: PoliteClient, host: str, page: str) -> tuple[str, str]:
    """Fetch one page's wikitext through the MediaWiki API.

    Parameters
    ----------
    client : PoliteClient
        The paced client.
    host : str
        ``fr.wiktionary.org``, ``en.wikipedia.org``…
    page : str
        Page title (redirects are followed).

    Returns
    -------
    tuple of (str, str)
        The wikitext and the resolved title, or ``("", "")`` when the page
        does not exist.
    """
    data = client.get_json(
        f"https://{host}/w/api.php",
        {
            "action": "parse",
            "page": page,
            "prop": "wikitext",
            "redirects": 1,
            "format": "json",
            "formatversion": 2,
        },
    )
    parse = (data or {}).get("parse") or {}
    return str(parse.get("wikitext") or ""), str(parse.get("title") or "")


def lookup_web(word: str, language: str, client: PoliteClient) -> list[tuple[str, str, str, str]]:
    """Look ``word`` up on Wiktionary, then Wikipedia.

    Wiktionary is asked in the text's language first (a French page may give
    the French way of saying a foreign name), then in English. Wikipedia is
    only asked when Wiktionary had nothing.

    Parameters
    ----------
    word : str
        The word or phrase.
    language : str
        ISO-639-1 code of the text being spoken.
    client : PoliteClient
        The paced client.

    Returns
    -------
    list of (ipa, language, source, url)
        Every transcription found, best source first.
    """
    editions = [language] + [e for e in ("fr", "en") if e != language]
    editions = [e for e in editions if e in ("fr", "en")]
    found: list[tuple[str, str, str, str]] = []
    for edition in editions:
        host = f"{edition}.wiktionary.org"
        # Wiktionary titles are case-sensitive: a proper noun lives under its
        # capital, a common word under lowercase.
        for page in dict.fromkeys([word, word.lower()]):
            text, title = _wikitext(client, host, page)
            if not text:
                continue
            url = f"https://{host}/wiki/{urllib.parse.quote(title.replace(' ', '_'))}"
            found += [
                (ipa, lang, "wiktionary", url) for ipa, lang in wiktionary_ipas(text, edition)
            ]
            break
    if found:
        return found
    for edition in editions:
        host = f"{edition}.wikipedia.org"
        text, title = _wikitext(client, host, word)
        if not text:
            continue
        url = f"https://{host}/wiki/{urllib.parse.quote(title.replace(' ', '_'))}"
        for ipa, lang in wikipedia_lead_ipas(text, edition):
            chunk = pick_for_word(ipa, word, title)
            if chunk:
                found.append((chunk, lang, "wikipedia", url))
        if found:
            break
    return found


class TargetResolver:
    """Find and cache the target pronunciation of words.

    Parameters
    ----------
    cache_path : Path
        The on-disk cache of web lookups (:data:`TARGET_CACHE` by default).
    web : bool
        Allow web lookups. Off means: the lexicon's IPA, else espeak.
    client : PoliteClient or None
        Injected for tests; a fresh paced client otherwise.
    """

    def __init__(
        self,
        cache_path: Path = TARGET_CACHE,
        *,
        web: bool = True,
        client: PoliteClient | None = None,
    ) -> None:
        """Open (but do not yet read) the cache.

        Parameters
        ----------
        cache_path, web, client
            See the class docstring.
        """
        self.cache_path = cache_path
        self.web = web
        self.client = client or PoliteClient()
        self._cache: dict[str, Any] | None = None

    def _load(self) -> dict[str, Any]:
        """Read the cache once, tolerating a missing or corrupt file.

        Returns
        -------
        dict
            ``"lang:word"`` → list of ``[ipa, language, source, url]``.
        """
        if self._cache is None:
            self._cache = {}
            if self.cache_path.exists():
                try:
                    self._cache = yaml.safe_load(self.cache_path.read_text(encoding="utf-8")) or {}
                except Exception as exc:  # noqa: BLE001 - a cache must never break the loop
                    osh.warning("eardrum: unreadable target cache %s (%s)", self.cache_path, exc)
        return self._cache

    def _save(self) -> None:
        """Write the cache back (best effort)."""
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(
                "# Pronunciations looked up by the Ralph Eardrum Loop, one per\n"
                '# "language:word"; an empty list is a lookup that found nothing.\n'
                "# Delete a line to look the word up again.\n"
                + yaml.safe_dump(self._load(), allow_unicode=True, sort_keys=True),
                encoding="utf-8",
            )
        except OSError as exc:
            osh.warning("eardrum: could not write target cache %s (%s)", self.cache_path, exc)

    def web_candidates(self, word: str, language: str) -> list[tuple[str, str, str, str]]:
        """Web transcriptions of ``word``, from the cache or a fresh lookup.

        Parameters
        ----------
        word : str
            The word or phrase.
        language : str
            Language of the text.

        Returns
        -------
        list of (ipa, language, source, url)
            Possibly empty.
        """
        cache = self._load()
        key = f"{language}:{word.casefold()}"
        if key in cache:
            return [tuple(row) for row in cache[key]]  # type: ignore[misc]
        if not self.web:
            return []
        found = lookup_web(word, language, self.client)
        # Only cache an answer when every host answered: a refusal is not
        # "this word has no IPA", and must be retried another day.
        if not self.client.refused_hosts:
            cache[key] = [list(row) for row in found]
            cache[f"_{key}_looked_up"] = _dt.date.today().isoformat()
            self._save()
        return found

    def resolve(
        self,
        word: str,
        language: str,
        *,
        ipa: str = "",
        respelling: str = "",
        espeak: Any = None,
    ) -> Target | None:
        """The target pronunciation of ``word``, most trusted source first.

        Parameters
        ----------
        word : str
            The word or phrase.
        language : str
            Language of the text it is spoken in.
        ipa : str
            The lexicon entry's own IPA, if any — final when present.
        respelling : str
            The current respelling, for the weak espeak fallback.
        espeak : callable or None
            ``(text, language) -> ipa``; :func:`speaker_helper.eardrum.espeak.espeak_ipa`
            in real use.

        Returns
        -------
        Target or None
            ``None`` only when nothing at all is known (no IPA, no web
            answer, no respelling, no espeak).
        """
        if ipa:
            return Target(variants=[ipa], language=language, source="lexicon")
        found = self.web_candidates(word, language)
        if found:
            # Prefer transcriptions written for the text's own language (a
            # French reading of a name, when Wiktionary gives one); otherwise
            # keep the original language's ones, all variants of it.
            same = [row for row in found if row[1] == language]
            rows = same or [row for row in found if row[1] == found[0][1]]
            return Target(
                variants=list(dict.fromkeys(v for row in rows for v in expand_optional(row[0]))),
                language=rows[0][1],
                source=rows[0][2],
                url=rows[0][3],
            )
        if espeak is not None and respelling:
            return Target(
                variants=[espeak(respelling, language)],
                language=language,
                source="espeak",
                weak=True,
            )
        return None


def target_as_dict(target: Target | None) -> dict[str, Any] | None:
    """A JSON-ready view of a target, for the report.

    Parameters
    ----------
    target : Target or None
        The target.

    Returns
    -------
    dict or None
        ``asdict(target)``, or ``None``.
    """
    return asdict(target) if target is not None else None
