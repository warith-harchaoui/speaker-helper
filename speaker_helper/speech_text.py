"""
What the voice says where the page shows notation.

A page and a narration are not the same text, and three things on a page have
no spoken form of their own:

* **Mathematics.** ``\\(R = T_{BA} \\circ T_{AB}\\)`` is a sentence a reader
  sees at a glance and a speech engine spells out as "backslash, open
  parenthesis, R equals T underscore...". Read aloud it has to become
  English, or French, or whatever the page is written in.
* **Footnote markers.** Handled by whoever walks the page, not here: telling
  a reference superscript from an exponent needs the markup, and this module
  is given a string. The rule that works is *by content* — a ``<sup>`` whose
  entire content is a number (bare, ``[1]``, ``(1)``) is a reference and goes
  unsaid. Its documented limit is that ``x<sup>2</sup>`` is taken for one.
* **Pronunciation overrides**, which belong to whoever assembles the segments.

The page's own text is never changed. This produces a *second* string, the
one handed to the engine, while the cue keeps the page's words — so a
read-along still highlights what the page shows, and the narration still
says something a person would say. That pair is
:class:`~speaker_helper.narration.Segment`'s ``text`` and ``say``, and this
module is how the second is usually derived from the first.

Why it lives in the voice package rather than beside a site generator: "what
does a voice say where the page shows notation" is a question about speech,
not about documents. It was written for a blog and is not specific to one —
it needs no model, no network and no optional extra, only the language the
text is written in.

Scope, stated plainly. This is not a LaTeX parser and does not try to be.
It covers the notation that appears in prose: relations, the common
operators and functions, Greek, subscripts, powers, roots and fractions.
Anything it does not know loses its backslash and is spoken as a word,
which is wrong far less often than spelling the command out.

Author
------
`Warith HARCHAOUI, Ph.D. <https://www.linkedin.com/in/warith-harchaoui/>`_
"""

from __future__ import annotations

import re

# ── Vocabulary, per language ───────────────────────────────────────────────
#
# Not a translation table with an English default: a French page read with
# English operator names is worse than one that says nothing, because the
# listener hears fluent words in the wrong language and assumes they
# misheard. A language with no table raises.

_SHARED: dict[str, str] = {
    # Greek, which is the same word in both languages often enough to share.
    r"\alpha": "alpha",
    r"\beta": "beta",
    r"\gamma": "gamma",
    r"\delta": "delta",
    r"\epsilon": "epsilon",
    r"\varepsilon": "epsilon",
    r"\zeta": "zeta",
    r"\eta": "eta",
    r"\theta": "theta",
    r"\iota": "iota",
    r"\kappa": "kappa",
    r"\lambda": "lambda",
    r"\mu": "mu",
    r"\nu": "nu",
    r"\xi": "xi",
    r"\pi": "pi",
    r"\rho": "rho",
    r"\sigma": "sigma",
    r"\tau": "tau",
    r"\upsilon": "upsilon",
    r"\phi": "phi",
    r"\varphi": "phi",
    r"\chi": "chi",
    r"\psi": "psi",
    r"\omega": "omega",
    r"\Gamma": "Gamma",
    r"\Delta": "Delta",
    r"\Theta": "Theta",
    r"\Lambda": "Lambda",
    r"\Xi": "Xi",
    r"\Pi": "Pi",
    r"\Sigma": "Sigma",
    r"\Phi": "Phi",
    r"\Psi": "Psi",
    r"\Omega": "Omega",
}

