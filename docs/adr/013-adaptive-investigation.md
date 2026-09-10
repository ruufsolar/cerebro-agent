# ADR 013 — Adaptive investigation with fourteen specialist turns

Status: accepted for implementation; live rollout requires operator verification.

Supersedes earlier routing fallback, relation allowlist and model/tool/deadline decisions in
ADRs 003, 004, 006 and 010 where they conflict. ADR 012's simplified modes and senior-maintained
delivery remain unchanged.

## Decision

Keep general/payment specialists and grounded payment output. Route the latest request in
context; vague or invalid classifications ask one concise question without investigating.
Instruction handling is separate from intent. Allow one specialist route correction sharing
fourteen total specialist model calls. Router gets one separate call; final specialist call
has no tools. Payment ambiguity may ask one targeted question after using available evidence.

Both specialists discover all application relations readable by the replica role. Curated
schema files guide rather than authorize. Database read-only privileges, SQL operation/function
checks, connection/time/result limits remain. Catalog access is via trusted metadata tools only.
Specialized payment helpers are optional shortcuts; paid/cancelled history is investigation
context, never collection authority.

Both routes load/recall existing shared memory; writing remains general-only. Memory references
and version enter existing audit JSON. Source references from SQL require primary-key re-reads
and unique declared-FK links to an order before evidence registration. Generic links remain weak;
computed values, inferred joins and memory cannot establish verified identity.

Remove overall investigation deadlines, custom tool-count budgets and application output-token
caps. Retain a configurable 180-second per-provider-request timeout and per-operation resource
limits. No model migration, adaptive reasoning, new working memory, compaction, checkpoints,
automatic resume or production grants/deployment accompany this change.

## Consequences and verification

Investigations can take longer and consume more tokens. Concise Slack rendering stays unchanged;
quality-report latency/usage thresholds remain diagnostic. Heartbeat health, not elapsed run
time alone, detects stalls. The 240-second fail-closed drain can defer an update for healthy work.
Operators must review the actual replica role and configure future-object grants; code cannot
expand PostgreSQL permissions. Live Azure routing accuracy requires operator acceptance.

Offline checks cover tool-free clarifications, fourteen-turn SDK execution and shared correction
budget, metadata/grants/paging in an additional schema, fabricated source rejection, memory
failure isolation, historical attribution, and existing Slack/cleanup/deployment behavior.
No migrations or new persistent memory structures are required.
