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
- Follow the week's phase and intent (volume, deload, strength, test...). Before planning, \
turn the intent into numbers, whatever its wording or language: reps per strength line, sets \
compared with the past week's, metcons in the whole week. Short sets are 5 reps or fewer; a \
halved volume is about half the past week's sets, line by line; a number of metcons counts for \
the week, not per session. A deload keeps the frequency: the same number of sessions, never \
more.
- Use the review: sessions done or missed, real loads and RIR, patterns not trained. Missed \
priority work (legs every week) comes back.
- Keep the athlete's weekly frame, on the same kind of days: the number of sessions of the \
past week's review (or of the phase's frame when there is no review). Sessions already planned \
in the target week count in that number: the ones you keep plus your new ones make it, never \
more. Count before you answer, in a deload too. Do not add sessions of \
your own, extra mobility or rest days included: a missed session comes back in place of \
another, not on top.
- Respect every athlete rule. Use only exercises from the exercise bank, with their exact \
names, in every part (warmup and mobility included). A movement that is not in the bank is \
left out; a rest is no session at all, never an exercise.
- Forbidden exercises: a rule with code forbid_flag lists flags (running, impact, \
free_barbell_legs...). Before using an exercise, read its flags in the exercise bank: one that \
carries a forbidden flag never appears, in any part (a back squat or a box jump, for instance, \
when they carry it). Pick an unflagged exercise of the same pattern instead.
- Loads: start from recent_loads; go up one step at most when the RIR was met. One step is \
the athlete's progression rule's (its params: upper_kg for the upper body, lower_kg for legs \
and hinge), above the heaviest set logged at as many reps or more. \
This holds in every phase: a power, strength or peak week means fewer reps and more sets at \
that load, never a jump of several steps. Fewer reps do not allow a \
heavier load: after a heaviest set of 8, a set of 3 is still at most one step above it.
- A missed set (fewer reps than planned, or a RIR below its target, RIR 0 included) means the \
load was too heavy: that exercise stays at most at the load of the missed set, or one step \
lighter, never higher, until a set at that load meets its RIR.
- Pain: when a feedback reports pain above the stop rule's threshold after a session, every \
exercise of the patterns that session loaded goes two load steps back from its load that day \
(the legs after a leg press, and the hinge too if that session loaded a deadlift), never up, \
until a later session \
loading them is reported without such pain. Keep training the pattern, lighter.
- Schedule sessions inside the target week only. If sessions are already planned for that week, \
they are the week's frame: keep each one (do not repeat it) or list its id in \
cancel_session_ids and give its replacement on the same day. Kept ones plus your new ones make \
the weekly frame's number (previous rules), never extra sessions on top.
- Critical health alert (an alert with severity critical): the whole week stays easy. No \
metcon at all, every strength, weightlifting and gymnastics line at RIR 3 or more, nothing \
marked as a max. Hard sessions already planned in the week are listed in cancel_session_ids \
and replaced by easy ones (technique, mobility, easy cardio).
- Low recovery, short sleep or an alert that is not critical: keep the first two days light (no \
metcon, RIR 3 or more). You give no medical advice.

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

    api_key: str = field(repr=False)  # never in a repr, a traceback's locals or a log line
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
