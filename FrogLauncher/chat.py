import json
import shlex
import shutil
import subprocess
import sys
import time
import urllib.request
from websockets.sync.client import connect

if sys.platform == "win32":
    import os; os.system("")

GREEN  = "\033[32m"
RESET  = "\033[0m"
SERVER = "http://127.0.0.1:58008"

COMMANDS = {
    "/?":                    "List all commands",
    "/bye":                  "Exit the chat",
    '/model "name"':         "Switch to a different model",
    "/ollama":               "List available local Ollama models",
    '/ollama -p "name"':     "Pull a model from Ollama",
    "/thinking off":         "Disable thinking (instant response)",
    "/thinking 1-10":        "Set thinking depth (1=minimal, 10=exhaustive)",
    "/clear":                "Clear conversation history",
}


def post(path, body):
    data = json.dumps(body).encode()
    req  = urllib.request.Request(f"{SERVER}{path}", data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def overwrite_thinking(thinking):
    width   = shutil.get_terminal_size().columns or 80
    flat    = thinking.replace('\n', ' ').replace('\r', '')
    prefix  = "[thinking: "
    suffix  = "]"
    max_text = width - len(prefix) - len(suffix) - 2
    tail    = flat[-max_text:] if len(flat) > max_text else flat
    line    = f"{prefix}{tail}{suffix}"
    sys.stdout.write(f"\r\033[K{GREEN}{line}{RESET}")
    sys.stdout.flush()


def clear_thinking_line():
    sys.stdout.write("\r\033[K")
    sys.stdout.flush()


def model_picker():
    result = subprocess.run(["ollama", "list"], capture_output=True, text=True)
    lines  = result.stdout.strip().splitlines()
    models = [l.split()[0] for l in lines[1:] if l.strip()]

    if not models:
        print("  No models installed.\n")
        return None

    selected = 0

    def draw(first=False):
        if not first:
            sys.stdout.write(f"\033[{len(models) + 1}A")
        sys.stdout.write(f"\r\033[KPick a model  (↑/↓ move, Enter/Space select, Esc cancel):\n")
        for i, m in enumerate(models):
            marker = f"{GREEN}>{RESET}" if i == selected else " "
            sys.stdout.write(f"\r\033[K {marker} {m}\n")
        sys.stdout.flush()

    draw(first=True)

    def clear_menu():
        sys.stdout.write(f"\033[{len(models) + 1}A")
        for _ in range(len(models) + 1):
            sys.stdout.write("\r\033[K\n")
        sys.stdout.write(f"\033[{len(models) + 1}A")
        sys.stdout.flush()

    if sys.platform == "win32":
        import msvcrt
        while True:
            ch = msvcrt.getch()
            if ch in (b'\xe0', b'\x00'):
                ch2 = msvcrt.getch()
                if ch2 == b'H':    selected = (selected - 1) % len(models); draw()
                elif ch2 == b'P':  selected = (selected + 1) % len(models); draw()
            elif ch in (b'\r', b' '):
                break
            elif ch == b'\x1b':
                clear_menu(); return None
    else:
        import tty, termios
        fd  = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            while True:
                ch = sys.stdin.read(1)
                if ch == '\x1b':
                    seq = sys.stdin.read(2)
                    if seq == '[A':    selected = (selected - 1) % len(models); draw()
                    elif seq == '[B':  selected = (selected + 1) % len(models); draw()
                    else:              break  # Esc
                elif ch in ('\r', '\n', ' '):
                    break
                elif ch == '\x03':
                    break
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)

    clear_menu()
    return models[selected]


