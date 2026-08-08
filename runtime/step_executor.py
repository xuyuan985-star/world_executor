import sys
import time
from pathlib import Path

from runtime.naturalness import NaturalnessPolicy
from runtime.observers.vlm_vision import VLMVisionObserver

M7_ROOT = Path(__file__).resolve().parent.parent.parent / "March7thAssistant"


class RealExecutor:
    def __init__(self, pkg, bus=None, execution_id=None, use_vlm=True):
        self.pkg = pkg
        self.bus = bus
        self.execution_id = execution_id
        self.naturalness = NaturalnessPolicy()
        self.vlm = VLMVisionObserver() if use_vlm else None
        self.auto = None

    def _emit(self, event_type, **kw):
        if self.bus is not None:
            from runtime.events.schema import make_event
            self.bus.publish(make_event(event_type, self.execution_id, **kw))

    def ensure_auto(self):
        if self.auto is not None:
            return self.auto
        sys.path.insert(0, str(M7_ROOT))
        from module.automation import auto
        self.auto = auto
        return auto

    def screenshot_path(self):
        auto = self.ensure_auto()
        shot, _, _ = auto.take_screenshot()
        from PIL import Image
        import numpy as np
        tmp = Path("ingest/raw/frames/live") / f"shot_{int(time.time()*1000)}.jpg"
        tmp.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(np.asarray(shot)[:, :, ::-1]).save(tmp, "JPEG", quality=90)
        return tmp

    def observe_room(self, room_ids):
        if self.vlm is None:
            return None, None
        shot = self.screenshot_path()
        data = self.vlm.observe_room(shot, room_ids)
        room = data.get("room")
        confidence = data.get("confidence")
        ui_state = data.get("ui_state")
        self._emit("observation", detail=f"room:{room}",
                   context={"observer": "vlm_vision", "target": "room_id",
                            "confidence": confidence, "room": room, "ui_state": ui_state})
        return room, confidence

    def locate_target(self, target_desc):
        if self.vlm is None:
            return None
        shot = self.screenshot_path()
        data = self.vlm.locate_target(shot, target_desc)
        found = data.get("found") is True
        x, y = data.get("screen_x"), data.get("screen_y")
        if found and x and y:
            x = float(x) / 1000.0
            y = float(y) / 1000.0
        self._emit("observation", detail=f"locate:{'found' if found else 'miss'}",
                   context={"observer": "vlm_vision", "target": target_desc,
                            "confidence": data.get("confidence"), "screen_x": x, "screen_y": y})
        return (x, y) if found else None

    def click_at(self, x, y, label="click"):
        auto = self.ensure_auto()
        auto.mouse_move(int(x * auto.width), int(y * auto.height))
        delay = self.naturalness.click_delay()
        time.sleep(delay)
        auto.mouse_click()
        self._emit("action_executed", detail=f"{label}@({x:.2f},{y:.2f})",
                   context={"naturalized": True, "delay_ms": int(delay * 1000)})

    def interact_template(self, template, threshold, scale_range):
        auto = self.ensure_auto()
        top_left, bottom_right, match = auto.find_image_element(
            str(self.pkg.templates_dir / template), threshold, scale_range, relative=True)
        if top_left is None:
            return False
        cx = (top_left[0] + bottom_right[0]) / 2
        cy = (top_left[1] + bottom_right[1]) / 2
        delay = self.naturalness.interaction_delay()
        time.sleep(delay)
        auto.mouse_click(cx, cy)
        self._emit("action_executed", detail=f"click:{template}",
                   context={"naturalized": True, "delay_ms": int(delay * 1000), "match": round(match, 3)})
        return True

    def move_visual_guided(self, target_desc, ticks, step_seconds):
        for i in range(ticks):
            pos = self.locate_target(target_desc)
            if pos is None:
                break
            x, y = pos
            if 0.4 < x < 0.6:
                dur = self.naturalness.sprint_duration(step_seconds)
                auto = self.ensure_auto()
                auto.press_key("w", wait_time=dur)
                self._emit("action_executed", detail=f"move_forward:{dur:.1f}s",
                           context={"naturalized": True, "tick": i})
            else:
                side = "d" if x < 0.5 else "a"
                auto = self.ensure_auto()
                auto.press_key(side, wait_time=self.naturalness.rotate_duration())
                self._emit("action_executed", detail=f"steer:{side}",
                           context={"naturalized": True, "tick": i})
        return True

    def portal_transition(self, portal, wait_base):
        auto = self.ensure_auto()
        trigger = portal["trigger"]
        ok = self.interact_template(trigger["template"], trigger["threshold"], trigger["scale_range"])
        if not ok:
            return False
        wait = self.naturalness.transition_wait(wait_base)
        time.sleep(wait)
        return True

    def verify_signal(self, template, expected, timeout):
        auto = self.ensure_auto()
        deadline = time.time() + timeout
        while time.time() < deadline:
            top_left, _, _ = auto.find_image_element(
                str(self.pkg.templates_dir / template), 0.8, (0.9, 1.1), relative=True)
            found = top_left is not None
            if (expected == "vanished" and not found) or (expected == "present" and found):
                return True
            time.sleep(1.5)
        return False
