"""Baseten Truss model for the Guitarra text/state planner.

Input contract (sent by agent.backends.baseten):
    {
      "session_id": "...",
      "system": "role/task prompt",
      "tools": [{"name": "look", "description": "...", "parameters": {...}}, ...],
      "messages": [
        {"role": "user", "text": "..."},
        {"role": "assistant", "text": "...", "tool_calls": [...]},
        {"role": "tool", "tool_call_id": "...", "name": "fret", "text": "{...}",
         "is_error": false}
      ],
      "generation": {"effort": "low|medium|high"}
    }

Optional diagnostic camera snapshots may appear as ``image_jpeg_b64`` in messages only
when the local CLI is run with explicit ``--camera``. This text planner intentionally ignores
image bytes; camera input is not part of the normal project path.

Output contract:
    {"text": "narration", "tool_calls": [{"id": "...", "name": "...", "arguments": {...}}],
     "stop": "tool_use|end_turn", "usage": {...}}

The deployed model only emits proposed tool calls. The local agent loop executes them through
its guard layer; Baseten never talks to robot hardware directly.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any
from uuid import uuid4


MODEL_ID = os.environ.get("HF_MODEL_ID", "Qwen/Qwen2.5-7B-Instruct")

OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "text": {"type": "string"},
        "tool_calls": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "name": {"type": "string"},
                    "arguments": {"type": "object"},
                },
                "required": ["name", "arguments"],
                "additionalProperties": True,
            },
        },
        "stop": {"type": "string", "enum": ["tool_use", "end_turn", "refusal"]},
    },
    "required": ["text", "tool_calls", "stop"],
    "additionalProperties": True,
}


class Model:
    def __init__(self, **_: Any):
        self.llm = None
        self.tokenizer = None
        self.sampling_params_cls = None
        self.default_max_tokens = int(os.environ.get("MAX_NEW_TOKENS", "512"))
        self.default_temperature = float(os.environ.get("TEMPERATURE", "0.1"))
        self.default_top_p = float(os.environ.get("TOP_P", "0.9"))

    def load(self) -> None:
        # Imports live here so local unit checks can import this file without GPU dependencies.
        from transformers import AutoTokenizer
        from vllm import LLM, SamplingParams

        hf_token = os.environ.get("hf_access_token") or os.environ.get("HF_TOKEN")
        if hf_token:
            os.environ.setdefault("HF_TOKEN", hf_token)

        self.tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, trust_remote_code=True, token=hf_token)
        self.sampling_params_cls = SamplingParams
        self.llm = LLM(
            model=MODEL_ID,
            trust_remote_code=True,
            max_model_len=int(os.environ.get("MAX_MODEL_LEN", "8192")),
            gpu_memory_utilization=float(os.environ.get("GPU_MEMORY_UTILIZATION", "0.90")),
        )

    def predict(self, model_input: dict[str, Any]) -> dict[str, Any]:
        if self.llm is None or self.tokenizer is None or self.sampling_params_cls is None:
            raise RuntimeError("model is not loaded")

        prompt = build_controller_prompt(model_input)
        llm_input = self._llm_input(prompt)

        generation = model_input.get("generation", {}) if isinstance(model_input.get("generation", {}), dict) else {}
        max_tokens = int(generation.get("max_tokens") or self.default_max_tokens)
        temperature = float(generation.get("temperature") or self.default_temperature)
        top_p = float(generation.get("top_p") or self.default_top_p)
        sampling = self._sampling_params(max_tokens=max_tokens, temperature=temperature, top_p=top_p)

        result = self.llm.generate([llm_input], sampling)[0]
        raw = result.outputs[0].text.strip()
        parsed = parse_model_json(raw)
        parsed.setdefault("raw", raw)
        parsed["usage"] = token_usage(result)
        return parsed

    def _llm_input(self, prompt: str) -> str:
        messages = [
            {"role": "system", "content": "You are a JSON-only planner. Return exactly one JSON object."},
            {"role": "user", "content": prompt},
        ]
        return self.tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)

    def _sampling_params(self, *, max_tokens: int, temperature: float, top_p: float) -> Any:
        kwargs: dict[str, Any] = {"max_tokens": max_tokens, "temperature": temperature, "top_p": top_p}
        if os.environ.get("GUIDED_JSON", "1") != "0":
            kwargs["guided_json"] = OUTPUT_SCHEMA
        try:
            return self.sampling_params_cls(**kwargs)
        except TypeError:
            # Older vLLM versions may not support guided_json. The prompt and parser still
            # preserve the contract, but deployment validation must measure malformed output.
            kwargs.pop("guided_json", None)
            return self.sampling_params_cls(**kwargs)


def build_controller_prompt(model_input: dict[str, Any]) -> str:
    system = str(model_input.get("system", ""))
    tools = model_input.get("tools", [])
    messages = model_input.get("messages", [])
    if not isinstance(tools, list):
        tools = []
    if not isinstance(messages, list):
        messages = []

    return "\n".join([
        "You are the decision model for a local robot-guitar rehearsal loop.",
        "The robot is NOT connected to you. You only choose among the provided tools; a local safety layer validates and runs them.",
        "Normal input is text/state only. Camera input is disabled unless the transcript explicitly says otherwise; do not claim visual evidence.",
        "Never invent tools, raw joint angles, unsupported notes, calibration changes, grip changes, or safety overrides.",
        "In this project, release means lift off a guitar string; it never means opening or loosening a gripper.",
        "Call at most one tool per turn unless the local prompt explicitly asks for multiple and the state is certain.",
        "Before a tool call, put one concise observation/reason in the text field, based only on supplied state/audio/tool results.",
        "",
        "Return exactly one JSON object and no markdown fences. Shape:",
        json.dumps({
            "text": "what was observed and why this tool is next",
            "tool_calls": [{"name": "look", "arguments": {}}],
            "stop": "tool_use",
        }),
        "If the goal is complete, unsafe, unsupported, or stuck, call done when that tool is available. If no tool is needed, use an empty tool_calls array and stop=end_turn.",
        "",
        "SYSTEM TASK:",
        system,
        "",
        "AVAILABLE TOOLS (JSON Schema):",
        json.dumps(tools, ensure_ascii=False),
        "",
        "TRANSCRIPT:",
        transcript_text(messages),
        "",
        "Now produce the next JSON object.",
    ])


def transcript_text(messages: list[Any]) -> str:
    lines: list[str] = []
    for i, msg in enumerate(messages[-24:], start=max(1, len(messages) - 23)):
        if not isinstance(msg, dict):
            continue
        role = msg.get("role", "unknown")
        image_note = " [optional image omitted by text-only planner]" if msg.get("image_jpeg_b64") else ""
        if role == "assistant":
            calls = msg.get("tool_calls", [])
            lines.append(f"{i}. assistant{image_note}: {msg.get('text', '')} tool_calls={json.dumps(calls, ensure_ascii=False)}")
        elif role == "tool":
            err = " ERROR" if msg.get("is_error") else ""
            lines.append(f"{i}. tool {msg.get('name', 'unknown')}#{msg.get('tool_call_id', '?')}{err}{image_note}: {msg.get('text', '')}")
        else:
            lines.append(f"{i}. {role}{image_note}: {msg.get('text', '')}")
    return "\n".join(lines)


def parse_model_json(raw: str) -> dict[str, Any]:
    obj_text = extract_json_object(raw)
    try:
        obj = json.loads(obj_text)
    except Exception as exc:  # noqa: BLE001 - return parse detail to local recorder
        return {"text": raw, "tool_calls": [], "stop": "end_turn", "parse_error": str(exc)}
    if not isinstance(obj, dict):
        return {"text": raw, "tool_calls": [], "stop": "end_turn", "parse_error": "top-level JSON was not an object"}

    text = str(obj.get("text", ""))
    raw_calls = obj.get("tool_calls", obj.get("calls", [])) or []
    calls = normalize_tool_calls(raw_calls)
    stop = str(obj.get("stop") or ("tool_use" if calls else "end_turn"))
    return {"text": text, "tool_calls": calls, "stop": stop}


def extract_json_object(raw: str) -> str:
    raw = raw.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, flags=re.S)
    if fenced:
        return fenced.group(1)
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        return raw[start:end + 1]
    return raw


def normalize_tool_calls(raw_calls: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_calls, list):
        return []
    calls: list[dict[str, Any]] = []
    for item in raw_calls:
        if not isinstance(item, dict):
            continue
        fn = item.get("function") if isinstance(item.get("function"), dict) else {}
        name = item.get("name") or fn.get("name")
        if not name:
            continue
        args = item.get("arguments", item.get("args", item.get("input", fn.get("arguments", {}))))
        if isinstance(args, str):
            try:
                args = json.loads(args or "{}")
            except json.JSONDecodeError:
                args = {}
        if not isinstance(args, dict):
            args = {}
        calls.append({"id": str(item.get("id") or item.get("call_id") or f"call_{uuid4().hex[:10]}"),
                      "name": str(name), "arguments": args})
    return calls


def token_usage(result: Any) -> dict[str, int]:
    usage: dict[str, int] = {}
    prompt_ids = getattr(result, "prompt_token_ids", None)
    if prompt_ids is not None:
        usage["input"] = len(prompt_ids)
    try:
        usage["output"] = len(result.outputs[0].token_ids)
    except Exception:  # noqa: BLE001
        pass
    return usage