def handle_command(raw, state):
    thinking_level = state["thinking_level"]
    try:
        parts = shlex.split(raw)
    except ValueError:
        parts = raw.split()
    cmd = parts[0].lower()

    if cmd == "/?":
        print()
        for name, desc in COMMANDS.items():
            print(f"  {name:<28} {desc}")
        print()

    elif cmd == "/bye":
        print("\nGoodbye!")
        sys.exit(0)

    elif cmd == "/model":
        rest = raw[len("/model"):].strip().strip('"').strip("'")
        if not rest:
            pick = model_picker()
            if pick:
                post("/set", {"model": pick})
                print(f"  Model set to: {pick}\n")
        else:
            post("/set", {"model": rest})
            print(f"  Model set to: {rest}\n")

    elif cmd == "/ollama":
        if len(parts) >= 3 and parts[1] == "-p":
            model = parts[2]
            print(f"  Pulling {model}...\n")
            subprocess.run(["ollama", "pull", model])
            print()
        elif len(parts) == 1:
            result = subprocess.run(["ollama", "list"], capture_output=True, text=True)
            print()
            print(result.stdout or result.stderr)
        else:
            print("  Usage: /ollama  or  /ollama -p \"modelname\"\n")

    elif cmd == "/thinking":
        if len(parts) < 2:
            level = state["thinking_level"]
            print(f"  Current thinking level: {'off' if level == 0 else level}\n")
            return
        arg = parts[1].lower()
        if arg in ("off", "0"):
            state["thinking_level"] = 0
            print("  Thinking disabled — responses will skip reasoning.\n")
        else:
            try:
                n = int(arg)
                if 1 <= n <= 10:
                    state["thinking_level"] = n
                    print(f"  Thinking level set to {n}.\n")
                else:
                    print("  Level must be 0/off or 1–10.\n")
            except ValueError:
                print("  Usage: /thinking off  or  /thinking 0-10\n")

    elif cmd == "/clear":
        post("/clear", {})
        print("  Conversation history cleared.\n")

    else:
        print(f"  Unknown command: {cmd}  (type /? for help)\n")


def chat():
    chat_state = {"thinking_level": 5}

    with connect("ws://127.0.0.1:58008/message") as ws:
        print("FrogLauncher Chat  (type /? for commands)\n")

        while True:
            try:
                user_input = input(">> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break

            if not user_input:
                continue

            if user_input.startswith("/"):
                handle_command(user_input, chat_state)
                continue

            print(f"\nUser: {user_input}\n")
            ws.send(json.dumps({"content": user_input, "thinking": chat_state["thinking_level"]}))

            current_message = ""
            in_message      = False
            thinking_start  = None
            last_redraw     = 0.0
            REDRAW_INTERVAL = 0.05 + chat_state["thinking_level"] * 0.01
            show_thinking   = chat_state["thinking_level"] > 0

            while True:
                msg      = json.loads(ws.recv())

                if "error" in msg:
                    err = msg["error"]
                    clear_thinking_line()
                    if err in ("no_model_running", "no_model_selected"):
                        print(f'  No model selected. Use /model "modelname" to pick one.\n')
                    elif err == "model_not_found":
                        model = msg.get("model", "?")
                        print(f'  Model "{model}" is not installed. Pull it with: /ollama -p "{model}"\n')
                    elif err == "ollama_connection_failed":
                        print("  Can't reach Ollama — is it running?\n")
                    else:
                        print(f"  Server error: {err}\n")
                    break

                stage    = msg.get("stage", 0)
                thinking = msg.get("thinking", "")
                message  = msg.get("message", "")

                if stage == 1:
                    if show_thinking:
                        if thinking_start is None:
                            thinking_start = time.time()
                        now = time.time()
                        if now - last_redraw >= REDRAW_INTERVAL:
                            overwrite_thinking(thinking)
                            last_redraw = now

                elif stage == 2:
                    if not in_message:
                        if show_thinking:
                            elapsed = time.time() - (thinking_start or time.time())
                            clear_thinking_line()
                            sys.stdout.write(f"💡 Thought for {elapsed:.1f}s.\n\nAI: ")
                        else:
                            sys.stdout.write("AI: ")
                        sys.stdout.flush()
                        in_message = True
                    if message != current_message:
                        sys.stdout.write(message[len(current_message):])
                        sys.stdout.flush()
                        current_message = message

                elif stage == 3:
                    if not in_message:
                        if show_thinking:
                            elapsed = time.time() - (thinking_start or time.time())
                            clear_thinking_line()
                            sys.stdout.write(f"💡 Thought for {elapsed:.1f}s.\n\nAI: ")
                        else:
                            sys.stdout.write("AI: ")
                        sys.stdout.write(message if message else "(no response)")
                    elif message != current_message:
                        sys.stdout.write(message[len(current_message):])
                    print("\n")
                    break


chat()
