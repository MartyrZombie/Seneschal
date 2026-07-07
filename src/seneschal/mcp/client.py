"""MCP integration framework and vetting checklist (plan §14)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class McpRiskTier(str, Enum):
    READ_ONLY = "read_only"
    WRITE = "write"
    EXTERNAL_COMMUNICATION = "external_communication"
    DESTRUCTIVE = "destructive"


@dataclass
class McpServerSpec:
    name: str
    version: str
    commit_hash: str
    risk_tier: McpRiskTier
    scopes: list[str] = field(default_factory=list)


VETTING_CHECKLIST = [
    "provenance: identifiable source, real commit history, compatible license",
    "read_before_trust: inspect tool descriptions and response schemas",
    "scope_it: narrowest filesystem/network grant; secrets via broker",
    "test_in_isolation: sub-agent first with injected adversarial input",
    "ongoing: pin version/commit, re-review every bump",
]

REJECTION_RED_FLAGS = [
    "broader permissions than function needs",
    "obfuscated code",
    "unpinnable versions (unpinned npx-and-forget)",
    "bundled credential storage",
    "tool descriptions phrased as directives at the AI",
]


@dataclass
class McpClient:
    """Stub MCP client — wire to 2026 spec incremental scope consent in build step 8."""

    servers: dict[str, McpServerSpec] = field(default_factory=dict)

    def register(self, spec: McpServerSpec) -> None:
        self.servers[spec.name] = spec

    def vet(self, spec: McpServerSpec) -> list[str]:
        issues: list[str] = []
        if not spec.commit_hash:
            issues.append("missing pinned commit hash")
        if spec.risk_tier in (McpRiskTier.EXTERNAL_COMMUNICATION, McpRiskTier.DESTRUCTIVE):
            issues.append("requires broker routing and manual approval")
        return issues