WORDS: dict[str, dict[str, str]] = {
    "en": {
        **_SHARED,
        "=": "equals",
        "+": "plus",
        "<": "is less than",
        ">": "is greater than",
        r"\neq": "is not equal to",
        r"\ne": "is not equal to",
        r"\approx": "is approximately",
        r"\sim": "is distributed as",
        r"\leq": "is at most",
        r"\le": "is at most",
        r"\geq": "is at least",
        r"\ge": "is at least",
        r"\pm": "plus or minus",
        r"\mp": "minus or plus",
        r"\times": "times",
        r"\cdot": "times",
        r"\div": "divided by",
        r"\circ": "composed with",
        r"\ast": "star",
        r"\to": "to",
        r"\rightarrow": "to",
        r"\mapsto": "maps to",
        r"\implies": "implies",
        r"\iff": "if and only if",
        r"\in": "in",
        r"\notin": "not in",
        r"\subset": "is contained in",
        r"\subseteq": "is contained in",
        r"\cup": "union",
        r"\cap": "intersection",
        r"\forall": "for all",
        r"\exists": "there exists",
        r"\sum": "the sum of",
        r"\prod": "the product of",
        r"\int": "the integral of",
        r"\infty": "infinity",
        r"\partial": "partial",
        r"\nabla": "gradient",
        r"\log": "log",
        r"\ln": "log",
        r"\exp": "the exponential of",
        r"\sin": "sine",
        r"\cos": "cosine",
        r"\tan": "tangent",
        r"\max": "the maximum of",
        r"\min": "the minimum of",
        r"\arg": "arg",
        r"\det": "the determinant of",
        "sqrt": "the square root of",
        "over": "over",
        "ratio": "the ratio of",
        "to": "to",
        "of": "of",
        "power": "to the power of",
        "squared": "squared",
        "cubed": "cubed",
        "minus": "minus",
        "times_implicit": "times",
        "given": "given",
        r"\mathbb{E}": "the expected value of",
        r"\mathbb{P}": "the probability of",
        r"\mathbb{V}": "the variance of",
        r"\operatorname{Var}": "the variance of",
        r"\mid": "given",
        "|": "given",
    },
    "fr": {
        **_SHARED,
        "=": "égale",
        "+": "plus",
        "<": "est inférieur à",
        ">": "est supérieur à",
        r"\neq": "est différent de",
        r"\ne": "est différent de",
        r"\approx": "vaut environ",
        r"\sim": "suit la loi",
        r"\leq": "est au plus",
        r"\le": "est au plus",
        r"\geq": "est au moins",
        r"\ge": "est au moins",
        r"\pm": "plus ou moins",
        r"\mp": "moins ou plus",
        r"\times": "fois",
        r"\cdot": "fois",
        r"\div": "divisé par",
        r"\circ": "composé avec",
        r"\ast": "étoile",
        r"\to": "vers",
        r"\rightarrow": "vers",
        r"\mapsto": "envoie sur",
        r"\implies": "implique",
        r"\iff": "si et seulement si",
        r"\in": "dans",
        r"\notin": "n'est pas dans",
        r"\subset": "est contenu dans",
        r"\subseteq": "est contenu dans",
        r"\cup": "union",
        r"\cap": "intersection",
        r"\forall": "pour tout",
        r"\exists": "il existe",
        r"\sum": "la somme des",
        r"\prod": "le produit des",
        r"\int": "l'intégrale de",
        r"\infty": "l'infini",
        r"\partial": "d rond",
        r"\nabla": "gradient",
        r"\log": "log",
        r"\ln": "log",
        r"\exp": "l'exponentielle de",
        r"\sin": "sinus",
        r"\cos": "cosinus",
        r"\tan": "tangente",
        r"\max": "le maximum de",
        r"\min": "le minimum de",
        r"\arg": "arg",
        r"\det": "le déterminant de",
        "sqrt": "la racine carrée de",
        "over": "sur",
        "ratio": "le rapport de",
        "to": "à",
        "of": "de",
        "power": "puissance",
        "squared": "au carré",
        "cubed": "au cube",
        "minus": "moins",
        "times_implicit": "fois",
        "given": "sachant",
        r"\mathbb{E}": "l'espérance de",
        r"\mathbb{P}": "la probabilité de",
        r"\mathbb{V}": "la variance de",
        r"\operatorname{Var}": "la variance de",
        r"\mid": "sachant",
        "|": "sachant",
    },
}

