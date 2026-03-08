import asyncio
import os
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from langchain_anthropic import ChatAnthropic
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

_eye = Eye(
    ollama_url=os.environ["OLLAMA_URL"],
    token=os.environ["OLLAMA_TOKEN"],
)
_eye.warmup()
_hand = Hand()

SYSTEM_PROMPT = """You are a browser automation agent controlling a real Chrome browser.

Guidelines:
- Before starting a task, call list_flows then read_flow if a relevant one exists.
- When the user asks to "remember" or "save" a procedure, use save_flow.
- When an error occurs that you cannot self-correct, call ask_user to pause and get instructions.
- After receiving error-handling instructions, update the flow with save_flow before resuming.
- For batch tasks (many items), process sequentially and report progress after each item.
- After ask_user returns an answer, incorporate it and continue — do not ask again for the same issue.
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
def scroll(direction: str = "down") -> str:
    """Scroll the page. direction: up | down | left | right"""
    _hand.scroll(direction)
    return f"Scrolled {direction}"


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

llm = ChatAnthropic(
    model="claude-sonnet-4-6",
    api_key=os.environ["ANTHROPIC_API_KEY"],
).bind_tools(TOOLS)


class State(TypedDict):
    messages: Annotated[list, add_messages]


def agent_node(state: State):
    msgs = [SystemMessage(content=SYSTEM_PROMPT)] + state["messages"]
    return {"messages": [llm.invoke(msgs)]}


_builder = StateGraph(State)
_builder.add_node("agent", agent_node)
_builder.add_node("tools", ToolNode(TOOLS))
_builder.set_entry_point("agent")
_builder.add_conditional_edges("agent", tools_condition)
_builder.add_edge("tools", "agent")
agent = _builder.compile(checkpointer=MemorySaver())

app = FastAPI()


@app.websocket("/ws")
async def chat(ws: WebSocket):
    await ws.accept()
    config = {"configurable": {"thread_id": str(id(ws))}}
    loop = asyncio.get_running_loop()

    try:
        while True:
            data = await ws.receive_json()
            user_text = data.get("content", "")

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
    uvicorn.run(app, host="0.0.0.0", port=8000)
