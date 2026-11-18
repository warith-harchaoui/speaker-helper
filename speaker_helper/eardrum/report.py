"""
The report: every take, side by side, for the ear that has the last word.

Module summary
--------------
The loop's scores point; they do not decide. The report puts, for every word,
the target pronunciation, each attempt with its score and what the recogniser
heard, and the audio — the whole carrier sentence and the word cut out of it —
so whoever owns the voice can listen and overrule. Three files:

* ``index.html`` — self-contained, plays the clips in place;
* ``report.json`` — the same, for scripts;
* ``report.md`` — a summary table for a terminal or a commit message.

Usage example
-------------
>>> verdict_label("fixed")
'corrigé'

Author
------
Warith HARCHAOUI — https://linkedin.com/in/warith-harchaoui
"""

from __future__ import annotations

import html
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from speaker_helper.eardrum.loop import WordResult

#: Verdicts as the report prints them (the report is read in French first).
_VERDICTS = {
    "ok": "déjà juste",
    "fixed": "corrigé",
    "improved": "amélioré",
    "proposal": "proposition",
    "unresolved": "non résolu",
    "no-target": "sans cible",
}


#: Reasons, origins and sources, as the report prints them.
_LABELS = {
    "asked": "demandé",
    "lexicon": "lexique",
    "proper": "nom propre",
    "acronym": "sigle",
    "mixed": "casse mixte",
    "foreign": "étranger",
    "heard": "entendu faux",
    "current": "actuelle",
    "written": "tel qu'écrit",
    "llm": "LLM",
    "target": "cible",
    "user": "écrite à la main",
    "builtin": "livrée",
    "eardrum": "eardrum",
    "new": "absent du lexique",
    "wiktionary": "Wiktionnaire",
    "wikipedia": "Wikipédia",
    "espeak": "espeak",
}


def label(code: str) -> str:
    """The French label of a reason, origin or source code.

    Parameters
    ----------
    code : str
        A code from the loop (``"proper"``, ``"written"``, ``"builtin"``…).

    Returns
    -------
    str
        Its label, or the code itself when unknown.

    Examples
    --------
    >>> label("proper"), label("zzz")
    ('nom propre', 'zzz')
    """
    return _LABELS.get(code, code)


def verdict_label(verdict: str) -> str:
    """The human label of a verdict.

    Parameters
    ----------
    verdict : str
        A :class:`~.loop.WordResult` verdict.

    Returns
    -------
    str
        The French label, or the verdict itself when unknown.
    """
    return _VERDICTS.get(verdict, verdict)


def _audio(path: str) -> str:
    """An inline audio player for a relative path (empty when no path).

    Parameters
    ----------
    path : str
        Path relative to the report directory.

    Returns
    -------
    str
        HTML.
    """
    if not path:
        return ""
    return f'<audio controls preload="none" src="{html.escape(path)}"></audio>'


def render_html(results: list[WordResult], meta: dict[str, Any]) -> str:
    """The self-contained HTML report.

    Parameters
    ----------
    results : list of WordResult
        One per word.
    meta : dict
        ``engine``, ``language``, ``threshold``, ``date``, ``saved_to``.

    Returns
    -------
    str
        A complete HTML document.
    """
    rows = []
    for r in results:
        target = r.target or {}
        variants = " | ".join(target.get("variants") or [])
        source = target.get("source", "")
        url = target.get("url", "")
        source_html = (
            f'<a href="{html.escape(url)}">{html.escape(source)}</a>'
            if url
            else html.escape(source)
        )
        weak = " (faible)" if target.get("weak") else ""
        attempts = []
        for i, a in enumerate(r.attempts):
            takes = "".join(
                f"<li><div class='heard'><span class='mono'>/{html.escape(t.heard)}/</span> "
                f"<span class='score'>{t.score:.2f}</span></div>"
                f"<div class='player'><span class='lbl'>mot</span>{_audio(t.clip)}</div>"
                f"<div class='player'><span class='lbl'>phrase</span>{_audio(t.audio)}</div></li>"
                for t in a.takes
            )
            best = " best" if i == r.best else ""
            attempts.append(
                f"<div class='attempt{best}'><div class='cand'>"
                f"<b>{html.escape(a.candidate)}</b> "
                f"<span class='origin'>{html.escape(label(a.origin))}</span> "
                f"<span class='score'>{a.score:.2f}</span></div><ul>{takes}</ul></div>"
            )
        rows.append(
            f"<section class='word v-{html.escape(r.verdict)}'>"
            f"<h2>{html.escape(r.word)} <span class='verdict'>{verdict_label(r.verdict)}</span>"
            f"{' <span class=saved>enregistré</span>' if r.saved else ''}</h2>"
            f"<p class='meta'>cible <span class='mono'>/{html.escape(variants)}/</span> "
            f"— {source_html}{weak} · raisons : {html.escape(', '.join(map(label, r.reasons)))} "
            f"· graphie : {html.escape(label(r.source))}</p>"
            f"<p class='note'>{html.escape(r.note)}</p>{''.join(attempts)}</section>"
        )
    counts: dict[str, int] = {}
    for r in results:
        counts[r.verdict] = counts.get(r.verdict, 0) + 1
    summary = " · ".join(f"{verdict_label(k)} : {v}" for k, v in sorted(counts.items()))
    return f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Ralph Eardrum Loop</title>
