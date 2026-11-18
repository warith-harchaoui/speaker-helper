"""
Prosody: what the voice did, measured from the audio alone.

Module summary
--------------
The pronunciation loop asks *which sounds* were said; the prosody loop asks
*how* they were said — the melody at the end of the sentence (did a question
rise?) and the energy of the delivery (calm or excited?). Both are read from
the signal, never from a transcript, so the words cannot vouch for a reading
the voice did not give.

* :func:`pitch_track` — the fundamental frequency (F0) over time, by pYIN.
* :func:`final_contour` — the movement of the last voiced stretch, in
  semitones, and its shape: ``rise``, ``fall`` or ``level``.
* :func:`measure` — every feature of one take in a :class:`ProsodyFeatures`:
  median F0, F0 range, final contour, loudness and its spread, voiced share.
* :func:`arousal_shift` — how much more (or less) activated a take is than a
  neutral take of the same sentence by the same voice. Arousal is relative by
  nature: a high voice is not an excited one, and comparing a take with its
  own neutral reading cancels the speaker.

Semitones, not hertz: a rise of 30 Hz is large for a low voice and small for a
high one, while 2 semitones is the same perceived step for both.

Usage example
-------------
>>> semitones(220.0, 110.0)
12.0

Author
------
Warith HARCHAOUI — https://linkedin.com/in/warith-harchaoui
"""

from __future__ import annotations

import io
import math
from dataclasses import dataclass
from typing import Any

#: Analysis rate: pYIN is accurate and cheap at 16 kHz for speech.
SAMPLE_RATE = 16000

#: pYIN search range. 65 Hz covers a low male voice; 600 Hz an excited female
#: one (the default voices here are female, ~180-250 Hz at rest).
F0_MIN_HZ = 65.0
F0_MAX_HZ = 600.0

#: Analysis hop: 10 ms, the usual resolution for intonation.
HOP = 160
FRAME = 1024

#: How much of the end of the utterance the final contour looks at.
FINAL_WINDOW_S = 0.4


def semitones(f: float, reference: float) -> float:
    """The interval from ``reference`` to ``f``, in semitones.

    Parameters
    ----------
    f, reference : float
        Two frequencies in Hz (positive).

    Returns
    -------
    float
        ``12 * log2(f / reference)``.
    """
    return round(12.0 * math.log2(f / reference), 6)


def _mono16k(wav_bytes: bytes) -> Any:
    """Decode a WAV payload to mono float32 at :data:`SAMPLE_RATE`.

    Parameters
    ----------
    wav_bytes : bytes
        Encoded audio.

    Returns
    -------
    numpy.ndarray
        The samples.
    """
    import numpy as np
    import soundfile as sf

    data, sr = sf.read(io.BytesIO(wav_bytes), dtype="float32", always_2d=True)
    mono = data.mean(axis=1)
    if sr != SAMPLE_RATE:
        import librosa

        mono = librosa.resample(mono, orig_sr=sr, target_sr=SAMPLE_RATE)
    return np.ascontiguousarray(mono, dtype="float32")


def pitch_track(samples: Any) -> tuple[Any, Any]:
    """F0 over time by probabilistic YIN, cleaned for intonation work.

    Voicing is pYIN's own HMM decision, not a threshold on its per-frame
    probability: the 0.5 cut the literature suggests kept 24 of 89 voiced
    frames on a kokoro sentence, which leaves no final contour to measure.
    The track is then median-filtered over five frames (50 ms), and any frame
    more than an octave from the utterance median is dropped as an octave
    error of the tracker.

    Parameters
    ----------
    samples : numpy.ndarray
        Mono audio at :data:`SAMPLE_RATE`.

    Returns
    -------
    tuple of (numpy.ndarray, numpy.ndarray)
        Frame times in seconds, and F0 in Hz (``nan`` where unvoiced).
    """
    import librosa
    import numpy as np

    f0, voiced, _probability = librosa.pyin(
        samples,
        fmin=F0_MIN_HZ,
        fmax=F0_MAX_HZ,
        sr=SAMPLE_RATE,
        frame_length=FRAME,
        hop_length=HOP,
    )
    f0 = np.where(voiced, f0, np.nan)
    times = librosa.times_like(f0, sr=SAMPLE_RATE, hop_length=HOP)
    if np.sum(~np.isnan(f0)) >= 5:
        f0 = _median_filter(f0, 5)
        median = np.nanmedian(f0)
        octave_errors = np.abs(12.0 * np.log2(f0 / median)) > 12.0
        f0 = np.where(octave_errors, np.nan, f0)
    return times, f0


