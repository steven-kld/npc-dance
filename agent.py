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
You are a flow execution agent. Your only job is to find the right flow, collect data from the user, and return ready-to-execute FlowInstruction objects.

Workflow:
1. The user describes what they want to do.
2. Call find_flow with the user's request.
3. If no flow found — tell the user and stop.
4. If flow found — show the user:
   - Flow name and description
   - List of required fields (labels only, no technical keys)
   Then say: "Is this the right flow? If yes — provide the data."
5. If the user says this is the wrong flow — go back to step 1 and search again with the new description.
6. Once the user provides data — call create_flow_calls EXACTLY ONCE, passing the entire raw user input as-is. No matter how many records — one call only. Never split, never loop, never call the tool more than once.
7. Show the FULL result of create_flow_calls to the user exactly as returned. Do not modify it.

Rules:
- Never execute anything in the browser.
- Never ask for more than what the flow's input_schema requires.
- If the user provides data for multiple records — pass ALL records as one user_input string to create_flow_calls, do NOT call it multiple times.
- After calling create_flow_calls — show the FULL result text to the user exactly as returned by the tool. Do not summarize it, do not replace it with "OK".
"""


def load_flows() -> list[dict]:
    if not FLOWS_FILE.exists():
        return []
    return json.loads(FLOWS_FILE.read_text(encoding="utf-8"))


# Global store: pending calls per thread_id — never touches the model context
_pending_calls: dict[str, list[dict]] = {}


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


@tool
def create_flow_calls(flow_id: str, user_input: str) -> str:
    """
    Parse user input and create one or more FlowInstruction objects for a given flow.
    user_input can contain data for multiple records — split by newline or semicolon.
    Saves valid FlowInstruction objects for later execution. Returns confirmation text.
    """
    flows = load_flows()
    flow = next((f for f in flows if f["id"] == flow_id), None)
    if not flow:
        return f"Flow '{flow_id}' not found."

    records = [r.strip() for r in user_input.replace(";", "\n").splitlines() if r.strip()]

    results = []
    valid_calls = []

    for i, record in enumerate(records, 1):
        try:
            call = FlowInstruction.create(flow, record)
            header = f"Record {i}:" if len(records) > 1 else ""
            results.append((header + "\n" if header else "") + str(call))
            valid_calls.append({
                "flow": call.flow,
                "input_schema": call.input_schema,
                "steps": call.steps,
            })
        except ValueError as e:
            results.append(f"Record {i}: {e}")

    return "\n\n---\n\n".join(results), valid_calls


TOOLS = [find_flow, create_flow_calls]

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
    thread_id = config["configurable"]["thread_id"]
    messages = state["messages"]
    last = messages[-1]
    results = []

    for tool_call in last.tool_calls:
        name = tool_call["name"]
        args = tool_call["args"]

        if name == "find_flow":
            result = find_flow.invoke(args)
            results.append(ToolMessage(content=result, tool_call_id=tool_call["id"]))

        elif name == "create_flow_calls":
            text, valid_calls = create_flow_calls.invoke(args)
            # Save pending calls keyed by thread_id — never goes into model context
            if valid_calls:
                _pending_calls[thread_id] = _pending_calls.get(thread_id, []) + valid_calls
                log.info(f"[pending] {len(valid_calls)} call(s) saved for thread {thread_id}")
            results.append(ToolMessage(content=text, tool_call_id=tool_call["id"]))

    return {"messages": results}


_builder = StateGraph(State)
_builder.add_node("agent", agent_node)
_builder.add_node("tools", tools_node)
_builder.set_entry_point("agent")
_builder.add_conditional_edges("agent", tools_condition)
_builder.add_edge("tools", "agent")
agent = _builder.compile(checkpointer=MemorySaver())

app = FastAPI()


@app.post("/run-flow")
async def run_flow(request: dict):
    loop = asyncio.get_running_loop()
    flows = load_flows()
    flow = next((f for f in flows if f["id"] == "abs142"), None)
    user_input = request.get("input", "")
    log.info(f"[run-flow] input: {user_input}")

    def execute():
        from flow_call import FlowCall
        instruction = FlowInstruction.create(flow, user_input)
        log.info(f"[run-flow] instruction: {instruction}")
        FlowCall(instruction, _eye, _hand).run()

    await loop.run_in_executor(None, execute)
    return {"status": "ok"}


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


# "Андрей Петров, улица Пушкина дом 16, 4500, DEUTDEFFXXX, COBADEFFXXX, DE89 3704 0044 0532 0130 00", "Андрей Петров, Пушкина 16, 6000, COBADEFFXXX, DE89 3704 0044 0532 0130 00", "Степан Себастьян Иоанович Петровский Корсаков, Пушкина 16, 1000, COBADEFFXXX, DE89 3704 0044 0532 0130 00"