import json
from websockets.sync.client import connect

with connect("ws://127.0.0.1:58008/message") as ws:
    ws.send(json.dumps({"content": "Say hi in one sentence."}))
    while True:
        msg = json.loads(ws.recv())
        print(json.dumps(msg, indent=2))
        if msg.get("stage") == 3:
            break