def _median_filter(f0: Any, width: int) -> Any:
    """Median-filter a track, ignoring unvoiced (``nan``) frames.

    Parameters
    ----------
    f0 : numpy.ndarray
        F0 with ``nan`` gaps.
    width : int
        Odd window length in frames.

    Returns
    -------
    numpy.ndarray
        The filtered track; unvoiced frames stay ``nan``.

    Examples
    --------
    >>> import numpy as np
    >>> _median_filter(np.array([200, 200, 400, 200, 200, np.nan]), 3).tolist()[:5]
    [200.0, 200.0, 200.0, 200.0, 200.0]
    """
    import numpy as np

    half = width // 2
    out = np.full_like(f0, np.nan, dtype=float)
    for i in range(len(f0)):
        if np.isnan(f0[i]):
            continue
        window = f0[max(0, i - half) : i + half + 1]
        out[i] = np.nanmedian(window)
    return out


#: The last voiced 40 ms are left out of the final contour: the voice often
#: creaks or drops into vocal fry there, which the tracker reads as a fall.
CREAK_S = 0.04

#: Contour thresholds, in semitones over the final window. Perception needs
#: roughly 1.5-3 st of excursion ('t Hart 1981); these are the engineering
#: values the TTS-prosody literature uses (no standard exists): a rise must
#: climb at least 3 st above the window's low point, a fall end at least 2 st
#: below its high point.
RISE_ST = 3.0
FALL_ST = 2.0


@dataclass
class Contour:
    """The melody of the end of an utterance.

    Attributes
    ----------
    slope_st : float
        Robust (Theil-Sen) slope across the window, in semitones.
    rise_st : float
        End of the window minus its lowest point (how far it climbed).
    fall_st : float
        Highest point of the window minus its end (how far it dropped).
    shape : str
        ``"rise"``, ``"fall"`` or ``"level"``.
    """

    slope_st: float
    rise_st: float
    fall_st: float
    shape: str


def final_contour(times: Any, f0: Any, window_s: float = FINAL_WINDOW_S) -> Contour | None:
    """How the melody moves over the last voiced stretch.

    The window is the last ``window_s`` seconds of voicing, minus the final
    :data:`CREAK_S`. Its F0 is put in semitones from the utterance median; the
    slope is a Theil-Sen fit (the median of pairwise slopes, so one stray
    frame cannot flip it), and the excursions are measured from the window's
    extremes to its last frames.

    Parameters
    ----------
    times : numpy.ndarray
        Frame times (s).
    f0 : numpy.ndarray
        F0 in Hz, ``nan`` where unvoiced.
    window_s : float
        Length of the final stretch examined.

    Returns
    -------
    Contour or None
        The contour, or ``None`` with fewer than five voiced frames in the
        window.

    Examples
    --------
    >>> import numpy as np
    >>> t = np.arange(0, 1, 0.01)
    >>> rising = 200 * 2 ** (np.clip(t - 0.6, 0, None) * 10 / 12)  # +4 st at the end
    >>> final_contour(t, rising).shape
    'rise'
    """
    import numpy as np

    voiced = ~np.isnan(f0)
    if voiced.sum() < 5:
        return None
    end = times[voiced][-1] - CREAK_S
    mask = voiced & (times >= end - window_s) & (times <= end)
    if mask.sum() < 5:
        return None
    st = 12.0 * np.log2(f0[mask] / np.nanmedian(f0))
    t = times[mask]
    pairs = [(st[j] - st[i]) / (t[j] - t[i]) for i in range(len(t)) for j in range(i + 1, len(t))]
    slope = float(np.median(pairs)) * float(t[-1] - t[0])
    # The end is the mean of the last three frames, not the last one alone.
    tail = float(np.mean(st[-3:]))
    rise = tail - float(np.min(st))
    fall = float(np.max(st)) - tail
    if rise >= RISE_ST and slope > 0:
        shape = "rise"
    elif fall >= FALL_ST and slope < 0:
        shape = "fall"
    else:
        shape = "level"
    return Contour(round(slope, 3), round(rise, 3), round(fall, 3), shape)


