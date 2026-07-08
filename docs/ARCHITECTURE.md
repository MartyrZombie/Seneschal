# Architecture

See the project plan in the repository root discussion / PR description for the full design.

## Component map

| Package | Plan § | Role |
|---------|--------|------|
| `seneschal.ingest` | §5 | Deterministic command/content classification |
| `seneschal.broker` | §11 | Capability broker — actions not secrets |
| `seneschal.dispatcher` | §8 | Subtask queue, budgets, redaction |
| `seneschal.orchestrator` | §7 | Plans, delegates, synthesizes |
| `seneschal.memory` | §9 | Working, episodic, semantic tiers |
| `seneschal.skills` | §10 | SKILL.md progressive disclosure |
| `seneschal.channels` | §18 | Desktop shim, email/SMS/voice stubs |
| `seneschal.correspondence` | §6 | Third-party thread policy |
| `seneschal.trace` | §17 | Unified JSONL trace log |
| `seneschal.scheduler` | §16 | Synthetic command injection |
| `seneschal.mcp` | §14 | MCP vetting framework |

## Build order

1. OS + agent user + ZFS (outside this repo)
2. Ingest layer
3. Capability broker
4. Orchestrator + dispatcher
5. OpenAI shim + desktop client
6. Memory + skills
7. Unified trace
8. MCP
9. OpenRouter external path
10. Egress enforcement
11. Text/email channels
12. Scheduler, digest, watchdog, backup
13. Voice channel
14. Staging + regression eval

## Deterministic vs model

**Deterministic (no LLM in enforcement path):** ingest, dispatcher, broker, redaction, egress control.

**Model-backed:** orchestrator, sub-agents, voice conversational layer.
