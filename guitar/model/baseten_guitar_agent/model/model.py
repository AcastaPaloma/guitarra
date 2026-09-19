"""Baseten Truss model for the Guitarra robot agent.

Input contract (sent by agent.backends.baseten):
    {
      "session_id": "...",
      "system": "role/task prompt",
      "tools": [{"name": "look", "description": "...", "parameters": {...}}, ...],
      "messages": [
        {"role": "user", "text": "...", "image_jpeg_b64": "optional"},
        {"role": "assistant", "text": "...", "tool_calls": [...]},
        {"role": "tool", "tool_call_id": "...", "name": "fret", "text": "{...}",
         "is_error": false, "image_jpeg_b64": "optional"}
      ],
      "generation": {"effort": "low|medium|high"}
    }

Output contract:
    {"text": "narration", "tool_calls": [{"id": "...", "name": "...", "arguments": {...}}],
     "stop": "tool_use|end_turn", "usage": {...}}

The deployed model only emits proposed tool calls. The local agent loop executes them through
its guard layer; Baseten never talks to robot hardware directly.
"""
from __future__ import annotations

import base64
import json
import os
import re
from io import BytesIO
from typing import Any
from uuid import uuid4


MODEL_ID = os.environ.get("HF_MODEL_ID", "Qwen/Qwen2.5-VL-7B-Instruct")


class Model:
    def __init__(self, **_: Any):
        self.llm = None
        self.processor = None
        self.sampling_params_cls = None
        self.default_max_tokens = int(os.environ.get("MAX_NEW_TOKENS", "768"))
        self.default_temperature = float(os.environ.get("TEMPERATURE", "0.2"))
        self.default_top_p = float(os.environ.get("TOP_P", "0.9"))

    def load(self) -> None:
        # Imports live here so local unit tests can import this file without GPU dependencies.
        from transformers import AutoProcessor
        from vllm import LLM, SamplingParams

        hf_token = os.environ.get("hf_access_token") or os.environ.get("HF_TOKEN")
        if hf_token:
            # vLLM/Transformers both know this conventional env var.
            os.environ.setdefault("HF_TOKEN", hf_token)

        self.processor = AutoProcessor.from_pretrained(MODEL_ID, trust_remote_code=True, token=hf_token)
        self.sampling_params_cls = SamplingParams
        self.llm = LLM(
            model=MODEL_ID,
            trust_remote_code=True,
            max_model_len=int(os.environ.get("MAX_MODEL_LEN", "8192")),
            gpu_memory_utilization=float(os.environ.get("GPU_MEMORY_UTILIZATION", "0.90")),
            limit_mm_per_prompt={"image": int(os.environ.get("MAX_IMAGES_PER_PROMPT", "1"))},
        )

    def predict(self, model_input: dict[str, Any]) -> dict[str, Any]:
        if self.llm is None or self.processor is None or self.sampling_params_cls is None:
            raise RuntimeError("model is not loaded")

        prompt = build_controller_prompt(model_input)
        image = latest_image(model_input.get("messages", []))
        llm_input = self._llm_input(prompt, image)

        generation = model_input.get("generation", {}) if isinstance(model_input.get("generation", {}), dict) else {}
        max_tokens = int(generation.get("max_tokens") or self.default_max_tokens)
        temperature = float(generation.get("temperature") or self.default_temperature)
        top_p = float(generation.get("top_p") or self.default_top_p)
        sampling = self.sampling_params_cls(max_tokens=max_tokens, temperature=temperature, top_p=top_p)

        result = self.llm.generate([llm_input], sampling)[0]
        raw = result.outputs[0].text.strip()
        parsed = parse_model_json(raw)
        parsed.setdefault("raw", raw)
        parsed["usage"] = token_usage(result)
        return parsed

    def _llm_input(self, prompt: str, image: Any | None) -> Any:
        if image is None:
            messages = [{"role": "user", "content": [{"type": "text", "text": prompt}]}]
            return self.processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)

        messages = [{"role": "user", "content": [
            {"type": "image", "image": image},
            {"type": "text", "text": prompt},
        ]}]
        chat_prompt = self.processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        return {"prompt": chat_prompt, "multi_modal_data": {"image": image}}


def build_controller_prompt(model_input: dict[str, Any]) -> str:
    system = str(model_input.get("system", ""))
    tools = model_input.get("tools", [])
    messages = model_input.get("messages", [])
    if not isinstance(tools, list):
        tools = []
    if not isinstance(messages, list):
        messages = []

    return "\n".join([
        "You are the decision model for a local robot-guitar control loop.",
        "The robot is NOT connected to you. You only choose among the provided tools; a local safety layer validates and runs them.",
        "Never invent tools or raw joint angles. Never open, loosen, or power-cycle grippers. In this project, release means lift off a guitar string.",
        "Call at most one tool per turn unless the user explicitly asks for a multi-step plan and the observations are certain.",
        "Before a tool call, put one concise observation/reason in the text field.",
        "",
        "Return exactly one JSON object and no markdown fences:",
        json.dumps({
            "text": "what you saw and why this tool is next",
            "tool_calls": [{"name": "look", "arguments": {}}],
            "stop": "tool_use",
        }),
        "If the goal is complete or unsafe/stuck, call the done tool if available. If no tool is needed, use an empty tool_calls array and stop=end_turn.",
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
        image_note = " [image attached]" if msg.get("image_jpeg_b64") else ""
        if role == "assistant":
            calls = msg.get("tool_calls", [])
            lines.append(f"{i}. assistant{image_note}: {msg.get('text', '')} tool_calls={json.dumps(calls, ensure_ascii=False)}")
        elif role == "tool":
            err = " ERROR" if msg.get("is_error") else ""
            lines.append(f"{i}. tool {msg.get('name', 'unknown')}#{msg.get('tool_call_id', '?')}{err}{image_note}: {msg.get('text', '')}")
        else:
            lines.append(f"{i}. {role}{image_note}: {msg.get('text', '')}")
    return "\n".join(lines)


def latest_image(messages: list[Any]) -> Any | None:
    for msg in reversed(messages):
        if isinstance(msg, dict) and msg.get("image_jpeg_b64"):
            return decode_image(str(msg["image_jpeg_b64"]))
    return None


def decode_image(value: str) -> Any:
    from PIL import Image

    # Accept either raw base64 or a data URL.
    if "," in value and value.lstrip().startswith("data:"):
        value = value.split(",", 1)[1]
    data = base64.b64decode(value)
    return Image.open(BytesIO(data)).convert("RGB")


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
    # vLLM exposes token ids on request/output objects; keep this best-effort so version
    # differences do not break inference.
    usage: dict[str, int] = {}
    prompt_ids = getattr(result, "prompt_token_ids", None)
    if prompt_ids is not None:
        usage["input"] = len(prompt_ids)
    try:
        usage["output"] = len(result.outputs[0].token_ids)
    except Exception:  # noqa: BLE001
        pass
    return usage