#: Spacing and sizing commands: invisible on the page, and nothing to say.
_DROPPED = re.compile(
    r"\\(?:left|right|big|Big|bigg|Bigg|displaystyle|textstyle|limits|,|;|:|!|\s|quad|qquad)"
)

#: `\mathbb{R}`, `\mathrm{d}`, `\text{if}` — the font is a page matter; the
#: letters inside are what is read.
_FONT = re.compile(r"\\(?:math(?:bf|cal|rm|sf|it|frak)|text(?:rm|bf|it)?)\s*\{([^{}]*)\}")

#: Operators written as a letter in a particular font -- `\mathbb{E}`, the
#: expectation -- which are *named things*, not styled letters. They have to
#: be recognised before `_FONT` strips the font away and leaves a bare "E".
_NAMED_OPERATOR = re.compile(r"\\(?:mathbb|operatorname)\s*\{\s*([A-Za-z]+)\s*\}")


class SpeechMismatch(ValueError):
    """Raised when a language has no vocabulary rather than serving English."""


def _words(lang: str) -> dict[str, str]:
    table = WORDS.get(lang)
    if table is None:
        raise SpeechMismatch(
            f"no spoken maths vocabulary for language {lang!r}; add it to "
            f"WORDS rather than reading a {lang} page with English operators"
        )
    return table


def _group(text: str, at: int) -> tuple[str, int]:
    """The brace group starting at ``at``, and where it ends.

    Returns the single character instead when there is no brace, because
    ``x_1`` and ``x_{1}`` are the same thing written two ways.
    """
    if at >= len(text):
        return "", at
    if text[at] != "{":
        return text[at], at + 1
    depth, i = 0, at
    while i < len(text):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[at + 1 : i], i + 1
        i += 1
    return text[at + 1 :], len(text)


