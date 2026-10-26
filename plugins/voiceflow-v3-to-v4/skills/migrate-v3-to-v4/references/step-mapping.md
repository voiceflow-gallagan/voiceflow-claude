# v3 step types and their v4 targets

Step `type` values found in `.vf` exports, as reported by `scripts/vf_audit.py`.
"Redesign" is the default mode; "faithful" keeps a workflow per v3 topic.

| `type` | v3 step | Redesign target | Faithful target |
|---|---|---|---|
| `start` | Start | Initialization workflow or start message | Workflow start |
| `message`, `text` | Text / Message | Folded into the global prompt or playbook instructions | Message step |
| `speak` | Speak (voice) | As above, voice project | Message step |
| `visual`, `card`, `cardV2`, `carousel` | Visual / Card / Carousel | Card or Carousel system tool | Card / Carousel step |
| `buttons` | Buttons | Buttons system tool | Buttons step |
| `interaction`, `choice` | Choice | Playbook decides from the user's answer | Buttons step or Operator step |
| `prompt` | Prompt (listen for intents) | Agent instructions | Listen step + Operator step |
| `captureV2`, `capture` | Capture | Playbook with structured output | Listen step + Set step |
| `intent`, `trigger` | Intent trigger | Instruction line routing to the skill | Instruction line routing to the workflow |
| `command` | Global intent command | Instruction line | Instruction line |
| `goTo`, `goToNode` | Go to intent / block | Instruction line or Playbook step | Workflow step or link |
| `component`, `flow` | Component | Playbook or sub-workflow | Workflow step |
| `exit` | End | End system tool | End |
| `ifV2`, `if` | Condition | Playbook instructions | Condition step |
| `setV2`, `set-v3`, `set` | Set | Set step or initialization workflow | Set step |
| `random`, `randomV2` | Random | Message variants | Message step with variants |
| `api`, `integration` | API / Integration | API tool attached to the skill | API step |
| `code` | Code | Function tool | Function step (or Code step) |
| `generative` | AI Response (deprecated) | Playbook instructions or Message step in Prompt mode | Message step in Prompt mode |
| `ai_set` | AI Set (deprecated) | Structured output | Operator step or playbook |
| `trace` | Custom action | Manual review (client integration) | Manual review |
| `actions` | Port actions | Follows its parent step | Port actions |
| `markup_text`, `markup_image` | Canvas notes | Ignored | Ignored |

Unknown types are listed in the audit under "Unknown step types". Add them here when you
meet a new one.
