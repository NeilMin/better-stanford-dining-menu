"""Does this picture show the dish? Asked as questions, not as a score.

A 1-10 score from a vision model is a mood, and the old gate showed it: a
picture it scored 3 went up anyway because it was the best of three, and one it
never managed to score went up with a 0. What works instead is to decompose "is
this right" into yes/no questions about what is visible -- the brief's checks,
plus the few every picture must pass -- and to ask them blind: the judge is not
told which answer is wanted, and the comparison happens here.

"unclear" is an answer, and what it means depends on the question. Asked for a
defining feature ("is the fish white?"), it fails: the picture has to show the
dish, not fail to rule it out. Asked about a mistake ("is the meat ground?"), it
passes: a mistake only counts if it can be seen. Measured on pictures a person
had already ruled on, failing both ways rejected half of the accepted ones.
"""

from __future__ import annotations

from datetime import datetime, timezone

from bsdm.llm import LLMError, parse_json

SYSTEM = (
    "You inspect food photographs for a dining hall menu. You answer strictly from what is "
    "visible in the photo, never from what the dish would usually contain. Reply with a single "
    "JSON object and nothing else."
)


def checks(brief: dict) -> list[dict]:
    """The brief's own checks, then the ones every dish shares.

    The recognition question is the catch-all for a mistake the brief did not
    think to ask about, and it is a judgement call where "unclear" is an honest
    answer about a perfectly good picture -- so only a definite no fails it.
    """
    recognised = {"q": f"Would someone who ordered {brief['dish']} recognise this as that dish?",
                  "yes": True, "lenient": True}
    # Narrow on purpose: fish and chips is one dish with its chips on the
    # plate. What this catches is the luau platter drawn for a bowl of rice.
    # A brief that is a spread by design asks for the opposite itself.
    one_dish = [] if brief.get("spread") else [
        {"q": "Is this a spread of several different dishes, like a buffet table or a combination platter?",
         "yes": False}]
    no_text = {"q": "Is there any text, logo, watermark, hand or person in the picture?", "yes": False}
    return [*brief["checks"], recognised, *one_dish, no_text]


def request(questions: list[dict]) -> str:
    numbered = "\n".join(f"{n}. {c['q']}" for n, c in enumerate(questions, 1))
    return (
        "Look at the photo. Answer each question with \"yes\", \"no\" or \"unclear\", judging only "
        "what you can see. Say unclear only when the photo really does not let you tell.\n\n"
        f"{numbered}\n\n"
        "Then say in one sentence what food the photo shows, as a diner would describe it.\n\n"
        'Reply with JSON: {"answers": ["yes", "no", ...], "seen": "..."} -- one answer per question, in order.'
    )


def _answer(value) -> str:
    text = str(value).strip().lower()
    if text.startswith("yes"):
        return "yes"
    if text.startswith("no"):
        return "no"
    return "unclear"


def inspect(image: bytes, brief: dict, llm) -> dict:
    """The verdict on one picture: pass, what the judge saw, and which checks failed."""
    questions = checks(brief)
    raw = parse_json(llm.ask(request(questions), images=[image], system=SYSTEM))
    answers = raw.get("answers")
    if not isinstance(answers, list) or len(answers) != len(questions):
        raise LLMError(f"expected {len(questions)} answers, got {answers!r}")
    failed = []
    for check, value in zip(questions, answers):
        got = _answer(value)
        expected = "yes" if check["yes"] else "no"
        if got == "unclear" and (not check["yes"] or check.get("lenient")):
            continue
        if got != expected:
            failed.append({"q": check["q"], "expected": expected, "got": got})
    return {
        "pass": not failed,
        "seen": str(raw.get("seen") or "").strip(),
        "failed": failed,
        "judge": llm.name,
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
