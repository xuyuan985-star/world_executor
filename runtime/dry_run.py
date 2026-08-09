import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from runtime.capabilities import CapabilityRegistry
from runtime.events.schema import make_event
from runtime.knowledge_loader import KnowledgePackage
from runtime.state_machine import Event, State, StateMachine

ANOMALY_TARGET = "chest_D"
DRY_RUN_VERIFIES = "schema/graph/state_transition/event_flow/replay"
DRY_RUN_NOT_VERIFIES = "game_vision/input_reliability/real_movement/game_state"


def _emit(bus, execution_id, event_type, **kw):
    if bus is not None:
        bus.publish(make_event(event_type, execution_id, **kw))


def simulate_step(machine, step, pkg, sim_context, bus=None, execution_id=None):
    kind = step["type"]
    if kind == "portal":
        portal = pkg.portal(step["portal_id"])
        print(f"  [SIM] {machine.state.name}  → portal step: {portal['id']} ({portal['from']}→{portal['to']})")
        _emit(bus, execution_id, "action_executed", detail=f"portal:{portal['id']}",
              context={"room": sim_context["room"], "reason": "portal_transition",
                       "source": "decision_layer", "naturalized": True})
        machine.on(Event.PORTAL_EXPECTED, f"portal {portal['id']} ahead")
        time.sleep(0.05)
        machine.on(Event.PORTAL_DETECTED, "loading screen")
        time.sleep(0.05)
        machine.on(Event.ROOM_MATCH, f"arrived {portal['to']}")
        sim_context["room"] = portal["to"]
        return True

    if kind == "state_check":
        state = sim_context["states"].get(step["state_id"], False)
        print(f"  [SIM] {machine.state.name}  → state_check {step['state_id']} = {state}")
        if not state:
            sim_context["states"][step["state_id"]] = True
            print("  [SIM]      state now True (simulated precondition trigger)")
        return True

    if kind == "move":
        target = step["target"]
        if sim_context["room"] == "room_B" and target == "lm_left_wing_end" and not sim_context.get("lm_end_ok"):
            sim_context["lm_end_ok"] = True
            print(f"  [SIM] {machine.state.name}  → move {target} FAILED (template miss)")
            _emit(bus, execution_id, "observation",
                  detail=f"template:{target} miss",
                  context={"room": sim_context["room"], "observer": "template_match", "confidence": 0.31})
            machine.on(Event.EVENT_INTERRUPTED, "move fail")
            machine.on(Event.RECOVER_OK, "retry after recovery")
            print(f"  [SIM] {machine.state.name}  → move {target} retry OK")
        else:
            print(f"  [SIM] {machine.state.name}  → move to landmark {target} OK")
            _emit(bus, execution_id, "action_executed", detail=f"move:{target}",
                  context={"room": sim_context["room"], "reason": "move_to_landmark",
                           "source": "decision_layer", "naturalized": True})
        return True

    if kind == "visual_guided_move":
        print(f"  [SIM] {machine.state.name}  → visual_guided_move {step.get('ticks')} ticks x {step.get('step_seconds')}s")
        return True

    if kind == "interact":
        print(f"  [SIM] {machine.state.name}  → interact template={step['template']} (click)")
        return True

    if kind == "verify":
        print(f"  [SIM] {machine.state.name}  → verify signal={step['signal']} expected={step['expected']}")
        return True

    if kind == "wait":
        print(f"  [SIM] {machine.state.name}  → wait {step.get('seconds', 1)}s")
        return True

    print(f"  [SIM] unknown step type: {kind}")
    return False


def dry_run(pkg_dir, target_ids=None, bus=None, execution_id=None):
    pkg = KnowledgePackage(Path(pkg_dir))
    print(f"== dry_run: {pkg.root.name} ==")
    print(f"   verifies: {DRY_RUN_VERIFIES}")
    print(f"   NOT verified: {DRY_RUN_NOT_VERIFIES}")

    caps = CapabilityRegistry()
    try:
        caps.check_requirements(pkg.meta.get("requires", []), knowledge_id=pkg.root.name)
    except Exception:
        # Bug 77：能力检查失败带完整堆栈
        import logging
        logging.getLogger("runtime.dry_run").exception("capability check failed")
        print("  [ERROR] capability check failed")
        return 1

    from ingest.compiler.validate_graph import validate

    errors, warnings = validate(pkg, verbose=False)
    if errors:
        for e in errors:
            print(f"  [ERROR] {e}")
        print("dry_run 中止: 知识包校验未通过")
        _emit(bus, execution_id, "run_finished", context={"result": "invalid"})
        return 1

    spawn = pkg.spawn_room()
    print(f"spawn_room = {spawn}")
    targets = target_ids or [c["id"] for c in pkg.chests]

    for cid in targets:
        sim_context = {"room": spawn, "states": {}, "lm_end_ok": False}

        def logger(prev, new, action, reason, _cid=cid):
            print(f"    {prev:>26} → {new:<26} {reason}")
            _emit(bus, execution_id, "state_changed",
                  from_state=prev, to_state=new, detail=reason,
                  context={"target": _cid, "action": action})

        machine = StateMachine(target_id=cid, room=spawn, logger=logger)
        print(f"\n== target {cid} ==")
        _emit(bus, execution_id, "target_progress",
              detail=f"start:{cid}", context={"target": cid, "status": "running"})
        machine.on(Event.START, "dry_run start")
        machine.on(Event.ROOM_MATCH, f"in {spawn}")
        wf = pkg.workflow(cid)
        if wf is None:
            # 真实点位无 workflow（VLM 只提取坐标，执行流程未生成）——明确失败而非 TypeError
            print(f"  [SKIP] {cid} 无执行流程（workflow 未生成）")
            _emit(bus, execution_id, "target_progress",
                  detail=f"skip:{cid}:no_workflow",
                  context={"target": cid, "status": "failed",
                           "reason": "no_workflow", "category": "F3"})
            continue
        for i, step in enumerate(wf["steps"]):
            if machine.state in (State.DONE, State.ABORT):
                break
            simulate_step(machine, step, pkg, sim_context, bus=bus, execution_id=execution_id)
            if machine.state in (State.DONE, State.ABORT):
                break
        if machine.state == State.NAVIGATING:
            machine.on(Event.TARGET_VISIBLE, "simulated target visible")
            machine.on(Event.TARGET_VERIFIED, "simulated verified")
            machine.on(Event.INTERACT_OK, "simulated interaction ok")
        ok = machine.state == State.DONE
        _emit(bus, execution_id, "target_progress",
              detail=f"finish:{cid}:{'ok' if ok else 'fail'}",
              context={"target": cid, "status": "done" if ok else "failed"})
        print(f"  [SIM] final state = {machine.state.name}  (exec {machine.execution_id})")
        if ok:
            print(f"  [RESULT] {cid} PASS (logical) — 仅验证 {DRY_RUN_VERIFIES}，不代表真机可用")
        else:
            print(f"  [RESULT] {cid} FAIL")
        for h in machine.history:
            print(f"    {h[0]:>26} → {h[1]:<26} {h[3]}")
    return 0


if __name__ == "__main__":
    sys.exit(dry_run(sys.argv[1], sys.argv[2:] or None))
