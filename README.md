# voiceflow-claude

Claude plugins for people who build agents on [Voiceflow](https://www.voiceflow.com).

> Community project, not an official Voiceflow product.

## Plugins

### voiceflow-v3-to-v4

Rebuilds a Voiceflow v3 (legacy) project as a v4 agent, starting from its `.vf` export.
Voiceflow has no automatic converter and recommends rebuilding rather than copying
([V4 migration guide](https://www.voiceflow.com/docs/v4-migration-guide)). The plugin
does that rebuild with you:

1. **Audit.** Reads the `.vf` file and lists topics, components, intents and utterances,
   entities, variables, API calls, AI steps and anything that needs a human.
2. **Plan.** Proposes a v4 design: a global prompt, routing instructions, playbooks,
   workflows, tools and test cases. Two modes: agentic redesign (default) or a faithful
   port where each topic becomes a workflow. Nothing is built until you approve the plan.
3. **Build.** Creates a new v4 project through the Voiceflow MCP server, or the `vf` CLI
   when you have a terminal. Your v3 project is never modified.
4. **Verify.** Runs test conversations for each former intent and writes a migration report.

Status: **0.1.0**. The audit is tested on chat and voice exports with schema versions 4 to 13.
The build phase is guided by the skill and still being tested; review the result in the
Creator before publishing.

## Install

Claude Code:

```bash
claude plugin marketplace add voiceflow-gallagan/voiceflow-claude
claude plugin install voiceflow-v3-to-v4@voiceflow-claude
```

Other Claude apps that support plugins: add this repository as a plugin marketplace and
install `voiceflow-v3-to-v4` from it.

Then connect the Voiceflow MCP server (`https://mcp.voiceflow.com/mcp`, OAuth sign-in), see
[Set up the Voiceflow MCP server](https://www.voiceflow.com/docs/mcp/setup). The `vf` CLI is
optional: [Install the vf CLI](https://www.voiceflow.com/docs/cli/install).

## Use

1. In the Voiceflow dashboard, export your v3 project as a `.vf` file.
2. Give Claude the file and ask: "Migrate this Voiceflow v3 project to v4".

You can run the audit on its own, with Python 3 and no dependencies:

```bash
python3 plugins/voiceflow-v3-to-v4/skills/migrate-v3-to-v4/scripts/vf_audit.py my-project.vf --out ./audit
```

## What does not carry over

- **Knowledge base documents.** A `.vf` export does not contain them. Keep your source
  URLs and files ready.
- **Credentials.** API keys stored in v3 steps are redacted, never copied. The plugin
  creates empty secrets for you to fill in. If your `.vf` contained real keys, rotate them.
- **Custom actions and client-side integrations.** Listed for manual review.

## Privacy

The audit runs locally. Do not commit `.vf` files to a repository: they can contain API
keys and customer data. This repo's `.gitignore` excludes them.

## License

MIT
