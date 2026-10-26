# Reading a .vf export by hand

A `.vf` file is JSON. Use this when no shell is available to run `scripts/vf_audit.py`.

## Top level

- `project`: `name`, `type` (`chat` / `voice`, missing in older files), `platform`
  (`webchat`, `chatbot`, voice platforms).
- `version`: `_version` (schema version; seen from 4 to 13), `platformData`, `topics`,
  `components`, `variables`, `settings.intentClassification`.
- `diagrams`: object keyed by diagram ID. Each has `name`, `type` (`TOPIC`, `COMPONENT`,
  `TEMPLATE`) and `nodes`.
- CMS tables (newer exports): `intents`, `utterances`, `entities`, `entityVariants`,
  `variables`, `responses`, `responseDiscriminators`, `responseMessages`. v4 tables
  (`agents`, `apiTools`, `functions`, `workflows`…) are present but empty for a v3 project.

## Intents and entities

`version.platformData.intents[]` holds `key`, `name` and `inputs[].text` (utterances).
`version.platformData.slots[]` holds entities: `key`, `name`, `type.value`, `inputs`
(comma-separated value and synonyms). Fall back to the CMS tables when these are empty.

## Steps

Each diagram's `nodes` contains `block` nodes whose `data.steps` lists step node IDs in
order. Every node has `type` and `data`. Links are in `data.portsV2` (`builtIn`, `byKey`,
`dynamic`), each port with a `target` node ID. See `step-mapping.md` for the types.

- `message` steps hold `data.messageID`. Resolve it through `responseDiscriminators`
  (`responseID` = messageID) then `responseMessages` (`discriminatorID`).
- `text` steps hold Slate rich text in `data.texts[].content`.
- AI steps (`generative`, `ai_set`) hold `prompt`, `system`, `model`, `temperature`, `maxTokens`.

## Variables in text

References look like `{{[name].something}}`. Keep the name in brackets and write `{name}`.

## Credentials

Treat as secret: any API step header other than Content-Type, Accept or User-Agent whose
value is 12 characters or longer and contains no `{{` variable reference, plus anything
that looks like an API key in URLs, bodies or code. Never repeat the value.
