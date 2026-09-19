"""Small, explicit workflow fixtures; no claims about physical playing capability."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Scenario:
    name: str
    notes: tuple[tuple[int, int], ...]
    expected_outcome: str = "completed"
    fail_first_press: bool = False

    def task(self) -> dict:
        return {
            "requested_notes": [{"string": s, "fret": f} for s, f in self.notes],
            "instructions": (
                "Use the tools to prepare and pluck each requested note exactly once, in order. "
                "Check that the whole request is supported before starting; if not, make no motion "
                "and finish blocked. On an execution fault, make no further motion and finish blocked. "
                "For normal completion, lift off the final fret before calling done. "
                "Do not invent sound observations. These are separate sequential notes, not a chord."
            ),
        }


SCENARIOS = {
    "single-note": Scenario("single-note", ((5, 5),)),
    "repeat-and-change": Scenario("repeat-and-change", ((5, 5), (5, 5), (3, 3))),
    "unsupported-target": Scenario("unsupported-target", ((5, 12),), expected_outcome="blocked"),
    "fret-failure": Scenario("fret-failure", ((5, 5),), expected_outcome="blocked", fail_first_press=True),
}
