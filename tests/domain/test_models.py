from __future__ import annotations

import pytest
from pydantic import ValidationError

from cogexp.domain.models import TaskVariant, VariantRef


def _choice_variant(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "task_id": "linda",
        "variant_id": "standard",
        "version": 1,
        "response_format": "choice",
        "prompt": "問題文",
        "choices": [{"id": "a", "text": "A"}, {"id": "b", "text": "B"}],
        "correct_choice_id": "a",
    }
    return base | overrides


def test_variant_ref_roundtrip() -> None:
    ref = VariantRef.parse("bat_ball/explicit@2")
    assert (ref.task_id, ref.variant_id, ref.version) == ("bat_ball", "explicit", 2)
    assert str(ref) == "bat_ball/explicit@2"


@pytest.mark.parametrize("text", ["linda/standard", "linda@1", "Linda/standard@1", "a/b@0"])
def test_variant_ref_rejects_malformed(text: str) -> None:
    with pytest.raises(ValueError):
        VariantRef.parse(text)


def test_choice_correct_id_must_exist() -> None:
    with pytest.raises(ValidationError):
        TaskVariant.model_validate(_choice_variant(correct_choice_id="zzz"))


def test_numeric_rejects_choices() -> None:
    with pytest.raises(ValidationError):
        TaskVariant.model_validate(
            _choice_variant(response_format="numeric", correct_choice_id=None)
        )


def test_content_hash_changes_with_prompt() -> None:
    a = TaskVariant.model_validate(_choice_variant())
    b = TaskVariant.model_validate(_choice_variant(prompt="問題文（改）"))
    assert a.content_hash() != b.content_hash()
