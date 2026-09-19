# Baseten integration — pretrained planner scaffold

**Status: client, custom server adapter, and configuration exist; live validation is pending.**
This is pretrained inference setup, not a fine-tune. The target is
[bounded guitar rehearsal](../DESIGN.md) with local motion authority and optional separate
audio-model assessment. No deployment or hardware validation is claimed by this README.

## 1. Existing pieces and validation boundary

- [`agent/backends/baseten.py`](../agent/backends/baseten.py) is a direct standard-library
  HTTP client for a **custom `/predict` contract**. It does not require the OpenAI SDK.
- [`baseten_guitar_agent/config.yaml`](baseten_guitar_agent/config.yaml) names
  `Qwen/Qwen2.5-VL-7B-Instruct`, vLLM dependencies, and an A10G resource configuration.
- [`model/model.py`](baseten_guitar_agent/model/model.py) was added concurrently during this
  review. It supplies Truss `load`/`predict`, constructs the guitar prompt, passes the latest
  image to Qwen, and normalizes generated JSON/tool calls into the client's response shape.

**These files are not evidence of a successful deployment or end-to-end test.** Verify
model/dependency loading, the exact payload/response, images, truncation/errors, and local
admission before physical use. Do not silently mix this custom `/predict` contract with
hosted Model APIs or native Chat Completions shapes; the adapter is the explicit translation.

## 2. Capabilities and product claims

Qwen2.5-VL is an image/text model. The current client sends JPEGs and text, **not raw audio**.
An audio score supplied by local code is not the model listening to a clip. For the optional
critic path, select a verified audio-capable endpoint and implement recording/export and
assessment handling separately; see [sensing](../sense/README.md).

The config describes a pretrained checkpoint, not guitar-specific trained weights. GPU
serving is not weight training. [FINETUNING.md](../FINETUNING.md) is deferred research;
H100 fine-tuning, LoRA, or a new classifier are not deployment prerequisites.

The CLI's current default remains `claude`; use `--backend baseten` explicitly for Baseten
requests. Astra/Claude traffic is not Baseten traffic, and a Baseten-hosted Astra endpoint
is not assumed.

## 3. Current client configuration

Keys may be supplied via the environment; the client also reads `guitar/.env` then the
repository-root `.env`, without replacing existing nonempty environment values. Never
commit, print, screenshot, or send credentials in model context.

| Setting | Current client behavior |
|---|---|
| `BASETEN_API_KEY` | Primary credential; `BASETEN` is an alias |
| `BASETEN_MODEL_ID` | Baseten deployment/model ID; the shared CLI's `--model` also maps to this ID, not a Hugging Face slug |
| `BASETEN_ENV` | Defaults to `development` |
| `BASETEN_MODEL_URL` | Explicit URL override |
| `BASETEN_TIMEOUT_S` | Defaults to 180 seconds; not a total attempt/physical-hold deadline |

Without an explicit URL, the client constructs
`https://model-<id>.api.baseten.co/<environment>/predict` and sends `Authorization: Api-Key ...`.
That describes current code, not a universal endpoint/auth recipe. Confirm the actual
Baseten-generated URL/auth for the selected deployment before calling it. In particular,
changing the URL alone does not convert the body to `/v1/chat/completions` format.

## 4. Custom client/server contract

The client sends the whole accumulated conversation each turn. Example **shape only**:

```json
{
  "session_id": "example-session",
  "system": "Example role/task instructions",
  "tools": [
    {"name": "look", "description": "Observe without motion", "parameters": {"type": "object", "properties": {}, "required": [], "additionalProperties": false}}
  ],
  "messages": [
    {"role": "user", "text": "Synthetic state: ready"},
    {"role": "assistant", "text": "Inspect first", "tool_calls": [{"id": "call_1", "name": "look", "args": {}}]},
    {"role": "tool", "tool_call_id": "call_1", "name": "look", "text": "Synthetic observation", "is_error": false}
  ],
  "generation": {"effort": "medium"}
}
```

User/tool messages can additionally contain `image_jpeg_b64`. The current assistant-history
entry uses `args` from the local dataclass; it is not native OpenAI tool-call serialization.
The current server translates this into a prompt containing the tool schemas and the last
24 transcript entries, with the most recent image. There is no raw audio field. The client
sends `generation.effort`, but the server currently reads only max-token/temperature/top-p
settings from `generation`; do not claim that the shared CLI's effort flag changes this model.

Expected response, directly or inside `model_output` (illustrative, not a real result):

```json
{
  "text": "Request one observation before proceeding.",
  "tool_calls": [{"id": "call_2", "name": "look", "arguments": {}}],
  "stop": "tool_use",
  "usage": {}
}
```

Do not return stock `choices[0].message` and assume this client parses it. Current JSON
formatting is requested in the prompt, not guaranteed by constrained decoding. The parser
can drop malformed calls or substitute empty arguments. Finish/refusal/truncation, input
bounds, and normalization need explicit tests; local semantic validation is still required.
The client sends context; a session ID is not server-side learning or persistent memory.

## 5. Validation before any physical use

1. Test the implemented custom server/client contract with mocks, without keys or hardware.
2. Pin/review model/runtime dependencies, input limits, and remote-code requirements.
3. Approve account access and serving spend before deployment; idle GPUs can bill.
4. Deploy through the selected supported Baseten/Truss workflow and verify health **and**
   the exact synthetic request/response, not just that a model page exists.
5. Use a non-motion request with no media upload first. Only after that, test fake execution.
6. Camera/audio upload and real hardware are separate opt-ins, with the local qualification
   gates in [STATUS.md](../STATUS.md) and [operator instructions](../../AGENTS.md).

A provider-only diagnostic, **only after a matching endpoint is working and spend approved**:

```python
# Run from guitar/ using its environment; this makes a billed inference request.
# It does not connect an arm, capture media, or dispatch any returned tool.
from agent.backends.baseten import BasetenBackend

backend = BasetenBackend()
turn = backend.begin(
    system="Synthetic endpoint test. End the request; no robot is connected.",
    tool_specs=[{
        "name": "done",
        "description": "Finish the synthetic test",
        "parameters": {
            "type": "object",
            "properties": {"reason": {"type": "string"}},
            "required": ["reason"],
            "additionalProperties": False,
        },
    }],
    text="Return done with a short reason.",
    image_jpeg=None,
)
print(turn.stop, [call.name for call in turn.calls])
```

The previous pluck-role fake smoke command required a `pluck_arm` map that is not supplied.
Do not claim it is a ready-made test or switch to real hardware to bypass that error.
A valid provider response alone does not establish safe execution or improvement from rehearsal.

## References

- [Baseten model development](https://docs.baseten.co/development/model/overview)
- [Custom model class](https://docs.baseten.co/development/model/model-class)
- [Model APIs](https://docs.baseten.co/inference/model-apis/overview)
- [Audio-capable endpoints](https://docs.baseten.co/inference/model-apis/audio)

These document platform options, not team entitlement, deployment success, model suitability,
or a verified audio critique of this guitar.