@dataclass
class ProsodyFeatures:
    """What one take's voice did.

    Attributes
    ----------
    f0_median_hz : float or None
        Median F0 over voiced frames.
    f0_range_st : float or None
        Spread of F0: 90th minus 10th percentile, in semitones.
    final : Contour or None
        Final contour (see :func:`final_contour`).
    loudness_db : float
        Mean frame energy over voiced frames, dBFS.
    loudness_spread_db : float
        Spread of frame energy (90th minus 10th percentile), dB.
    voiced_share : float
        Share of frames that are voiced (a proxy for pausing and rate).
    duration_s : float
        Length of the take.
    """

    f0_median_hz: float | None
    f0_range_st: float | None
    final: Contour | None
    loudness_db: float
    loudness_spread_db: float
    voiced_share: float
    duration_s: float


def measure(wav_bytes: bytes) -> ProsodyFeatures:
    """Measure one take's prosody.

    Parameters
    ----------
    wav_bytes : bytes
        Encoded audio of the take.

    Returns
    -------
    ProsodyFeatures
        Its features (F0 fields ``None`` when the take has almost no voicing).
    """
    import librosa
    import numpy as np

    samples = _mono16k(wav_bytes)
    times, f0 = pitch_track(samples)
    rms = librosa.feature.rms(y=samples, frame_length=FRAME, hop_length=HOP)[0]
    db = 20.0 * np.log10(np.maximum(rms, 1e-6))
    n = min(len(db), len(f0))
    db, f0, times = db[:n], f0[:n], times[:n]
    voiced = ~np.isnan(f0)
    if voiced.sum() >= 5:
        median = float(np.nanmedian(f0))
        p10, p90 = np.nanpercentile(f0, [10, 90])
        f0_range = semitones(float(p90), float(p10))
        loud = db[voiced]
    else:
        median, f0_range, loud = None, None, db
    lo, hi = np.percentile(loud, [10, 90])
    return ProsodyFeatures(
        f0_median_hz=round(median, 2) if median else None,
        f0_range_st=round(f0_range, 3) if f0_range is not None else None,
        final=final_contour(times, f0),
        loudness_db=round(float(np.mean(loud)), 3),
        loudness_spread_db=round(float(hi - lo), 3),
        voiced_share=round(float(voiced.mean()), 4) if n else 0.0,
        duration_s=round(len(samples) / SAMPLE_RATE, 3),
    )


def arousal_shift(take: ProsodyFeatures, neutral: ProsodyFeatures) -> float:
    """How much more activated ``take`` is than ``neutral``, in one number.

    The classic acoustic correlates of arousal, each relative to the neutral
    reading of the same sentence by the same voice: higher median F0 (in
    semitones), wider F0 range (semitones), louder (dB, at a third of the
    weight: loudness is partly the engine's normalisation, not the voice).
    Positive is more activated, negative calmer, around 0 the same.

    Parameters
    ----------
    take : ProsodyFeatures
        The take under judgement.
    neutral : ProsodyFeatures
        A neutral take of the same text by the same voice.

    Returns
    -------
    float
        The shift, in roughly semitone-sized units.

    Examples
    --------
    >>> base = ProsodyFeatures(200.0, 6.0, None, -20.0, 12.0, 0.6, 2.0)
    >>> excited = ProsodyFeatures(238.0, 9.0, None, -17.0, 14.0, 0.6, 1.8)
    >>> round(arousal_shift(excited, base), 2)  # +3.0 st, +3.0 st, +3 dB / 3
    2.34
    """
    parts: list[float] = []
    if take.f0_median_hz and neutral.f0_median_hz:
        parts.append(semitones(take.f0_median_hz, neutral.f0_median_hz))
    if take.f0_range_st is not None and neutral.f0_range_st is not None:
        parts.append(take.f0_range_st - neutral.f0_range_st)
    parts.append((take.loudness_db - neutral.loudness_db) / 3.0)
    return round(sum(parts) / len(parts), 3)