<style>
:root {{ --bg:#fbfbfd; --fg:#1d1d1f; --muted:#6e6e73; --card:#fff; --line:#d2d2d7;
  --ok:#248a3d; --fix:#0071e3; --warn:#b25000; --bad:#d70015; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#000; --fg:#f5f5f7; --muted:#a1a1a6;
  --card:#1c1c1e; --line:#38383a; --ok:#30d158; --fix:#0a84ff; --warn:#ff9f0a; --bad:#ff453a; }} }}
body {{ background:var(--bg); color:var(--fg); font:15px/1.5 -apple-system, "Roboto", sans-serif;
  margin:0 auto; max-width:960px; padding:24px 16px; }}
h1 {{ font-size:24px; margin:0 0 4px; }} .sub {{ color:var(--muted); margin:0 0 24px; }}
.word {{ background:var(--card); border:1px solid var(--line); border-radius:12px;
  padding:16px; margin:0 0 16px; border-left:6px solid var(--line); }}
.v-ok {{ border-left-color:var(--ok); }} .v-fixed {{ border-left-color:var(--fix); }}
.v-improved, .v-proposal {{ border-left-color:var(--warn); }}
.v-unresolved, .v-no-target {{ border-left-color:var(--bad); }}
h2 {{ font-size:19px; margin:0 0 6px; }} .verdict, .saved {{ font-size:12px; font-weight:600;
  padding:2px 8px; border-radius:99px; border:1px solid var(--line); vertical-align:middle; }}
.meta, .note {{ color:var(--muted); margin:4px 0; }}
.mono {{ font-family:"Roboto Mono", ui-monospace, monospace; }}
.attempt {{ border-top:1px solid var(--line); padding:8px 0; }}
.attempt.best .cand b {{ color:var(--fix); }}
.origin {{ color:var(--muted); font-size:12px; }}
.score {{ font-variant-numeric:tabular-nums; font-weight:600; }}
.lbl {{ color:var(--muted); font-size:12px; }}
ul {{ list-style:none; padding:0; margin:4px 0; }}
li {{ margin:6px 0; display:grid; grid-template-columns:minmax(150px, 1fr) 2fr 2fr;
  align-items:center; gap:8px; }}
.player {{ display:flex; align-items:center; gap:6px; min-width:0; }}
.lbl {{ width:44px; flex:none; }}
audio {{ height:32px; width:100%; min-width:0; }}
@media (max-width: 640px) {{ li {{ grid-template-columns:1fr; }} }}
</style></head><body>
<h1>Ralph Eardrum Loop</h1>
<p class="sub">moteur <b>{html.escape(str(meta.get("engine")))}</b>
· langue {html.escape(str(meta.get("language")))} · seuil {meta.get("threshold")}
· {html.escape(str(meta.get("date")))}
<br>{html.escape(summary)}<br>score = distance phonétique du mot entendu à la cible
(0 = parfait).
Les chiffres orientent ; l'oreille tranche.</p>
{"".join(rows)}
</body></html>
"""


def render_markdown(results: list[WordResult], meta: dict[str, Any]) -> str:
    """A summary table in Markdown.

    Parameters
    ----------
    results : list of WordResult
        One per word.
    meta : dict
        As for :func:`render_html`.

    Returns
    -------
    str
        Markdown.
    """
    lines = [
        f"# Ralph Eardrum Loop — {meta.get('engine')} / {meta.get('language')}",
        "",
        f"Seuil {meta.get('threshold')} · {meta.get('date')}",
        "",
        "| mot | verdict | cible | meilleure graphie | score | entendu |",
        "|---|---|---|---|---|---|",
    ]
    for r in results:
        target = r.target or {}
        best = r.attempts[r.best] if r.attempts and r.best >= 0 else None
        lines.append(
            f"| {r.word} | {verdict_label(r.verdict)}{' ✓' if r.saved else ''} "
            f"| /{' | '.join(target.get('variants') or [])}/ ({target.get('source', '—')}) "
            f"| {best.candidate if best else '—'} | {f'{best.score:.2f}' if best else '—'} "
            f"| /{best.takes[0].heard if best and best.takes else ''}/ |"
        )
    return "\n".join(lines) + "\n"


def write_report(out_dir: Path, results: list[WordResult], meta: dict[str, Any]) -> Path:
    """Write ``index.html``, ``report.json`` and ``report.md``.

    Parameters
    ----------
    out_dir : Path
        The run's directory (audio already inside).
    results : list of WordResult
        One per word.
    meta : dict
        Run metadata.

    Returns
    -------
    Path
        The HTML report's path.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.json").write_text(
        json.dumps(
            {"meta": meta, "words": [asdict(r) for r in results]}, ensure_ascii=False, indent=2
        ),
        encoding="utf-8",
    )
    (out_dir / "report.md").write_text(render_markdown(results, meta), encoding="utf-8")
    index = out_dir / "index.html"
    index.write_text(render_html(results, meta), encoding="utf-8")
    return index