def speak_math(latex: str, lang: str = "en") -> str:
    """One formula, as a person would read it out.

    ``R = T_{BA} \\circ T_{AB}`` becomes "R equals T B A composed with T A B".

    Subscripts are read as their own letters rather than announced: "T A B"
    is how somebody says that at a blackboard, and "T subscript A B" is how
    nobody does. Powers keep their announcement, because "x 2" and "x
    squared" are different claims.
    """
    words = _words(lang)
    # Each piece carries whether it came through verbatim from the source.
    # Consecutive verbatim characters are a name -- `T`, `A`, `B` were `TAB`
    # on the page and must not become three words -- while anything
    # translated is a word and takes a space. Joining on length alone looked
    # equivalent and was not: it glued the `1` of `n+1` onto "plus".
    out: list[tuple[str, bool]] = []
    i = 0
    text = _NAMED_OPERATOR.sub(lambda m: f"\\{m.group(1)}OP ", latex)
    text = _FONT.sub(r"\1", text)
    text = _DROPPED.sub(" ", text)

    while i < len(text):
        char = text[i]

        if char == "\\":
            match = re.match(r"\\[a-zA-Z]+", text[i:])
            if match is None:
                i += 1
                continue
            command = match.group(0)
            i += len(command)

            # A named operator -- the expectation, a probability, a variance
            # -- takes what follows as its argument and reads as a phrase:
            # "the expected value of theta given m", not "E, open bracket,
            # theta, mid, m, close bracket". This is the difference between
            # telling a formula and spelling it.
            if command.endswith("OP"):
                name = words.get(rf"\mathbb{{{command[1:-2]}}}")
                argument, i = _argument(text, i)
                if name:
                    out.append((f"{name} {speak_math(argument, lang)}", False))
                else:
                    out.append((f"{command[1:-2]} {speak_math(argument, lang)}", False))
                continue

            if command == r"\sqrt":
                body, i = _group(text, i)
                out.append((f"{words['sqrt']} {speak_math(body, lang)}", False))
            elif command == r"\frac":
                top, i = _group(text, i)
                bottom, i = _group(text, i)
                said_top = speak_math(top, lang)
                said_bottom = speak_math(bottom, lang)
                # "a over b" is how a simple fraction is said. It stops
                # working the moment either half is a sum: "tau squared over
                # tau squared plus sigma squared" can be heard three ways,
                # and the listener has no parentheses to fall back on. The
                # ratio phrasing binds, because "to" closes the first half.
                if _is_compound(top) or _is_compound(bottom):
                    out.append(
                        (
                            f"{words['ratio']} {said_top} {words['to']} {said_bottom}",
                            False,
                        )
                    )
                else:
                    out.append((f"{said_top} {words['over']} {said_bottom}", False))
                # A fraction followed by a bare symbol is a product, and a
                # page writes no sign for it. Said aloud it needs one, or
                # the symbol sounds like a stray letter.
                rest = text[i:].lstrip()
                if rest and (rest[0].isalnum() or rest[0] == "\\"):
                    # The comma is doing work, not decoration: it closes the
                    # ratio before the product opens, which is the only
                    # grouping a listener gets.
                    out.append((f", {words['times_implicit']}", False))
            else:
                # An unknown command loses its backslash and is spoken as the
                # word it already is. `\foo` as "foo" is wrong much less
                # often than `\foo` spelled out.
                out.append((words.get(command, command[1:]), False))
            continue

        if char == "_":
            body, i = _group(text, i + 1)
            spoken = speak_math(body, lang)
            # Letters in a subscript are spelled out. `T_{AB}` read as
            # "T ab" turns an index into a syllable; "T A B" is how somebody
            # says it at a blackboard. Digits are left alone -- "x 12" is a
            # number, not one and two.
            if spoken.isalpha() and len(spoken) > 1:
                spoken = " ".join(spoken)
            out.append((spoken, False))
            continue

        if char == "^":
            body, i = _group(text, i + 1)
            spoken = speak_math(body, lang).strip()
            if spoken == "2":
                out.append((words["squared"], False))
            elif spoken == "3":
                out.append((words["cubed"], False))
            else:
                out.append((f"{words['power']} {spoken}", False))
            continue

        if char == "-":
            out.append((words["minus"], False))
            i += 1
            continue

        # A parenthesis right after a name is an application, not a
        # grouping: `R(x_n)` is "R of x n", and dropping the bracket the way
        # a grouping is dropped glues it into "R x n" — which sounds like a
        # product of three things. Found on the French page, where the same
        # formula reads `R(x_n)` and came out as "Rx n".
        if char == "(" and out and out[-1][1] and out[-1][0][-1:].isalpha():
            body, i = _bracketed(text, i)
            out.append((f"{words['of']} {speak_math(body, lang)}", False))
            continue

        # Grouping brackets are punctuation for the eye. Said aloud they
        # become "open bracket", which is the spelling this module exists to
        # remove; the phrasing above is what carries the grouping instead.
        if char in "{}$()[]":
            i += 1
            continue

        if char in words:
            out.append((words[char], False))
            i += 1
            continue

        out.append((char, True))
        i += 1

    joined = ""
    previous_verbatim = False
    for piece, verbatim in out:
        if not joined:
            joined = piece
        elif verbatim and previous_verbatim and piece.strip():
            joined += piece
        else:
            joined += " " + piece
        previous_verbatim = verbatim and bool(piece.strip())
    # A space before a comma is a typing slip anywhere; here it also makes
    # the engine pause twice.
    return re.sub(r"\s+([,;:.])", r"\1", " ".join(joined.split()))


#: Whether a half of a fraction is more than one term, and therefore needs
#: the phrasing that binds it.
def _is_compound(latex: str) -> bool:
    body = _DROPPED.sub("", latex)
    return bool(re.search(r"[+\-=]|\\(?:cdot|times|pm|mp)\b", body))


def _bracketed(text: str, at: int) -> tuple[str, int]:
    """The parenthesised group starting at ``at``, and where it ends."""
    depth, i = 0, at
    while i < len(text):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return text[at + 1 : i], i + 1
        i += 1
    return text[at + 1 :], len(text)


