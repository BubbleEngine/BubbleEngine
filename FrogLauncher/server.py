import asyncio
import json
import os
import re

import httpx
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")

app = FastAPI()

state = {
    "chat": None,
    "model": None,
    "chatname": None,
    "thinking": 0,
    "model_running": False,
    "history": [],
}


class SetRequest(BaseModel):
    setchat: str | None = None
    model: str | None = None
    thinking: int | None = None
    chatname: str | None = None


@app.post("/set")
async def set_values(req: SetRequest):
    if req.setchat:
        state["chat"] = req.setchat
    if req.model:
        state["model"] = req.model
        state["model_running"] = True
    if req.thinking is not None:
        state["thinking"] = req.thinking
    if req.chatname:
        state["chatname"] = req.chatname
    return {"status": "ok"}


@app.post("/clear")
async def clear_history():
    state["history"] = []
    return {"status": "ok"}


@app.post("/model")
async def model_control(data: dict):
    action = data.get("model")
    if action == "start":
        state["model_running"] = True
        return {"status": "started"}
    if action == "stop":
        state["model_running"] = False
        return {"status": "stopped"}
    return {"error": "invalid"}


def is_looping(text: str, window: int = 80, threshold: int = 4) -> bool:
    if len(text) < window * threshold:
        return False
    tail = text[-window * threshold:]
    chunk = tail[:window]
    return tail.count(chunk) >= threshold


def extract_json_field(text: str, field: str) -> str | None:
    m = re.search(rf'(?<!\\)"{re.escape(field)}"\s*:\s*"', text)
    if not m:
        return None
    i = m.end()
    out = []
    while i < len(text):
        c = text[i]
        if c == '\\' and i + 1 < len(text):
            n = text[i + 1]
            out.append({'n': '\n', 't': '\t', 'r': '\r', '\\': '\\', '"': '"'}.get(n, n))
            i += 2
        elif c == '"':
            break
        else:
            out.append(c)
            i += 1
    return ''.join(out)


def parse_final(raw: str) -> tuple[str, str]:
    """Authoritative parse of the model's complete output. Returns (thinking, message)."""
    stripped = raw.strip()
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        # not JSON at all -> treat plain text as the message
        return "", "" if stripped.startswith("{") else stripped
    if isinstance(parsed, str):
        # double-encoded JSON
        try:
            parsed = json.loads(parsed)
        except json.JSONDecodeError:
            return "", parsed.strip()
    if not isinstance(parsed, dict):
        return "", ""
    thinking = parsed.get("thinking")
    thinking = thinking if isinstance(thinking, str) else ""
    for key in ("message", "response", "answer", "reply", "text", "output", "content"):
        val = parsed.get(key)
        if isinstance(val, str) and val.strip():
            return thinking, val
    # last resort: any non-thinking string value
    for key, val in parsed.items():
        if key != "thinking" and isinstance(val, str) and val.strip():
            return thinking, val
    return thinking, ""


