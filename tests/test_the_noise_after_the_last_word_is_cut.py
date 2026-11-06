"""
The noise Chatterbox appends after the last word is cut; the word is not.

The multilingual model sometimes keeps generating once the sentence is said:
silence, then a second of clicks or breath as loud as the voice. The guard
keys on voicing, so these takes are synthetic: a 150 Hz tone stands for a
vowel, white noise for the artefact.

Author
------
Warith HARCHAOUI — https://linkedin.com/in/warith-harchaoui/
"""

from __future__ import annotations

import numpy as np

from speaker_helper.backends.chatterbox import SAMPLE_RATE_HZ, trailing_artifact_start

SR = SAMPLE_RATE_HZ


def voice(seconds: float) -> np.ndarray:
    t = np.arange(int(SR * seconds)) / SR
    return 0.3 * np.sin(2 * np.pi * 150 * t)


def silence(seconds: float) -> np.ndarray:
    return np.zeros(int(SR * seconds))


def noise(seconds: float) -> np.ndarray:
    return 0.05 * np.random.default_rng(0).standard_normal(int(SR * seconds))


def test_noise_after_a_silence_is_cut_at_the_end_of_the_silence() -> None:
    take = np.concatenate([voice(1.0), silence(0.2), noise(1.0)])
    cut = trailing_artifact_start(take, SR)
    assert cut is not None
    assert SR * 11 // 10 <= cut <= SR * 12 // 10


def test_a_second_sentence_after_a_pause_is_kept() -> None:
    take = np.concatenate([voice(1.0), silence(0.3), voice(0.8), silence(0.2)])
    assert trailing_artifact_start(take, SR) is None


def test_a_final_consonant_joined_to_its_vowel_is_kept() -> None:
    take = np.concatenate([voice(1.0), noise(0.08), silence(0.3)])
    assert trailing_artifact_start(take, SR) is None


def test_a_clean_take_and_a_silent_one_are_untouched() -> None:
    assert trailing_artifact_start(np.concatenate([voice(1.0), silence(0.5)]), SR) is None
    assert trailing_artifact_start(silence(1.0), SR) is None
