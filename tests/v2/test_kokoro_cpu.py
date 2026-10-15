"""Independent guards for the offline CPU audition seam."""
import re
from types import SimpleNamespace

import pytest

from lvc.tts.kokoro_cpu import GenerationCanceled, IncompletePhonemes, plan_phonemes


def _g2p(text: str):
    matches = list(re.finditer(r"(\S+)(\s*)", text))
    return " ".join(match[1].lower() for match in matches), [
        SimpleNamespace(text=match[1], phonemes=match[1].lower(), whitespace=match[2])
        for match in matches
    ]


def test_planning_preserves_original_text_and_rejects_long_phonemes():
    source = "Alpha beta.  Alpha beta.\nThird line."
    units = plan_phonemes(source, _g2p, max_phonemes=20)
    assert "".join(unit.text for unit in units) == source
    assert all(0 < len(unit.phonemes) <= 20 for unit in units)


def test_missing_word_phonemes_are_rejected():
    def missing(_text):
        return "alpha", [SimpleNamespace(text="alpha", phonemes="alpha", whitespace=" "),
                         SimpleNamespace(text="beta", phonemes="", whitespace="")]

    with pytest.raises(IncompletePhonemes):
        plan_phonemes("alpha beta", missing)


def test_tokenizer_text_changes_are_rejected():
    with pytest.raises(IncompletePhonemes):
        plan_phonemes("Bring 10 stones.", lambda _text: ("bɹɪŋ", [
            SimpleNamespace(text="Bring", phonemes="bɹɪŋ", whitespace="")]))


def test_cancel_before_phonemizing():
    with pytest.raises(GenerationCanceled):
        plan_phonemes("Never read this.", _g2p, still_current=lambda: False)
