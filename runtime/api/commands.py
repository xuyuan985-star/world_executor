import threading
from dataclasses import dataclass
from typing import Optional

from runtime import db
from runtime.events.bus import EventBus
from runtime.events.schema import WorldEvent, make_event


@dataclass
class MissionSpec:
    knowledge_dir: str
    target_ids: Optional[list] = None


class RuntimeAPI:
    def __init__(self, event_bus: EventBus, execution_id=None):
        self.bus = event_bus
        self.execution_id = execution_id
        self._runner = None
        self._thread = None
        self._state = "idle"

    def start_mission(self, spec: MissionSpec, runner_factory=None):
        from runtime import dry_run

        def runner(bus, execution_id):
            from ingest.compiler.validate_graph import validate
            from runtime.knowledge_loader import KnowledgePackage
            from pathlib import Path

            pkg = KnowledgePackage(Path(spec.knowledge_dir))
            errors, _ = validate(pkg, verbose=False)
            if errors:
                bus.publish(make_event("run_finished", execution_id,
                                       context={"result": "invalid", "errors": len(errors)}))
                return "invalid"

            targets = spec.target_ids or [c["id"] for c in pkg.chests]
            self._state = "running"
            bus.publish(make_event("run_started", execution_id,
                                   context={"knowledge": spec.knowledge_dir, "targets": targets}))
            result = dry_run.dry_run(spec.knowledge_dir, targets, bus=bus, execution_id=execution_id)
            self._state = "done"
            bus.publish(make_event("run_finished", execution_id,
                                   context={"result": result}))
            return result

        import uuid

        self.execution_id = self.execution_id or f"run{uuid.uuid4().hex[:4]}"
        self._thread = threading.Thread(target=lambda: runner(self.bus, self.execution_id), daemon=True)
        self._thread.start()
        return self.execution_id

    def pause(self):
        self._state = "paused"
        return self._state

    def request_pause_human(self, reason="unknown_state"):
        self._state = "paused_for_human"
        self.bus.publish(make_event("pause_requested", self.execution_id,
                                    context={"reason": reason}))
        return self._state

    def resume_check(self, checks=None):
        self._state = "resume_check"
        self.bus.publish(make_event("resume_checked", self.execution_id,
                                    context={"checks": checks or []}))
        return self._state

    def resume(self):
        self._state = "running"
        return self._state

    def stop(self):
        self._state = "stopped"
        return self._state

    def inspect(self):
        return {"state": self._state, "execution_id": self.execution_id}

    def recent_events(self, limit=50):
        return self.bus.replay(self.execution_id)[-limit:]
