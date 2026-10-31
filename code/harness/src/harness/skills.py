"""Skills：给流程，不给能力。

目录约定：
    skills/<name>/SKILL.md
    skills/<name>/workflow.json   # 可选；有它才能 as_workflow
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .body import WorkflowPolicy
from .contracts import Step


@dataclass(frozen=True)
class SkillMeta:
    name: str
    description: str
    allowed_tools: list[str] = field(default_factory=list)
    path: str = ""


@dataclass
class Skill:
    meta: SkillMeta
    body: str
    resources: dict[str, str] = field(default_factory=dict)


class SkillRegistry:
    def __init__(self, skills: dict[str, Skill] | None = None) -> None:
        self.skills = dict(skills or {})

    @classmethod
    def from_dir(cls, root: str | Path) -> "SkillRegistry":
        root = Path(root)
        skills: dict[str, Skill] = {}
        if not root.exists():
            return cls()
        for folder in sorted(p for p in root.iterdir() if p.is_dir()):
            manifest = folder / "SKILL.md"
            if not manifest.exists():
                continue
            raw = manifest.read_text(encoding="utf-8")
            meta, body = _parse_manifest(folder.name, raw, str(folder))
            resources = {}
            refs = folder / "references"
            for path in (sorted(refs.glob("*")) if refs.exists() else []):
                if path.is_file():
                    resources[path.name] = path.read_text(encoding="utf-8", errors="ignore")
            skills[meta.name] = Skill(meta=meta, body=body, resources=resources)
        return cls(skills)

    def catalog(self) -> list[SkillMeta]:
        return [skill.meta for skill in self.skills.values()]

    def load(self, name: str) -> Skill:
        if name not in self.skills:
            raise KeyError(f"未知 Skill：{name}")
        return self.skills[name]

    def as_workflow(self, name: str) -> WorkflowPolicy:
        skill = self.load(name)
        manifest = Path(skill.meta.path) / "workflow.json"
        if not manifest.exists():
            raise ValueError(f"Skill {name} 只有说明，不能编译成 Workflow")
        rows = json.loads(manifest.read_text(encoding="utf-8"))
        steps = [Step(**row) for row in rows["steps"]]
        return WorkflowPolicy(steps)


def _parse_manifest(folder_name: str, raw: str, path: str) -> tuple[SkillMeta, str]:
    name = folder_name
    description = ""
    allowed: list[str] = []
    body = raw
    if raw.startswith("---"):
        parts = raw.split("---", 2)
        if len(parts) >= 3:
            front, body = parts[1], parts[2].lstrip()
            for line in front.splitlines():
                if ":" not in line:
                    continue
                key, value = line.split(":", 1)
                key, value = key.strip(), value.strip()
                if key == "name":
                    name = value
                elif key == "description":
                    description = value
                elif key == "allowed-tools":
                    allowed = [item.strip() for item in value.strip("[]").split(",") if item.strip()]
    if not description:
        description = next((line.strip("# ").strip() for line in body.splitlines() if line.strip()), "")
    return SkillMeta(name=name, description=description, allowed_tools=allowed, path=path), body
