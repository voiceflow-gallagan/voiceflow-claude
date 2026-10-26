---
name: migrate-v3-to-v4
description: >-
  Rebuild a Voiceflow v3 (legacy) project as a v4 agent, starting from its .vf export.
  Use when the user has a .vf file, mentions a v3 / legacy / conversation-flow Voiceflow
  project, or asks to migrate, convert or port a Voiceflow agent to v4. Audits the file,
  proposes a redesign plan for approval, then builds a new v4 project through the
  Voiceflow MCP server (or the vf CLI when a terminal is available).
---

# Migrate a Voiceflow v3 project to v4

Voiceflow has no automatic v3 to v4 converter. The official guidance is to rebuild the
agent in v4 using the v3 project as a reference for *what* it does, not *how*
([V4 migration guide](https://www.voiceflow.com/docs/v4-migration-guide)). This skill
automates that rebuild in four phases. Never skip the approval gate between phase 2 and 3.

## Ground rules

- **The .vf file is the only source.** v3 projects are not on the environments system, so
  the Voiceflow MCP server and the vf CLI cannot read them. Ask the user to export the
  project from the Creator dashboard (project menu, Export, .vf).
- **Always build into a new project.** Never modify an existing project.
- **Credentials:** a .vf can hold API keys in plain text (API step headers, code). Never
  print, copy or log their values. The audit script redacts them; recreate each one as an
  empty Voiceflow secret and ask the user to paste the value in the Creator.
- **Knowledge base:** a .vf export does not include knowledge base documents. Ask the user
  for their source URLs, sitemaps and files.
- **Docs first:** before naming a step, setting or UI location, check it with the Voiceflow
  documentation (the Voiceflow docs MCP server if connected, otherwise
  https://www.voiceflow.com/docs). v4 changes often.

## Phase 1: Audit

1. Get the .vf path from the user.
2. If a shell is available, run:
   `python3 scripts/vf_audit.py <file.vf> --out <work dir>`
   It writes `<name>.audit.md` (for the user) and `<name>.ir.json` (for you). It handles every
   schema version seen so far and prints unknown step types instead of failing.
3. Without a shell, read the .vf as JSON yourself and follow the same structure (see
   `references/vf-format.md`). Apply the same credential rule before quoting anything.
4. Show the user the audit summary: topics, components, intents, API calls, AI steps,
   credentials found, and the "Needs a human" list.

## Phase 2: Redesign plan (approval gate)

Ask which mode the user wants:

- **Redesign (default, recommended by Voiceflow):** agentic v4. Global prompt for persona and
  guardrails, agent instructions for routing, playbooks for conversational tasks, workflows
  only where order must be guaranteed, knowledge base for FAQ content.
- **Faithful port:** each v3 topic and component becomes a workflow with equivalent steps,
  routed by agent instructions. Closer to the original, less agentic.

Write the plan with `references/concept-mapping.md` and `references/step-mapping.md`:

- Project: name (suffix " (v4)"), channel (`webchat` for chat, `phone-call` for voice).
- Global prompt draft (persona, tone, guardrails from the v3 messages).
- One row per v3 topic or component: v4 target (playbook, workflow, knowledge base, or
  dropped), name, trigger sentence, tools it needs.
- Agent instructions: one routing line per custom intent, built from its utterances.
- Tools: one API tool per distinct API endpoint, one function per code step worth keeping,
  one secret per redacted credential.
- Variables to create, entities that become structured-output fields.
- Test cases: two or three utterances per intent with the expected skill.
- Open items for the user.

Save the plan as a file, show it, and **wait for explicit approval**. Apply edits and ask again.

## Phase 3: Build

Use the Voiceflow MCP server (tools named `voiceflow_*`; resolve them by name at runtime,
read each tool's description before the first call). With a terminal and the vf CLI
signed in, the equivalent `vf` commands work too. Build in this order and stop on the first
error you cannot explain:

1. `voiceflow_project` create (workspace chosen by the user) and note the project ID.
2. `voiceflow_variable` create the variables.
3. `voiceflow_secret` create one empty secret per redacted credential.
4. `voiceflow_api_tool` / `voiceflow_function` create the tools; reference secrets, never
   literal values.
5. `voiceflow_playbook` create each playbook with its instructions and attach its tools
   (`voiceflow_tool`).
6. `voiceflow_workflow` create each workflow (faithful mode, or deterministic tasks).
7. `voiceflow_agent` update the global prompt and routing instructions.
8. `voiceflow_document` add the knowledge base sources the user gave you.
9. `voiceflow_environment` compile.

Keep a build log (what was created, IDs, anything skipped) in the work directory.

## Phase 4: Verify and report

1. For each test case, run a test conversation (`voiceflow_conversation`) and record which
   skill answered.
2. Write `<name>.migration-report.md`: what was rebuilt, routing test results, secrets the
   user must fill, KB sources still missing, and the manual review list from the audit.
3. Tell the user what to check in the Creator before publishing. Do not publish for them.