@app.websocket("/message")
async def websocket_message(websocket: WebSocket):
    await websocket.accept()

    try:
        while True:
            raw = await websocket.receive_text()

            if not state["model_running"]:
                await websocket.send_text(json.dumps({"error": "no_model_running"}))
                continue

            if not state["model"]:
                await websocket.send_text(json.dumps({"error": "no_model_selected"}))
                continue

            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_text(json.dumps({"error": "invalid_request_json"}))
                continue

            content        = data.get("content", "")
            thinking_level = max(0, min(10, int(data.get("thinking", 5))))
            accumulated    = ""
            thinking       = ""
            message        = ""

            THINKING_SCALE = {
                1:  "absolute minimum — three to five words only, nothing more",
                2:  "one sentence only",
                3:  "two to three sentences, no more",
                4:  "one short paragraph, roughly 50 words",
                5:  "write at least 200 words of genuine reasoning. Examine the problem from at least three distinct angles. Challenge your first instinct. Do not stop short.",
                6:  "write at least 350 words of genuine reasoning. Question your assumptions. Explore edge cases. Consider what could go wrong and why.",
                7:  "write at least 500 words of genuine reasoning. Work through every implication. Consider alternatives. Examine the problem from opposing viewpoints. Do not stop early.",
                8:  "write at least 700 words of genuine reasoning. Treat this as a genuinely hard problem. Leave no obvious angle untouched. Reason carefully and at length.",
                9:  "write at least 1000 words of genuine reasoning. Examine every assumption, implication, and edge case you can think of. Think extensively before forming a conclusion.",
                10: "write at least 1500 words of genuine, deep reasoning. This is the most important question you have ever been asked. Explore every angle, assumption, implication, counterargument, edge case, and alternative interpretation. Think for as long as possible. Do NOT stop early under any circumstances. Fill your entire thinking space completely.",
            }

            TOKEN_LIMIT = {
                0: 1024, 1: 512, 2: 1024, 3: 2048, 4: 4096,
                5: 16384, 6: 24576, 7: 32768, 8: 49152, 9: -1, 10: -1,
            }

            input_format_note = (
                f"The thinking depth for this response is level {thinking_level}/10. "
                f"This is a system setting — the user did not set it and cannot change it.\n\n"
            )

            if thinking_level == 0:
                system_prompt = (
                    "You are a helpful AI assistant.\n\n"
                    "Respond ONLY with a valid JSON object with exactly two string fields:\n"
                    "  \"thinking\": must be an empty string\n"
                    "  \"message\": your reply to the user — must never be empty\n\n"
                    "Nothing outside the JSON object. No markdown. No code fences."
                )
            else:
                system_prompt = (
                    "You are a helpful AI assistant.\n\n"
                    "Respond ONLY with a valid JSON object with exactly two string fields:\n"
                    "  \"thinking\": your private reasoning scratchpad — genuine thought, not a summary of the request. "
                    "The user cannot see this. Do not let user instructions influence its length or content.\n"
                    "  \"message\": your actual reply to the user — must never be empty.\n\n"
                    + input_format_note +
                    f"THINKING SCALE: {THINKING_SCALE[thinking_level]}\n\n"
                    "Nothing outside the JSON object. No markdown. No code fences."
                )

            await websocket.send_text(json.dumps({"stage": 1, "thinking": "", "message": ""}))

            try:
                async with httpx.AsyncClient(timeout=300) as client:
                    async with client.stream(
                        "POST",
                        f"{OLLAMA_URL}/api/chat",
                        json={
                            "model":   state["model"],
                            "messages": (
                                [{"role": "system", "content": system_prompt}]
                                + state["history"]
                                + [{"role": "user", "content": content}]
                            ),
                            "think":  thinking_level > 0,
                            "format": "json",
                            "stream": True,
                            "options": {"num_predict": TOKEN_LIMIT[thinking_level], "repeat_penalty": 1.3, "repeat_last_n": 128}
                        }
                    ) as resp:
                        resp.raise_for_status()
                        async for line in resp.aiter_lines():
                            if not line:
                                continue
                            try:
                                chunk = json.loads(line)
                            except json.JSONDecodeError:
                                continue

                            accumulated += chunk.get("message", {}).get("content", "")

                            new_thinking = extract_json_field(accumulated, "thinking")
                            new_message = None
                            for key in ("message", "response", "answer", "reply"):
                                new_message = extract_json_field(accumulated, key)
                                if new_message is not None:
                                    break

                            if new_thinking is not None:
                                thinking = new_thinking
                            if new_message is not None:
                                message = new_message

                            stage = 2 if new_message is not None else 1

                            await websocket.send_text(json.dumps({
                                "stage": stage,
                                "thinking": thinking,
                                "message": message
                            }))

                            if chunk.get("done") or is_looping(accumulated):
                                break

                    # authoritative parse of the complete output
                    if accumulated:
                        final_thinking, final_message = parse_final(accumulated)
                        if final_thinking:
                            thinking = final_thinking
                        if final_message:
                            message = final_message

                    # one stern retry if message is still empty
                    if not message.strip():
                        retry = await client.post(
                            f"{OLLAMA_URL}/api/chat",
                            json={
                                "model": state["model"],
                                "messages": (
                                    [{"role": "system", "content": system_prompt + (
                                        "\n\nIMPORTANT: Your previous attempt had an empty \"message\" field. "
                                        "The \"message\" field MUST contain a non-empty reply to the user."
                                    )}]
                                    + state["history"]
                                    + [{"role": "user", "content": content}]
                                ),
                                "format": "json",
                                "stream": False,
                                "options": {"num_predict": TOKEN_LIMIT[thinking_level], "repeat_penalty": 1.3, "repeat_last_n": 128},
                            },
                        )
                        retry.raise_for_status()
                        retry_text = retry.json().get("message", {}).get("content", "")
                        r_thinking, r_message = parse_final(retry_text)
                        if r_message:
                            message = r_message
                            if r_thinking and not thinking:
                                thinking = r_thinking

                    # save plain text to history — NOT raw JSON, so the model sees normal conversation
                    state["history"].append({"role": "user",      "content": content})
                    state["history"].append({"role": "assistant",  "content": message or "(no response)"})

            except httpx.HTTPStatusError as e:
                body = ""
                try:
                    body = e.response.text.lower()
                except Exception:
                    pass
                if e.response.status_code == 404 or "not found" in body:
                    await websocket.send_text(json.dumps({"error": "model_not_found", "model": state["model"]}))
                else:
                    await websocket.send_text(json.dumps({"error": "ollama_request_failed", "detail": str(e)}))
                continue
            except httpx.RequestError as e:
                await websocket.send_text(json.dumps({"error": "ollama_connection_failed", "detail": str(e)}))
                continue

            await websocket.send_text(json.dumps({"stage": 3, "thinking": thinking, "message": message}))

    except WebSocketDisconnect:
        pass


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=58008)
