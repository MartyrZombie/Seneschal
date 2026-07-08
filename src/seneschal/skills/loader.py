"""SKILL.md progressive disclosure loader (plan §10)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class SkillMeta:
    name: str
    description: str
    path: Path


class SkillIndex:
    """Loads skill metadata for context; full bodies on demand."""

    META_PATTERN = re.compile(r"^#\s+(.+)$", re.M)
    DESC_PATTERN = re.compile(r"^description:\s*(.+)$", re.M | re.I)

    def __init__(self, skills_dir: Path) -> None:
        self.skills_dir = skills_dir

    def list_skills(self) -> list[SkillMeta]:
        if not self.skills_dir.exists():
            return []
        skills: list[SkillMeta] = []
        for skill_dir in sorted(self.skills_dir.iterdir()):
            if not skill_dir.is_dir():
                continue
            skill_md = skill_dir / "SKILL.md"
            if not skill_md.exists():
                continue
            text = skill_md.read_text()
            name_match = self.META_PATTERN.search(text)
            desc_match = self.DESC_PATTERN.search(text)
            skills.append(
                SkillMeta(
                    name=name_match.group(1).strip() if name_match else skill_dir.name,
                    description=desc_match.group(1).strip() if desc_match else "",
                    path=skill_md,
                )
            )
        return skills

    def metadata_block(self) -> str:
        lines = []
        for skill in self.list_skills():
            lines.append(f"- {skill.name}: {skill.description}")
        return "\n".join(lines) if lines else "(no skills loaded)"

    def load_body(self, name: str) -> str | None:
        for skill in self.list_skills():
            if skill.name.lower() == name.lower() or skill.path.parent.name == name:
                return skill.path.read_text()
        return None
