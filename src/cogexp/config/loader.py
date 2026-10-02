"""``experiments/`` の YAML を読み込み、参照整合性を検証する。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from cogexp.domain.models import Experiment, TaskVariant, VariantRef

DEFAULT_ROOT = Path(__file__).resolve().parents[3] / "experiments"


@dataclass(frozen=True)
class Catalog:
    variants: dict[VariantRef, TaskVariant]
    experiments: dict[str, Experiment]


def _load_yaml(path: Path) -> object:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_variants(root: Path = DEFAULT_ROOT) -> dict[VariantRef, TaskVariant]:
    variants: dict[VariantRef, TaskVariant] = {}
    for path in sorted((root / "tasks").glob("*.yaml")):
        data = _load_yaml(path)
        if not isinstance(data, dict) or not isinstance(data.get("variants"), list):
            raise ValueError(f"{path}: トップレベルに 'variants' のリストが必要")
        for raw in data["variants"]:
            variant = TaskVariant.model_validate(raw)
            if variant.ref in variants:
                raise ValueError(f"{path}: {variant.ref} が重複している")
            variants[variant.ref] = variant
    return variants


def load_catalog(root: Path = DEFAULT_ROOT) -> Catalog:
    variants = load_variants(root)
    experiments: dict[str, Experiment] = {}
    for path in sorted(root.glob("*.yaml")):
        exp = Experiment.model_validate(_load_yaml(path))
        if exp.experiment_id in experiments:
            raise ValueError(f"{path}: experiment_id {exp.experiment_id} が重複している")
        for cond in exp.conditions:
            for ref in cond.variant_refs():
                if ref not in variants:
                    raise ValueError(
                        f"{path}: 条件 {cond.condition_id} が未定義の版 {ref} を参照している"
                    )
        experiments[exp.experiment_id] = exp
    return Catalog(variants=variants, experiments=experiments)
