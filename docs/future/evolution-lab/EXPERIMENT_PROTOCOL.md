# Evolution Lab Experiment Protocol

1. Create a disposable repository or disposable fork with no production secrets/data.
2. Pin the blueprint/spec revision.
3. Select the slice corpus, potentially hundreds to ~1,000 slices.
4. Define autonomous permissions explicitly for the lab repo only.
5. Require checkpoints after each material milestone so the run can resume after provider/session failure.
6. Require tests, decision logs, architecture notes, and failure records even when the agent is allowed to merge freely in the lab.
7. Record when a slice is skipped, partially implemented, reinterpreted, or worked around.
8. Periodically snapshot repo health and architecture drift.
9. Never connect the lab to production credentials, production payment authority, real outbound messaging, or destructive external systems.
10. At run completion, produce a harvest report: successful capabilities, failed approaches, hidden regressions, reusable components, new tests, and recommended production promotions.
