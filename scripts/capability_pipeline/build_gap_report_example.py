"""One-off script that produced capability_specs/tasks_status_summary.gap_report.json.

Runs the real, unmodified V0.3B ``backend.gap_reasoning.analyze_goal()``
against a scripted model response (the same ``FakeRouter`` pattern
``tests/test_gap_reasoning.py`` already uses) and the real
``build_default_registry()`` **as it existed on ``origin/main`` before
this branch's tasks.status_summary tool was added** -- i.e. this captures
a genuine "goal -> gap identified" moment, not a report generated after
the fact against a registry that already has the answer.

Uses a throwaway temporary SQLite database (never ``data/mootos.db``,
matching AGENTS.md's testing guidance) purely because
``analyze_goal()`` audits every call as a Run row; nothing about the gap
analysis itself is stored beyond that existing Run audit trail (no goal
text, no report body -- see ``backend/gap_reasoning.py``'s docstring).

Not a runtime module, not imported by anything else; kept for
reproducibility/audit of how the example Gap Report was produced. See
``docs/CAPABILITY_BUILD_PIPELINE.md`` Sec2.
"""

import json
import os
import tempfile
from pathlib import Path


def build() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        # Must be set before any backend.db import -- DATABASE_PATH is
        # resolved once, at import time.
        os.environ["MOOTOS_DATABASE_PATH"] = str(Path(tmp) / "gap_report_example.db")

        from backend.memory import init_db
        from backend.gap_reasoning import analyze_goal
        from backend.tool_registry import ToolRegistry
        from backend.tools_reference import register_reference_tools
        from backend.tools_web import register_v03c_tools

        init_db()

        # The registry as it existed BEFORE this branch's proof capability
        # was added -- V0.2A reference tools + V0.3C self-inspection, no
        # tasks.status_summary -- so this genuinely reproduces the gap the
        # proof capability was proposed to fill.
        pre_v03e_registry = ToolRegistry()
        register_reference_tools(pre_v03e_registry)
        register_v03c_tools(pre_v03e_registry)

        class ScriptedRouter:
            """Scripted response: the model proposes 'tasks.status_insight'
            as a capability the goal below needs -- exactly the shape a
            real model call to backend.gap_reasoning would return."""

            def generate_standalone(self, messages, instructions):
                from backend.model_router import ModelResponse

                proposal = {
                    "requirements": [
                        {
                            "capability": "tasks.status_insight",
                            "reason": (
                                "The goal asks for a breakdown of Task counts "
                                "by status, which no installed capability "
                                "currently provides in one call."
                            ),
                            "externally_blocked": False,
                        }
                    ]
                }
                return ModelResponse(
                    text=json.dumps(proposal), provider="scripted-example", model="scripted-example"
                )

        report = analyze_goal(
            "How many open Tasks do I have right now, broken down by status?",
            router=ScriptedRouter(),
            registry=pre_v03e_registry,
        )

        output_path = (
            Path(__file__).resolve().parent.parent.parent
            / "capability_specs"
            / "tasks_status_summary.gap_report.json"
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report.to_dict(), indent=2, sort_keys=False) + "\n", encoding="utf-8")
        print(f"Wrote {output_path}")
        print(f"classification={report.classification}")


if __name__ == "__main__":
    build()
