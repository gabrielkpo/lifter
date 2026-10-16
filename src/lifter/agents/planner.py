"""The week planner's LLM call: context in, typed WeekPlan out (Mistral, structured output).

The planner is a callable so the graph and the tests do not depend on a provider: tests use a
scripted planner, the CLI uses MistralPlanner. Token usage is recorded for the evaluation bench.
"""

from dataclasses import dataclass, field
from typing import Protocol

from pydantic import ValidationError

from lifter.agents.context import PlanningContext
from lifter.agents.plan import WeekPlan

SYSTEM_PROMPT = """You are the week planner of Lifter, a CrossFit coach. You program ONE week of \
the athlete's cycle, the way the athlete does it every weekend: from the review of the past \
week and from the phase of the coming week.

Method:
- Every training session follows the frame: warmup, then weightlifting or gymnastics while \
fresh, then strength, then the metcon. Cardio and mobility days have their own parts.
- Every strength, weightlifting or gymnastics line has a count (quantity), and every strength \
or weightlifting line in reps a target RIR (repetitions in reserve). The RIR is the \
instruction, the load only a guide.
- A metcon has a target (target_seconds for a for_time, target_rounds for an amrap), never a \
time cap.
- Follow the week's phase and intent (volume, deload, strength, test...). A deload halves the \
volume and keeps the frequency.
- Use the review: sessions done or missed, real loads and RIR, patterns not trained. Missed \
priority work (legs every week) comes back.
- Respect every athlete rule. Only use exercises from the exercise bank, with their exact names.
- Loads: start from recent_loads; go up one step at most when the RIR was met.
- Schedule sessions inside the target week only. If sessions are already planned for that week, \
either keep them (do not repeat them) or list their ids in cancel_session_ids and replace them.
- Low recovery or alerts: keep the first days light. You give no medical advice.

Numbers: in the summary and the rationales, cite only numbers that appear in the context or in \
your plan (loads, reps, scores, dates). Never compute new numbers (no differences, no \
percentages of your own). Write the summary and the rationales in {language}."""


@dataclass
class Usage:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class Planner(Protocol):
    usage: Usage

    def __call__(self, ctx: PlanningContext, feedback: list[str]) -> WeekPlan:
        """A plan for ctx.target_week; `feedback` lists what the guardrail refused last time."""


class PlannerOutputError(ValueError):
    """The model did not return a valid WeekPlan."""


def user_message(ctx: PlanningContext, feedback: list[str]) -> str:
    text = (
        f"Program week {ctx.target_week.number} ({ctx.target_week.start_date} to "
        f"{ctx.target_week.end_date}). Context (JSON):\n{ctx.model_dump_json()}"
    )
    if feedback:
        text += (
            "\n\nYour previous plan was refused by the guardrail. Fix every point and return "
            "the whole week again:\n" + "\n".join(f"- {item}" for item in feedback)
        )
    return text


@dataclass
class MistralPlanner:
    """WeekPlan from a Mistral chat model, through LangChain's structured output."""

    api_key: str
    model: str
    language: str = "English"
    temperature: float = 0.2
    timeout_seconds: float = 120
    max_output_tokens: int = 6000  # one answer can never cost more than this in output
    usage: Usage = field(default_factory=Usage)

    def __post_init__(self) -> None:
        from langchain_mistralai import ChatMistralAI

        llm = ChatMistralAI(
            model=self.model,
            api_key=self.api_key,
            temperature=self.temperature,
            timeout=self.timeout_seconds,
            max_retries=2,
            max_tokens=self.max_output_tokens,
        )
        self._llm = llm.with_structured_output(WeekPlan, include_raw=True)

    def __call__(self, ctx: PlanningContext, feedback: list[str]) -> WeekPlan:
        out = self._llm.invoke(
            [
                ("system", SYSTEM_PROMPT.format(language=self.language)),
                ("human", user_message(ctx, feedback)),
            ]
        )
        self.usage.calls += 1
        meta = getattr(out["raw"], "usage_metadata", None) or {}
        self.usage.input_tokens += meta.get("input_tokens", 0)
        self.usage.output_tokens += meta.get("output_tokens", 0)
        if out.get("parsing_error") is not None or out.get("parsed") is None:
            raise PlannerOutputError(f"invalid plan from the model: {out.get('parsing_error')}")
        parsed = out["parsed"]
        try:
            return parsed if isinstance(parsed, WeekPlan) else WeekPlan.model_validate(parsed)
        except ValidationError as exc:
            raise PlannerOutputError(f"invalid plan from the model: {exc}") from exc
