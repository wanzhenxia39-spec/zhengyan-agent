"""Skill 注册中心：编排器只能发现和调用已注册、带契约的 Skill。"""
from advisor.contracts.skill import Skill


class SkillRegistry:
    def __init__(self, skills: list[Skill] | None = None):
        self._skills: dict[str, Skill] = {}
        for s in skills or []:
            self.register(s)

    def register(self, skill: Skill) -> None:
        if skill.spec.name in self._skills:
            raise ValueError(f"重复注册: {skill.spec.name}")
        self._skills[skill.spec.name] = skill

    def get(self, name: str) -> Skill | None:
        return self._skills.get(name)

    def catalog(self) -> list[dict]:
        return [
            {"name": s.spec.name, "version": s.spec.version, "category": s.spec.category,
             "permission": s.spec.permission, "description": s.spec.description}
            for s in self._skills.values()
        ]
