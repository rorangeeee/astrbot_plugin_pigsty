from __future__ import annotations

from core.interaction import (
    build_interaction_classification_prompt,
    build_interaction_conversion_prompt,
    parse_intent_response,
    parse_user_interaction_plan,
)
from core.models import Pig


def test_classification_prompt_lists_the_current_pig_positions() -> None:
    pigs = (Pig(name="白雪 小猪", weight_kg=5.0), Pig(name="花花 猪", weight_kg=7.5))

    prompt = build_interaction_classification_prompt(pigs, "给小猪喂点东西")

    assert "1. 白雪 小猪" in prompt
    assert "2. 花花 猪" in prompt
    assert "给小猪喂点东西" in prompt


def test_conversion_prompt_contains_current_values_and_global_limits() -> None:
    pigs = (Pig(name="白雪 小猪", health=80, mood=50, energy=40),)

    prompt = build_interaction_conversion_prompt(pigs, "让它多吃一点")

    assert "白雪 小猪" in prompt
    assert "体重：5.00kg" in prompt
    assert "健康：80" in prompt
    assert "心情：50" in prompt
    assert "体力：40" in prompt
    assert "0 到 100" in prompt
    assert "0.01kg" in prompt


def test_parse_intent_response_accepts_true_and_false() -> None:
    assert parse_intent_response('{"involves_pigs": true}') is True
    assert parse_intent_response('{"involves_pigs": false}') is False
    assert parse_intent_response('```json\n{"involves_pigs": true}\n```') is True
    assert parse_intent_response("not json") is None


def test_parse_user_interaction_plan_extracts_changes_and_reply() -> None:
    raw = """
    ```json
    {
      "interactions": [
        {
          "pig_position": 1,
          "description": "喂了一碗玉米糊",
          "changes": {"weight_kg": 0.2, "health": 2, "mood": 5, "energy": 10}
        }
      ],
      "reply": "已经给小猪喂了一碗玉米糊。"
    }
    ```
    """

    plan = parse_user_interaction_plan(raw)

    assert plan is not None
    assert plan.reply == "已经给小猪喂了一碗玉米糊。"
    assert len(plan.interactions) == 1
    interaction = plan.interactions[0]
    assert interaction.position == 1
    assert interaction.description == "喂了一碗玉米糊"
    assert {change.key: change.delta for change in interaction.changes} == {
        "weight_kg": 0.2,
        "health": 2,
        "mood": 5,
        "energy": 10,
    }


def test_parse_user_interaction_plan_rejects_duplicate_positions() -> None:
    raw = (
        '{"interactions": ['
        '{"pig_position": 1, "description": "a", "changes": {"mood": 1}}, '
        '{"pig_position": 1, "description": "b", "changes": {"health": 1}}'
        "]}"
    )

    assert parse_user_interaction_plan(raw) is None


def test_parse_user_interaction_plan_skips_zero_change_entries() -> None:
    raw = '{"interactions": [{"pig_position": 1, "description": "a", "changes": {}}]}'

    plan = parse_user_interaction_plan(raw)

    assert plan is not None
    assert plan.interactions == ()
    assert plan.reply == ""
