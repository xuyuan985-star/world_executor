# WorldExecutor 源码索引（AI 友好版）

> 生成时间：2026-08-08（第 51 轮后）

> 使用：按需读取 `01_<模块>.py`；manifest.json 提供符号级摘要。

| 模块 | 职责/关键符号 | 依赖 |
|---|---|---|
| `config/settings.py` | def get；def qwen_api_key；def qwen_base_url；def qwen_model；def qwen_vlm_analyze_model；def qwen_vlm_structure_model | os, pathlib |
| `gui/main_window.py` | class MainWindow；def closeEvent；class HealthWorker；def run | PySide6.QtCore, PySide6.QtWidgets, gui.pages.command_deck, gui.pages.placeholder, gui.theme |
| `gui/pages/command_deck.py` | def card_layout；def card_title；def category_text；class TargetRow；class ObservationSnapshot；class RuntimeHealthBar | PySide6.QtCore, PySide6.QtWidgets, gui.state_machine_view, qfluentwidgets |
| `gui/pages/guides_view.py` | class GuidesView；def reload | PySide6.QtCore, PySide6.QtWidgets, json, pathlib, qfluentwidgets |
| `gui/pages/placeholder.py` | def card_layout；def card_title；def placeholder_page；class WorldGraphPage；class ObservationPage；class KnowledgePage | PySide6.QtCore, PySide6.QtWidgets, gui.pages.guides_view, pathlib, qfluentwidgets |
| `gui/run.py` | def main | PySide6.QtWidgets, ctypes, gui.main_window, gui.theme, pathlib |
| `gui/state_machine_view.py` | class _Canvas；class StateMachineView；def paintEvent；def on_state；def add_overlay；def reset | PySide6.QtCore, PySide6.QtGui, PySide6.QtWidgets, gui.theme |
| `gui/theme.py` | def apply_theme | PySide6.QtCore, PySide6.QtGui, qfluentwidgets |
| `ingest/archive_video.py` | def resolve_map_area；def room_to_area；def make_point；def archive_point；def main | argparse, ingest.capture_frames, ingest.vlm_client, json, pathlib |
| `ingest/bilibili.py` | class BiliError；def get_cookie；def http_get；def pages_of；def playurl；def pick_stream | argparse, config, json, pathlib, subprocess |
| `ingest/bilibili_test.py` | def http_get；def get_pages；def get_playurl；def main | json, sys, urllib.parse, urllib.request |
| `ingest/capture_frames.py` | def extract_frames；def ask_frame；def main | ingest.vlm_client, json, pathlib, re, subprocess |
| `ingest/compiler/validate_graph.py` | def validate；def main | json, pathlib, runtime.knowledge_loader, sys |
| `ingest/crop_templates.py` | def norm_box；def crop；def main | PIL, json, pathlib, sys |
| `ingest/download_all.py` | def main | ingest, pathlib, sys |
| `ingest/probe_models.py` | def probe；def main | config, json, pathlib, requests, sys |
| `ingest/review_templates.py` | def main | base64, ingest.vlm_client, json, pathlib, sys |
| `ingest/vlm_client.py` | class SegmentNarrative；class QuotaExhausted；class VLMProvider；class QwenVLProvider；def get_provider；def list_available_models | base64, config, dataclasses, json, requests |
| `live_monitor.py` | def window_info；def capture_screen；def main | PIL, ctypes, mss, os, pathlib |
| `live_probe.py` | def main | ctypes, module.automation, os, pathlib, runtime.observers.vlm_vision |
| `runtime/action_intent.py` | class ActionType；class ActionMethod；class ActionIntent；def to_context | dataclasses, enum, types, typing, uuid |
| `runtime/api/commands.py` | class MissionSpec；class RuntimeAPI；def start_mission；def pause；def request_pause_human；def resume_check | dataclasses, ingest.compiler.validate_graph, pathlib, runtime, runtime.capability |
| `runtime/capabilities.py` | class CapabilityRegistry；class CapabilityError；def status；def is_ready；def check_requirements；def summary | pathlib, yaml |
| `runtime/capability.py` | class CapabilityReport；def detect_capability；def detect_capability_with_tests；def input_available；def capture_available；def to_context | dataclasses, runtime.health |
| `runtime/db.py` | def conn；def init；def record_event；def replay_events；def record_state_observation；def record_fail | config, json, pathlib, sqlite3, threading |
| `runtime/decision/action.py` | — | runtime.action_intent |
| `runtime/drivers/march7th/__init__.py` | — | runtime.drivers.march7th.driver |
| `runtime/drivers/march7th/driver.py` | class March7thDriver；def get_driver | runtime.drivers.march7th.input, runtime.drivers.march7th.vision, runtime.drivers.march7th.window |
| `runtime/drivers/march7th/input.py` | class March7thInputBackend；def click；def move；def press_key；def release_key；def execute | module.automation, pyautogui, runtime.drivers.march7th.window, runtime.input.base, time |
| `runtime/drivers/march7th/vision.py` | class March7thVision；def validator；def take_screenshot；def screenshot_path；def ocr_lines；def find_text | module.automation, module.ocr, numpy, pathlib, runtime.drivers.march7th.window |
| `runtime/drivers/march7th/window.py` | def find_game_window；def set_foreground_with_retry；def ensure_march7th_env；def cb | ctypes, os, pathlib, security.quarantine, sys |
| `runtime/dry_run.py` | def simulate_step；def dry_run；def logger | ingest.compiler.validate_graph, pathlib, runtime.capabilities, runtime.events.schema, runtime.knowledge_loader |
| `runtime/errors.py` | class ErrorCode；def code_of；def classify | enum |
| `runtime/events/bus.py` | class EventBus；def subscribe；def publish；def replay；def close；def load | collections, json, logging, pathlib, runtime |
| `runtime/events/schema.py` | class WorldEvent；def make_event；class Observation；def to_dict；def to_event | dataclasses, enum, time, typing, uuid |
| `runtime/execution.py` | class ExecutionResult；def execution_failure；def to_context | dataclasses, runtime.errors |
| `runtime/execution_router.py` | class ExecutionRouter；def input；def execute；def capability_input；def from_capability | runtime.input.base, runtime.input.observe |
| `runtime/failure_memory.py` | class FailureMemory；def record；def query；def count | json, pathlib, time |
| `runtime/failure_report.py` | def environment_snapshot；class FailureReporter；def report | ctypes, json, pathlib, platform, security.quarantine |
| `runtime/guards/__init__.py` | — |  |
| `runtime/guards/action_guard.py` | class ActionGuard；def check；def allow | runtime.guards.policy, runtime.guards.risk, time |
| `runtime/guards/policy.py` | def confidence_for；def is_critical；def allowed；def risk_limit |  |
| `runtime/guards/risk.py` | def calculate_risk |  |
| `runtime/health.py` | def check_health；class MOUSEINPUT；class INPUT | ctypes, numpy, runtime.drivers.march7th.vision, runtime.drivers.march7th.window, runtime.observers.vlm_vision |
| `runtime/input/__init__.py` | def get_backend | runtime.drivers.march7th.input, runtime.input.base, runtime.input.mock_backend, runtime.input.win32_backend |
| `runtime/input/base.py` | class InputResult；class InputBackendProtocol；class InputBackend；def to_context；def click；def press_key | dataclasses, typing |
| `runtime/input/mock_backend.py` | class MockBackend；def click；def move；def press_key；def release_key；def execute | runtime.input.base |
| `runtime/input/observe.py` | class ObserveOnlyInput；def click；def press_key；def release_key；def click_template；def click_text | runtime.input.base |
| `runtime/input/replay.py` | class ReplayInput；def consumed；def click；def press_key；def release_key；def click_template | runtime.input.base |
| `runtime/input/win32_backend.py` | class Win32Backend；def click；def move；def press_key；def release_key；class MOUSEINPUT | ctypes, runtime.input.base, time |
| `runtime/knowledge_loader.py` | class KnowledgePackage；def package_hash；def workflow；def verify_expectations；def spawn_room；def room_ids | hashlib, json, logging, pathlib |
| `runtime/naturalness.py` | class NaturalnessPolicy；def click_delay；def interaction_delay；def transition_wait；def sprint_duration；def rotate_duration | random |
| `runtime/observation.py` | class Observation；def to_context | dataclasses |
| `runtime/observation_memory.py` | class StableState；def update；def label | dataclasses |
| `runtime/observation_store.py` | class ObservationRecord；class ObservationStore；def is_stale；def set；def get；def snapshot | time |
| `runtime/observers/__init__.py` | — |  |
| `runtime/observers/vlm_vision.py` | class VLMVisionObserver；def observe_room；def locate_target；def heading_check；def sample_stability | base64, collections, ingest.vlm_client, json, pathlib |
| `runtime/orchestrator.py` | class SessionWatchdog；class TargetRecord；class WorkflowOrchestrator；def touch；def run；def stop | ctypes, dataclasses, pathlib, runtime.action_intent, runtime.drivers.march7th.window |
| `runtime/planner.py` | class Planner；def decide；def plan_interact；def plan；def plan_wait；def action_of | runtime.action_intent, runtime.observation, runtime.world_state |
| `runtime/platform/__init__.py` | — |  |
| `runtime/platform/windows/__init__.py` | — |  |
| `runtime/platform/windows/capture.py` | class Frame；class CaptureManager；def frame_hash；def capture | dataclasses, hashlib, runtime.drivers.march7th.vision, time |
| `runtime/platform/windows/coords.py` | class CoordinateSpace；def logical_to_physical；def physical_to_logical；def screenshot_to_screen；def from_scale_factor | dataclasses |
| `runtime/platform/windows/privilege.py` | def init_dpi；def is_admin；def require_admin；def relaunch_as_admin | ctypes, os, sys |
| `runtime/platform/windows/window.py` | class GameWindow；def score_window；def find_best_window | dataclasses, runtime.win_capture |
| `runtime/recovery/__init__.py` | — |  |
| `runtime/recovery/manager.py` | class RecoveryManager；def recover_capture；def recover_window；def to_context | time |
| `runtime/safety.py` | class EmergencyMonitor；def run；def is_paused；def resume；def stop | ctypes, runtime.events.schema, threading, time |
| `runtime/state_machine.py` | class StateMachine；def on | enum, runtime, time, uuid |
| `runtime/step_executor.py` | def recovery_for；def subclass_for；def retryable_for；class RealExecutor；def input；def set_input_backend | collections, pathlib, runtime.action_intent, runtime.drivers.march7th, runtime.errors |
| `runtime/vision_gate.py` | class VisionDecision；class OCREvidence；class VLMEvidence；class VisionEvidence；class VisionGate；def dump_vision_decision | dataclasses, json, pathlib, time |
| `runtime/vision_observer.py` | class OCRAdapter；def validate_vlm_output；class VLMAdapter；class VisionObserver；def fuse_observation；def detect | numpy, runtime.observation |
| `runtime/vision_quality.py` | class CaptureResult；class FrameValidator；def check_static；def validate | dataclasses, numpy |
| `runtime/win_capture.py` | def process_identity；def find_game_window；class WindowStateMonitor；def try_capture_window；def set_foreground_with_retry；def capture_game_foreground | PIL, ctypes, ctypes.wintypes, mss, time |
| `runtime/world_state.py` | class WorldState；def update；def to_context | dataclasses |
| `security/__init__.py` | — |  |
| `security/quarantine.py` | def install_pylnk3_stub；def install_security_stubs；def require_m7_path；def sanitize_text；def sanitize_mapping；class Lnk | pathlib, sys, types |
| `smoke_test.py` | def require_m7；def main | module.automation, module.ocr, numpy, os, pathlib |
| `tests/planner/test_planner.py` | def main；class FakePkg；def workflow | pathlib, runtime.failure_memory, runtime.knowledge_loader, runtime.planner, runtime.world_state |
| `tests/replay/test_action_replay.py` | def load_events；def replay；def replay_failure；def main；def driver_factory；def driver_factory | json, pathlib, runtime.events.bus, runtime.input.replay, runtime.knowledge_loader |
| `tests/vision/test_gate.py` | def ev；def main；class VLMDead；def observe | numpy, pathlib, runtime.observation, runtime.observation_memory, runtime.vision_gate |
| `tools/action_guard_test.py` | def make_intent；def main；class Obs；class ObsFake；def intent_risk | pathlib, runtime.action_intent, runtime.guards.action_guard, runtime.guards.policy, runtime.guards.risk |
| `tools/architecture_check.py` | def check_file；def find_cycles；def main；def nearest；def dfs | argparse, ast, json, pathlib, sys |
| `tools/calibration/click_test.py` | def tee；def ocr_lines；def box_center；def main | json, module.automation, module.ocr, numpy, os |
| `tools/coords_calibrate.py` | def main | ctypes, module.automation, module.ocr, numpy, os |
| `tools/diag_frames.py` | def main | PIL, ctypes, json, numpy, os |
| `tools/export_issue_report.py` | def main | argparse, json, pathlib, security.quarantine, shutil |
| `tools/input_privilege_check.py` | def is_admin；def main | ctypes, ctypes.wintypes, os, pathlib, runtime.drivers.march7th.window |
| `tools/run_gate.py` | def run；def py；def architecture；def security；def units；def replay | argparse, ast, pathlib, runtime.errors, security.quarantine |
| `tools/sendinput_probe.py` | def probe_setcursor；def probe_sendinput；def main；class INPUT；class _MOUSEINPUT | ctypes, ctypes.wintypes, sys, time |
| `tools/smoke_orchestrator.py` | class FakeAuto；class FakeInput；class FakeVision；class FakeVisionDPI125；class FakeDriver；class FakeVLM | inspect, pathlib, runtime.events.bus, runtime.guards.action_guard, runtime.input.base |
| `tools/windows_stability_test.py` | def main | argparse, ctypes, ctypes.wintypes, numpy, pathlib |