import asyncio
import json
import websockets

async def main():
    uri = "ws://localhost:8000/ws"
    print(f"Connecting to {uri}...")
    async with websockets.connect(uri) as ws:
        print("Connected. Type your message and press Enter. Ctrl+C to exit.\n")
        while True:
            msg = input("you: ").strip()
            if not msg:
                continue
            await ws.send(json.dumps({"content": msg}))
            reply = await ws.recv()
            print(f"agent: {json.loads(reply)['content']}\n")

asyncio.run(main())
