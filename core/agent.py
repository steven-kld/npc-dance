import json
import os
from pathlib import Path
from typing import Annotated

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import tools_condition
from typing_extensions import TypedDict

from automation.workspace import connect
from automation.eye import Eye
from automation.hand import Hand
from automation.flow_instruction import FlowInstruction
from core.logger import Logger
from core.prompts import AGENT_SYSTEM, FIND_FLOW_SYSTEM

logger = Logger()

FLOWS_FILE = Path(__file__).parent.parent / "flows.json"

connect()

_eye = Eye(api_key=os.environ["TOGETHER_AI_API_KEY"])
_eye.warmup()
_hand = Hand()



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

    response = llm.invoke([
        SystemMessage(content=FIND_FLOW_SYSTEM),
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
    from automation.flow_call import FlowCall
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
            logger.log(f"[run_flow] executing record {i}: {instruction}")
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


def agent_node(state: State):
    msgs = [SystemMessage(content=AGENT_SYSTEM)] + state["messages"]
    response = llm.invoke(msgs)
    if response.content:
        logger.log(f"[thought] {response.content}")
    for call in getattr(response, "tool_calls", []):
        logger.log(f"[tool_call] {call['name']}({call['args']})")
    return {"messages": [response]}


def tools_node(state: State):
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
            logger.log(f"[run_flow] result: {result}")
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
