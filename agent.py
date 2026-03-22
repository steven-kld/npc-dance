import asyncio
import logging
import json, os
from pathlib import Path
from typing import Annotated

LOG_FILE = Path(__file__).parent / "agent.log"
LOG_FILE.write_text("")

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
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import tools_condition
from langgraph.types import Command
from typing_extensions import TypedDict
from langchain_core.runnables import RunnableConfig

from workspace import connect
from eye import Eye
from hand import Hand
from flow_instruction import FlowInstruction

FLOWS_FILE = Path(__file__).parent / "flows.json"

connect()

_eye = Eye(api_key=os.environ["TOGETHER_AI_API_KEY"])
_eye.warmup()
_hand = Hand()

SYSTEM_PROMPT = """/no_think
You are a flow execution agent.

Workflow:
1. Call find_flow with the user's message to identify the flow.
2. If no flow found — tell the user and stop.
3. Call prepare_flow ONCE with the flow_id and the user's raw input as-is. Show the result to the user.
4. If the result contains missing fields — wait for the user to provide them, then reconstruct the full corrected record(s) and call prepare_flow again.
5. Repeat step 4 until all records are complete.
6. When the user confirms ("ok", "go", "execute", etc.) — call run_flow ONCE with the same flow_id and the last complete user_input.
7. Show the FULL result of run_flow to the user exactly as returned.

Rules:
- Do NOT inspect or validate data yourself. All parsing and validation happens inside the tools.
- Pass ALL records as one user_input string — never split across multiple calls.
- When reconstructing input after a user correction, combine all records into one string (one per line).
- Never call run_flow until the user explicitly confirms.
"""


def load_flows() -> list[dict]:
    if not FLOWS_FILE.exists():
        return []
    return json.loads(FLOWS_FILE.read_text(encoding="utf-8"))


@tool
def find_flow(user_input: str) -> str:
    """Find the most relevant flow from flows.json based on user's description."""
    flows = load_flows()
    if not flows:
        return "No flows available."

    catalog = "\n".join(
        f'{i}. name="{f["name"]}" | description="{f["description"]}"'
        for i, f in enumerate(flows)
    )

    llm = ChatOpenAI(
        model="deepseek-ai/DeepSeek-V3.1",
        base_url="https://api.together.xyz/v1",
        api_key=os.environ["TOGETHER_AI_API_KEY"],
    )

    system = (
        "You are an assistant that matches a user request to a flow from a catalog.\n"
        "Reply with ONLY a number — the index of the best matching flow.\n"
        "If no flow matches — reply with the word null.\n"
        "No other text."
    )

    response = llm.invoke([
        SystemMessage(content=system),
        HumanMessage(content=f"User request: {user_input}\n\nFlow catalog:\n{catalog}")
    ])
    answer = response.content.strip()

    if answer == "null":
        return "No matching flow found."

    try:
        idx = int(answer)
        flow = flows[idx]
        fields = "\n".join(
            f'  - {f["description"]}{"  (optional)" if f.get("optional") else ""}'
            for f in flow["input_schema"]
        )
        return (
            f'Flow found:\n'
            f'  Name: {flow["name"]}\n'
            f'  Description: {flow["description"]}\n'
            f'  Required fields:\n{fields}\n'
            f'  Flow ID: {flow["id"]}'
        )
    except (ValueError, IndexError):
        return "No matching flow found."


def _format_records(flow: dict, user_input: str) -> tuple[str, bool]:
    """Parse all records and format as a table. Returns (formatted_text, has_missing)."""
    records = [r.strip() for r in user_input.replace(";", "\n").splitlines() if r.strip()]
    blocks = []
    has_missing = False

    for record in records:
        instruction = FlowInstruction.create(flow, record)
        lines = []
        for f in instruction.input_schema:
            val = str(f["value"]).strip()
            if not val and not f.get("optional"):
                lines.append(f'{f["description"]}: ⚠ missing')
                has_missing = True
            elif val:
                lines.append(f'{f["description"]}: {val}')
        blocks.append("\n".join(lines))

    return "\n----\n".join(blocks), has_missing


@tool
def prepare_flow(flow_id: str, user_input: str) -> str:
    """
    Parse user input for the given flow and display a table of field values per record.
    Flags missing required fields. Does not execute anything.
    """
    flows = load_flows()
    flow = next((f for f in flows if f["id"] == flow_id), None)
    if not flow:
        return f"Flow '{flow_id}' not found."

    table, has_missing = _format_records(flow, user_input)
    if has_missing:
        table += "\n\n⚠ Some required fields are missing. Please provide them."
    return table


@tool
def run_flow(flow_id: str, user_input: str) -> str:
    """
    Parse user input, build FlowInstruction(s), and execute them for the given flow.
    user_input can contain data for multiple records — split by newline or semicolon.
    Raises errors if the data is inconsistent with the flow's input_schema.
    """
    from flow_call import FlowCall
    flows = load_flows()
    flow = next((f for f in flows if f["id"] == flow_id), None)
    if not flow:
        return f"Flow '{flow_id}' not found."

    records = [r.strip() for r in user_input.replace(";", "\n").splitlines() if r.strip()]
    results = []

    for i, record in enumerate(records, 1):
        header = f"Record {i}:\n" if len(records) > 1 else ""
        try:
            instruction = FlowInstruction.create(flow, record)
            missing = [
                f["description"] for f in instruction.input_schema
                if not f.get("optional") and not str(f["value"]).strip()
            ]
            if missing:
                results.append(f"{header}Missing required fields: {', '.join(missing)}")
                continue
            log.info(f"[run_flow] executing record {i}: {instruction}")
            FlowCall(instruction, _eye, _hand).run()
            results.append(f"{header}OK — {instruction}")
        except (ValueError, RuntimeError) as e:
            results.append(f"{header}Error: {e}")

    return "\n\n---\n\n".join(results)


TOOLS = [find_flow, prepare_flow, run_flow]

llm = ChatOpenAI(
    model="deepseek-ai/DeepSeek-V3.1",
    base_url="https://api.together.xyz/v1",
    api_key=os.environ["TOGETHER_AI_API_KEY"],
).bind_tools(TOOLS)


class State(TypedDict):
    messages: Annotated[list, add_messages]


def agent_node(state: State, config: RunnableConfig):
    msgs = [SystemMessage(content=SYSTEM_PROMPT)] + state["messages"]
    response = llm.invoke(msgs)
    if response.content:
        log.info(f"[thought] {response.content}")
    for call in getattr(response, "tool_calls", []):
        log.info(f"[tool_call] {call['name']}({call['args']})")
    return {"messages": [response]}


def tools_node(state: State, config: RunnableConfig):
    messages = state["messages"]
    last = messages[-1]
    results = []

    for tool_call in last.tool_calls:
        name = tool_call["name"]
        args = tool_call["args"]

        if name == "find_flow":
            result = find_flow.invoke(args)
        elif name == "prepare_flow":
            result = prepare_flow.invoke(args)
        elif name == "run_flow":
            result = run_flow.invoke(args)
            log.info(f"[run_flow] result: {result}")
        else:
            result = f"Unknown tool: {name}"

        results.append(ToolMessage(content=result, tool_call_id=tool_call["id"]))

    return {"messages": results}


_builder = StateGraph(State)
_builder.add_node("agent", agent_node)
_builder.add_node("tools", tools_node)
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
    log.info("CHAT CONNECTION")
    config = {"configurable": {"thread_id": str(id(ws))}}
    loop = asyncio.get_running_loop()

    try:
        while True:
            data = await ws.receive_json()
            user_text = data.get("content", "")
            log.info(f"[user] {user_text}")

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
