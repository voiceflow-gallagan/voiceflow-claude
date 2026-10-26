# v3 to v4 concept mapping

Summarised from the Voiceflow [V4 migration guide](https://www.voiceflow.com/docs/v4-migration-guide)
(sections 6 and 8). Check the guide for changes before relying on a row.

| v3 concept | v4 equivalent | Notes |
|---|---|---|
| Intent | Agent instructions + skill name and trigger | No training utterances. Write one routing rule per intent. |
| Entity / slot | Variables + structured outputs | Use structured outputs on playbooks or tools for extraction. |
| Flow / topic | Playbook or workflow | Playbook when the path can vary, workflow when order must be guaranteed. |
| Component | Workflow step (sub-workflow) or Crew step | |
| AI Response step | Message step (Prompt mode) or playbook | Message for one reply, playbook for multi-turn. |
| AI Set step | Structured output, Operator step or playbook | |
| Choice step | Buttons step, Operator step or playbook | |
| Capture step | Listen step or playbook | Playbook for conversational extraction. |
| Code step | Function tool (Function step) or Code step | Function tools are reusable. |
| API block | API tool (API step) | Reusable across skills. |
| Speak / Text step | Message step | |
| Set step | Set step | Unchanged. |
| Condition step | Condition step or Operator step | |
| Random step | Message step with variants | |
| Go to flow | Workflow step or playbook step | |
| No match handler | Global no-match (Behaviour) | Generative or scripted. |
| No reply handler | Global no-reply (Behaviour) | |
| NLU training | Routing by instructions | Nothing to train. |
| Launch event | Initialization workflow + start message | |

## Patterns from the guide

- **Intent-triggered FAQ flow** becomes knowledge base content plus an instruction. No skill needed.
- **Data collection flow** (text + capture, repeated) becomes one playbook with a structured output.
- **Conditional routing flow** becomes agent instructions, or a workflow with an Operator step.
- **API-heavy flow with strict order** stays a workflow with API and Function steps.

The guide's main advice: do not replicate a v3 agent one to one. Use the v3 project as the
specification of what the agent must do.
