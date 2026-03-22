import asyncio
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from langchain_core.messages import HumanMessage

from core.agent import agent
from core.logger import Logger, LOG_FILE

logger = Logger()

app = FastAPI()


@app.get("/demo")
async def demo():
    from fastapi.responses import HTMLResponse
    html = (Path(__file__).parent / "static" / "test_form.html").read_text()
    return HTMLResponse(html)


@app.get("/log")
async def get_log():
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse(LOG_FILE.read_text())


@app.get("/img-log")
async def img_log():
    from fastapi.responses import FileResponse, Response
    p = Path("/tmp/result.png")
    if not p.exists():
        return Response(status_code=404, content="No result.png yet")
    return FileResponse(p, media_type="image/png")


@app.websocket("/ws")
async def chat(ws: WebSocket):
    await ws.accept()
    logger.log("CHAT CONNECTION")
    config = {"configurable": {"thread_id": str(id(ws))}}
    loop = asyncio.get_running_loop()

    try:
        while True:
            data = await ws.receive_json()
            user_text = data.get("content", "")
            logger.log(f"[user] {user_text}")

            inp = {"messages": [HumanMessage(content=user_text)]}

            try:
                result = await loop.run_in_executor(
                    None, lambda i=inp, c=config: agent.invoke(i, c)
                )
            except Exception as e:
                await ws.send_json({"role": "assistant", "content": f"[Error] {e}"})
                continue

            last = result["messages"][-1]
            content = last.content if isinstance(last.content, str) else str(last.content)
            await ws.send_json({"role": "assistant", "content": content})

    except WebSocketDisconnect:
        pass


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, ws_ping_interval=None)
