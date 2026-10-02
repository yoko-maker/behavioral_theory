"""``experiments/`` の YAML を読み込み、参照整合性を検証する。"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

import yaml

from cogexp.domain.models import Experiment, TaskVariant, VariantRef

REPO_EXPERIMENTS = Path(__file__).resolve().parents[3] / "experiments"
TEXT_NAMES = ("intro", "consent", "instructions", "transition", "end", "declined")


@dataclass(frozen=True)
class Catalog:
    root: Path
    variants: dict[VariantRef, TaskVariant]
    experiments: dict[str, Experiment]

    def variant(self, ref: VariantRef) -> TaskVariant:
        return self.variants[ref]

    def config_hash(self, experiment_id: str) -> str:
        """実験定義と参照する全版の内容ハッシュ。participants.config_hash に保存する。"""
        exp = self.experiments[experiment_id]
        refs = {*exp.practice_refs(), *(r for c in exp.conditions for r in c.variant_refs())}
        payload = {
            "experiment": exp.model_dump(mode="json"),
            "variants": {str(r): self.variants[r].content_hash() for r in sorted(refs, key=str)},
        }
        text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def snapshot(self, experiment_id: str) -> dict[str, object]:
        """条件設定と問題文の版をまとめた出力（概要書 §9.3）。"""
        exp = self.experiments[experiment_id]
        refs = {*exp.practice_refs(), *(r for c in exp.conditions for r in c.variant_refs())}
        return {
            "config_hash": self.config_hash(experiment_id),
            "experiment": exp.model_dump(mode="json"),
            "variants": [self.variants[r].model_dump(mode="json") for r in sorted(refs, key=str)],
        }

    def text(self, name: str) -> str:
        """参加者向け文面（experiments/texts/<name>.md）。"""
        if name not in TEXT_NAMES:
            raise KeyError(name)
        return (self.root / "texts" / f"{name}.md").read_text(encoding="utf-8")


def default_root() -> Path:
    """COGEXP_EXPERIMENTS_DIR で差し替え可能（テスト・別の実験セットの実施用）。"""
    return Path(os.environ.get("COGEXP_EXPERIMENTS_DIR", REPO_EXPERIMENTS))


def _load_yaml(path: Path) -> object:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_variants(root: Path | None = None) -> dict[VariantRef, TaskVariant]:
    root = root or default_root()
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


def load_catalog(root: Path | None = None) -> Catalog:
    root = root or default_root()
    variants = load_variants(root)
    experiments: dict[str, Experiment] = {}
    for path in sorted(root.glob("*.yaml")):
        exp = Experiment.model_validate(_load_yaml(path))
        if exp.experiment_id in experiments:
            raise ValueError(f"{path}: experiment_id {exp.experiment_id} が重複している")
        for ref in exp.practice_refs():
            if ref not in variants:
                raise ValueError(f"{path}: 練習課題が未定義の版 {ref} を参照している")
        for cond in exp.conditions:
            for ref in cond.variant_refs():
                if ref not in variants:
                    raise ValueError(
                        f"{path}: 条件 {cond.condition_id} が未定義の版 {ref} を参照している"
                    )
        experiments[exp.experiment_id] = exp
    for name in TEXT_NAMES:
        if not (root / "texts" / f"{name}.md").exists():
            raise ValueError(f"{root / 'texts'}: 参加者向け文面 {name}.md がない")
    return Catalog(root=root, variants=variants, experiments=experiments)
