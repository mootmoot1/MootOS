"""One-off script that produced capability_specs/projects_overview.gap_report.json.

Same pattern as ``build_gap_report_example.py`` (proof #1): runs the real,
unmodified V0.3B ``backend.gap_reasoning.analyze_goal()`` against a
scripted model response and the real registry **as it existed before this
branch's ``projects.overview`` tool was added** -- V0.2A reference tools +
V0.3C self-inspection + V0.3E proof #1's ``tasks.status_summary``. That is
exactly the merged ``origin/main`` registry, so this captures a genuine
"goal -> gap identified" moment rather than a report generated after the
fact against a registry that already contains the answer.

Uses a throwaway temporary SQLite database (never ``data/mootos.db``, per
AGENTS.md) purely because ``analyze_goal()`` audits every call as a Run
row.

Not a runtime module and not imported by anything; kept for
reproducibility/audit. See ``docs/CAPABILITY_BUILD_PIPELINE.md`` §2.
"""

import json
import os
import tempfile
from pathlib import Path


GOAL = "Give me an overview of how much is going on in each of my projects."


def build() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        # Must be set before any backend.db import -- DATABASE_PATH is
        # resolved once, at import time.
        os.environ["MOOTOS_DATABASE_PATH"] = str(Path(tmp) / "gap_report_proof2.db")

        from backend.gap_reasoning import analyze_goal
        from backend.memory import init_db
        from backend.tool_registry import ToolRegistry
        from backend.tools_reference import register_reference_tools
        from backend.tools_task_summary import register_v03e_tools
        from backend.tools_web import register_v03c_tools

        init_db()

        # The registry as it existed BEFORE proof #2 -- i.e. exactly what
        # is merged on origin/main today. projects.overview is absent, so
        # this genuinely reproduces the gap proof #2 was proposed to fill.
        pre_proof2_registry = ToolRegistry()
        register_reference_tools(pre_proof2_registry)
        register_v03c_tools(pre_proof2_registry)
        register_v03e_tools(pre_proof2_registry)

        class ScriptedRouter:
            """Scripted response: the model proposes 'projects.insight' as
            a capability the goal needs -- the exact JSON shape a real
            model call to backend.gap_reasoning would return."""

            def generate_standalone(self, messages, instructions):
                from backend.model_router import ModelResponse

                proposal = {
                    "requirements": [
                        {
                            "capability": "projects.insight",
                            "reason": (
                                "The goal asks how much activity each project "
                                "holds, which requires counting memories, "
                                "Tasks, and conversations per project -- no "
                                "installed capability can do that."
                            ),
                            "externally_blocked": False,
                        },
                        {
                            "capability": "projects.view",
                            "reason": "The goal is about the user's projects, which must be enumerable.",
                            "externally_blocked": False,
                        },
                    ]
                }
                return ModelResponse(
                    text=json.dumps(proposal),
                    provider="scripted-example",
                    model="scripted-example",
                )

        report = analyze_goal(GOAL, router=ScriptedRouter(), registry=pre_proof2_registry)

        output_path = (
            Path(__file__).resolve().parent.parent.parent
            / "capability_specs"
            / "projects_overview.gap_report.json"
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(report.to_dict(), indent=2, sort_keys=False) + "\n", encoding="utf-8"
        )
        print(f"Wrote {output_path}")
        print(f"classification={report.classification}")
        print(f"missing={list(report.missing_capabilities)}")
        print(f"available={list(report.available_capabilities)}")


if __name__ == "__main__":
    build()
