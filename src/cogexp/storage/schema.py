"""保存スキーマの単一定義。

列を変えたら ``docs/data_dictionary.md`` も更新すること（``dev.py check`` が差分を検出する）。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Column:
    name: str
    dtype: str  # "str" | "int" | "float" | "bool" | "datetime" | "json"
    nullable: bool = False


TABLES: dict[str, tuple[Column, ...]] = {
    "participants": (
        Column("participant_id", "str"),
        Column("experiment_id", "str"),
        Column("condition_id", "str"),
        Column("assignment_seed", "int"),
        Column("consent_status", "str"),
        Column("consented_at", "datetime", nullable=True),
        Column("status", "str"),
        Column("created_at", "datetime"),
        Column("completed_at", "datetime", nullable=True),
        Column("app_version", "str"),
        Column("config_hash", "str"),
    ),
    "trials": (
        Column("trial_id", "str"),
        Column("submission_id", "str"),
        Column("participant_id", "str"),
        Column("experiment_id", "str"),
        Column("condition_id", "str"),
        Column("task_id", "str"),
        Column("variant_id", "str"),
        Column("task_version", "int"),
        Column("presentation_order", "int"),
        Column("is_practice", "bool"),
        Column("response_format", "str"),
        Column("time_limit_sec", "float", nullable=True),
        Column("show_countdown", "bool"),
        Column("attempt", "str"),
        Column("shown_at_server", "datetime"),
        Column("submitted_at_server", "datetime", nullable=True),
        Column("shown_at_client_ms", "float", nullable=True),
        Column("submitted_at_client_ms", "float", nullable=True),
        Column("response_time_ms", "float", nullable=True),
        Column("outcome", "str"),
        Column("choice_id", "str", nullable=True),
        Column("response_value", "float", nullable=True),
        Column("is_correct", "bool", nullable=True),
        Column("confidence", "int", nullable=True),
        Column("confidence_timing", "str", nullable=True),
        Column("revision_count", "int"),
        Column("duplicate_submission_count", "int"),
    ),
    "events": (
        Column("event_id", "str"),
        Column("trial_id", "str"),
        Column("participant_id", "str"),
        Column("event_type", "str"),
        Column("t_client_ms", "float"),
        Column("x_norm", "float", nullable=True),
        Column("y_norm", "float", nullable=True),
        Column("target_id", "str", nullable=True),
        Column("payload", "json", nullable=True),
    ),
}

# 分析データに入れてはならない直接識別情報の列名（部分一致）
FORBIDDEN_COLUMN_PATTERNS: tuple[str, ...] = (
    "name",
    "email",
    "mail",
    "phone",
    "address",
    "ip_addr",
    "birth",
    "student_number",
)
