# Flow Execution System — Spec

## Flow Format (JSON)

Flows are stored as `.json` files in `flows/`. Each flow has:

```json
{
  "title": "Fill Euro Transfer",
  "description": "Fills the European bank transfer form at localhost:8000/demo and submits",
  "scheme": [
    {
      "field": "full_name",
      "transform": "if value > 35 chars, split at space nearest to middle — first half goes to full_name, second half prepended to full_address",
      "fallback": "skip if missing"
    },
    {
      "field": "iban",
      "fallback": "skip if missing"
    },
    {
      "field": "bic"
    },
    {
      "field": "intermediary_bank"
    },
    {
      "field": "full_address"
    },
    {
      "field": "amount"
    },
    {
      "field": "currency"
    },
    {
      "field": "payment_method"
    },
    {
      "field": "due_date"
    },
    {
      "field": "description",
      "fallback": "skip if missing"
    }
  ],
  "steps": [
    { "type": "navigate", "input_text": "http://localhost:8000/demo" },
    { "type": "wait sec", "wait_sec": 1 },
    { "type": "click and paste", "search_description": "Full Name input field", "input_text": "{full_name}" },
    { "type": "click and paste", "search_description": "IBAN input field", "input_text": "{iban}" },
    { "type": "click and paste", "search_description": "BIC SWIFT input field", "input_text": "{bic}" },
    { "type": "click and paste", "search_description": "Intermediary BIC input field", "input_text": "{intermediary_bank}" },
    { "type": "click and paste", "search_description": "Full Address input field", "input_text": "{full_address}" },
    { "type": "click and paste", "search_description": "Amount input field", "input_text": "{amount}" },
    { "type": "click", "search_description": "Currency dropdown" },
    { "type": "click", "search_description": "EUR option in dropdown" },
    { "type": "click", "search_description": "Payment Method dropdown" },
    { "type": "click", "search_description": "SWIFT option in dropdown" },
    { "type": "click and paste", "search_description": "Due Date input field", "input_text": "{due_date}" },
    { "type": "click", "search_description": "Submit button" },
    { "type": "wait until locate", "search_description": "Add one more button", "timeout_sec": 5 }
  ]
}
```

## Step Types

| type | required fields | description |
|---|---|---|
| `navigate` | `input_text` (URL) | Navigate browser to URL |
| `scroll` | — | Scroll down once |
| `click` | `search_description` | Locate element visually and click |
| `locate` | `search_description` | Assert element is visible, no click |
| `press enter` | — | Press Enter key |
| `click and paste` | `search_description`, `input_text` | Click field then paste text |
| `wait sec` | `wait_sec` | Sleep for N seconds |
| `wait until locate` | `search_description`, `timeout_sec` | Poll until element found or timeout |

`input_text` supports `{field}` placeholders — replaced with row data at runtime.

## Tools

### `find_flow(query: str) -> str`
Searches all flow JSON files by `title` and `description`. Returns a list of matches with title + description. Used by the agent to discover available flows before executing.

### `exec_flow(flow_name: str, csv_path: str) -> str`
Full pipeline:

1. Load flow JSON from `flows/<flow_name>.json`
2. Parse CSV rows
3. Apply `scheme` transforms to each row:
   - Run any `transform` logic (LLM call with the transform string as instruction)
   - Apply `fallback` rule if field is empty/missing
4. Show preview as markdown table — cells that were **actually modified by a transform** are marked with `*`
5. `interrupt()` — wait for user confirmation
6. For each row: execute `steps` sequentially, substituting `{field}` placeholders with row values

## Data Transform Engine

Each `scheme` entry's `transform` is a plain-English instruction evaluated by a small LLM call (no tools). Input: raw field value + full row context. Output: new value(s) — can affect multiple fields (e.g. split name spills into address).

Transforms run before the preview so the user sees exactly what will be typed.

## Preview Format (sent over WebSocket)

```
Ready to execute "Fill Euro Transfer" for 3 rows:

| field            | row 1                          | row 2           | row 3     |
|------------------|--------------------------------|-----------------|-----------|
| full_name        | INDIVIDUAL ENTERP... *split*   | John Smith      | Anna K.   |
| full_address     | *ENTERPRENEUR + original addr* | 5 Main St       | 7 Oak Ave |
| iban             | GE42CD0360000035565825         | DE89370400440532| ...       |
| ...              | ...                            | ...             | ...       |

* = value was modified by a transform rule

Confirm? (yes / no)
```

## Open Questions

- CSV path: user provides file path, or can paste inline data?
- Dropdown steps: currently hardcoded `search_description` per option — should dropdown value come from `{field}` placeholder instead so it's data-driven?
- Should markdown flows (existing format) remain supported for simple cases, or migrate fully to JSON?
- Error handling per row: skip row and continue, or stop and ask user?
