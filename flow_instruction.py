import os
from dotenv import load_dotenv
load_dotenv()
from dataclasses import dataclass
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.output_parsers import JsonOutputParser
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from openai import APIConnectionError

_llm = ChatOpenAI(
    model="deepseek-ai/DeepSeek-V3.1",
    base_url="https://api.together.xyz/v1",
    api_key=os.environ["TOGETHER_AI_API_KEY"],
    timeout=15,
)


@dataclass
class FlowInstruction:
    flow: dict
    input_schema: list[dict]
    steps: list[dict]

    @classmethod
    def create(cls, flow: dict, user_input: str) -> "FlowInstruction":
        schema = [dict(field) for field in flow["input_schema"]]

        schema_description = "\n".join(
            f'- key="{f["key"]}" — {f["description"]}'
            for f in schema
        )

        system = (
            "Extract the fields from the user's input. "
            "Return ONLY a JSON object with no explanation.\n"
            "For missing or absent fields use empty string \"\", never null, never \"none\".\n\n"
            f"Fields:\n{schema_description}\n\n"
            f'Keys: {", ".join(f["key"] for f in schema)}'
        )

        @retry(
            retry=retry_if_exception_type(APIConnectionError),
            wait=wait_exponential(multiplier=1, min=2, max=10),
            stop=stop_after_attempt(3),
            reraise=True,
        )
        def invoke():
            return (_llm | JsonOutputParser()).invoke([
                SystemMessage(content=system),
                HumanMessage(content=user_input)
            ])

        parsed_values = invoke()

        for field in schema:
            raw_value = parsed_values.get(field["key"])
            field["value"] = "" if (raw_value is None or str(raw_value).strip().lower() in ("none", "null", "н/д", "n/a")) else str(raw_value)

        empty_optional_keys = {f["key"] for f in schema if f.get("optional") and not str(f["value"]).strip()}

        def substitute(s: str) -> str:
            for field in schema:
                s = s.replace(f'{{{field["key"]}.value}}', str(field["value"]))
            return s

        rendered_steps = []
        for step in flow["steps"]:
            step_str = str(step)
            if any(f"{{{k}." in step_str for k in empty_optional_keys):
                continue
            rendered = {k: substitute(v) if isinstance(v, str) else v for k, v in step.items()}
            rendered_steps.append(rendered)

        return cls(
            flow=flow,
            input_schema=schema,
            steps=rendered_steps,
        )