def _argument(text: str, at: int) -> tuple[str, int]:
    r"""What a named operator applies to: its bracketed or braced argument.

    ``\mathbb{E}[\theta \mid m]`` is the shape every statistics paper
    writes; ``\mathbb{E}(X)`` and ``\mathbb{E}\{X\}`` are the same
    thing. A bare symbol after the operator counts too, so
    ``\mathbb{E} X`` reads.
    """
    rest = text[at:]
    stripped = rest.lstrip()
    offset = at + (len(rest) - len(stripped))
    pairs = {"[": "]", "(": ")", "{": "}"}
    if stripped and stripped[0] in pairs:
        opening, closing = stripped[0], pairs[stripped[0]]
        depth, i = 0, offset
        while i < len(text):
            if text[i] == opening:
                depth += 1
            elif text[i] == closing:
                depth -= 1
                if depth == 0:
                    return text[offset + 1 : i], i + 1
            i += 1
        return text[offset + 1 :], len(text)
    return _group(text, offset)


#: Inline and display maths, in the spellings a page actually uses. Display
#: first, so `$$…$$` is not read as two empty `$…$`.
_MATH = re.compile(
    r"\\\[(?P<display>.+?)\\\]"
    r"|\$\$(?P<display2>.+?)\$\$"
    r"|\\\((?P<inline>.+?)\\\)"
    r"|(?<![\w$])\$(?P<inline2>[^$\n]+?)\$(?![\w$])",
    re.S,
)


# ── When spelling it out is not reading it ─────────────────────────────────


def complexity(latex: str) -> int:
    """How much structure a formula carries.

    A rough count of the things that make a formula hard to follow by ear:
    commands, relations, nesting, sub- and superscripts. ``R`` scores zero
    and needs no help; a nested fraction of sums scores high and a
    symbol-by-symbol reading of it is sound without meaning.
    """
    score = len(re.findall(r"\\[a-zA-Z]+", latex))
    score += len(re.findall(r"[_^]", latex))
    score += len(re.findall(r"[=<>]|\\(?:le|ge|neq|approx)\b", latex))
    score += max(0, latex.count("{") - 1)
    return score


#: Above this, a formula is narrated rather than transliterated — when a
#: narrator is available. Six, because five is `R = T_{BA} \circ T_{AB}` —
#: one relation, one operator, two indices — and its mechanical reading
#: ("R equals T B A composed with T A B") is exactly what a person would
#: say. A nested fraction of sums scores nine, and there the mechanical
#: reading is sound with no meaning in it.
NARRATE_ABOVE: int = 6


def speakable(
    text: str,
    lang: str = "en",
    *,
    narrator=None,
) -> str:
    """The sentence as the voice should say it.

    Only the notation changes; every other word is the page's.

    ``narrator`` is an optional ``(latex, lang) -> str | None``. It is asked
    about formulas whose :func:`complexity` is above :data:`NARRATE_ABOVE`,
    and its answer is used when it gives one. This is the difference between
    *spelling* a formula and *reading* it: "the sum over i of x i, all over
    n" is a transliteration, "the average of the x values" is a sentence,
    and only the second survives being heard once with no page in front of
    you.

    It stays an injected callable rather than an import so this module needs
    no model, no network and no optional extra to be used or tested. Without
    one, every formula gets the deterministic reading — which is the
    baseline, not a degraded mode.
    """

    def _replace(match: re.Match) -> str:
        body = next(g for g in match.groups() if g is not None)
        plain = speak_math(body, lang)
        if narrator is not None and complexity(body) > NARRATE_ABOVE:
            try:
                told = narrator(body, lang)
            except Exception:  # pragma: no cover - a narrator is best effort
                told = None
            if told and told.strip() and "\\" not in told:
                return " ".join(told.split())
        return plain

    return " ".join(_MATH.sub(_replace, text).split())
