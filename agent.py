import asyncio
import logging
import os
from pathlib import Path
from typing import Annotated

LOG_FILE = Path(__file__).parent / "agent.log"
LOG_FILE.write_text("")  # clear on each startup

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("agent")

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.types import interrupt, Command
from typing_extensions import TypedDict

from workspace import connect
from eye import Eye
from hand import Hand

FLOWS_DIR = Path(__file__).parent / "flows"
FLOWS_DIR.mkdir(exist_ok=True)

connect()

_eye = Eye(api_key=os.environ["AWS_BEARER_TOKEN_BEDROCK"])
_eye.warmup()
_hand = Hand()

SYSTEM_PROMPT = """/no_think
You are a browser automation agent controlling a real Chrome browser.

Rules:
- Call tools immediately. No clarification questions.
- After completing the user's request, respond with exactly "OK" and nothing else.
- If something failed or you could not complete the task, respond with a single short sentence describing the issue.
- Never respond with anything else — no acknowledgments, no explanations, just "OK" or the issue.
- "scroll down" = call scroll ONCE, then output OK. STOP. Do NOT scroll again.
- Only keep scrolling if the user said "scroll until you find X" — in that case scroll, try click("X"), repeat ONLY if not found.
- Before starting a task, call list_flows then read_flow if a relevant one exists.
- When the user asks to "remember" or "save" a procedure, use save_flow.
"""


@tool
def navigate(url: str) -> str:
    """Navigate the browser to a URL."""
    _hand.navigate(url)
    return f"Navigated to {url}"


@tool
def click(query: str) -> str:
    """Click a UI element by visual description (e.g. 'Submit button', 'search field')."""
    result = _eye.locate(query)
    if "center" not in result:
        raise RuntimeError(f"Element not found: '{query}' — {result}")
    cx, cy = result["center"]
    _hand.click(cx, cy)
    return f"Clicked '{query}' at ({cx}, {cy})"


@tool
def type_text(query: str, text: str) -> str:
    """Click a UI element and type text into it."""
    result = _eye.locate(query)
    if "center" not in result:
        raise RuntimeError(f"Element not found: '{query}' — {result}")
    cx, cy = result["center"]
    _hand.click_and_type(cx, cy, text)
    return f"Typed '{text}' into '{query}'"


@tool
def scroll(direction: str = "down", times: int = 1) -> str:
    """Scroll the page. direction: up | down | left | right. times: how many scroll steps (default 1)."""
    for _ in range(max(1, times)):
        _hand.scroll(direction)
    return f"Scrolled {direction} x{times}"


@tool
def save_flow(name: str, content: str) -> str:
    """Save or update a named flow procedure. name should be a slug e.g. 'amazon_insert'."""
    (FLOWS_DIR / f"{name}.md").write_text(content)
    return f"Flow '{name}' saved."


@tool
def read_flow(name: str) -> str:
    """Read a saved flow procedure by name."""
    p = FLOWS_DIR / f"{name}.md"
    return p.read_text() if p.exists() else f"No flow named '{name}'."


@tool
def list_flows() -> str:
    """List all saved flow names."""
    flows = [f.stem for f in FLOWS_DIR.glob("*.md")]
    return ", ".join(flows) if flows else "No flows saved yet."


@tool
def ask_user(question: str) -> str:
    """Pause execution and ask the user a question. Use when blocked or on unhandled error."""
    return interrupt(question)


TOOLS = [navigate, click, type_text, scroll,
         save_flow, read_flow, list_flows, ask_user]

llm = ChatOpenAI(
    model="deepseek.v3.2",
    base_url="https://bedrock-mantle.us-east-1.api.aws/v1",
    api_key=os.environ["AWS_BEARER_TOKEN_BEDROCK"],
).bind_tools(TOOLS)


class State(TypedDict):
    messages: Annotated[list, add_messages]


def agent_node(state: State):
    msgs = [SystemMessage(content=SYSTEM_PROMPT)] + state["messages"]
    response = llm.invoke(msgs)
    if response.content:
        log.info(f"[thought] {response.content}")
    for call in getattr(response, "tool_calls", []):
        log.info(f"[tool_call] {call['name']}({call['args']})")
    return {"messages": [response]}


_builder = StateGraph(State)
_builder.add_node("agent", agent_node)
_builder.add_node("tools", ToolNode(TOOLS))
_builder.set_entry_point("agent")
_builder.add_conditional_edges("agent", tools_condition)
_builder.add_edge("tools", "agent")
agent = _builder.compile(checkpointer=MemorySaver())

app = FastAPI()


@app.get("/demo")
async def demo():
    from fastapi.responses import HTMLResponse
    html = (Path(__file__).parent / "test_form.html").read_text()
    return HTMLResponse(html)


@app.get("/log")
async def get_log():
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse(LOG_FILE.read_text())


@app.websocket("/ws")
async def chat(ws: WebSocket):
    await ws.accept()
    log.info("CHAT CONNECTION")
    config = {"configurable": {"thread_id": str(id(ws))}}
    loop = asyncio.get_running_loop()

    try:
        while True:
            data = await ws.receive_json()
            user_text = data.get("content", "")
            log.info(f"[user] {user_text}")

            # If graph is paused on an interrupt, resume with user's answer
            state = agent.get_state(config)
            interrupts = [iv for task in state.tasks for iv in task.interrupts]
            if interrupts:
                inp = Command(resume=user_text)
            else:
                inp = {"messages": [HumanMessage(content=user_text)]}

            try:
                result = await loop.run_in_executor(
                    None, lambda i=inp, c=config: agent.invoke(i, c)
                )
            except Exception as e:
                await ws.send_json({"role": "assistant", "content": f"[Error] {e}"})
                continue

            # Check if graph paused again (ask_user called)
            new_state = agent.get_state(config)
            new_interrupts = [iv for task in new_state.tasks for iv in task.interrupts]
            if new_interrupts:
                await ws.send_json({"role": "assistant", "content": new_interrupts[0].value})
            else:
                last = result["messages"][-1]
                content = last.content if isinstance(last.content, str) else str(last.content)
                await ws.send_json({"role": "assistant", "content": content})

    except WebSocketDisconnect:
        pass


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, ws_ping_interval=None)
