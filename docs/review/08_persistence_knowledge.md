# R8 持久化与知识层审查（2026-08-12）

## SQLite（runtime/db.py）

- 线程本地连接（threading.local）+ WAL + synchronous=NORMAL + timeout=30
- 7 表：progress/events/fail_log/repair_log/statistics/cache/state_observation + 4 索引
- record_event：events 表 context JSON 序列化（含路径等——脱敏面，R19 核对）
- start_progress/record_state_observation：状态机每次迁移落库
- 无显式连接关闭（进程级 WAL，可接受）

## 知识包（runtime/knowledge_loader.py）

- 结构：package.json（schema_version=1 + environment + game_version）/ rooms.json / portals.json / landmarks.json / chests.json / templates/ / workflows/
- 防护：schema_version 不匹配拒绝加载（fail-fast）；game_version≠2.x 告警不拒绝；JSON 损坏 → KnowledgeCorruptError；缺文件 → None（区分）；id 唯一性校验（DuplicateIDError）；chests 排序稳定（Bug 104）
- environment 标记（test 包禁正式执行——调用方据此拒绝）
- package_hash：Merkle 式指纹（json + workflows + 模板全部参与，相对路径参与 hash）
- 索引：chests by id/room、portals by id、rooms by id（O(1) 查询）
- workflow 缓存冻结（#28：运行中改文件不影响执行链）
- entity_position：只认 normalized 坐标（0-1），absolute/未知拒绝兜底
- verify_expectations：workflow verify 步骤的 OCR（must/forbid/context 表达）/VLM 声明

## 攻略数据（knowledge/guides_loader.py）

- guides/maps/<map_id>/{map.json, areas/, points/}
- POINT_TYPES 9 类（chest/warptrotter/puzzle/book/enemy/achievement/quest/shop/anchor）
- 08_custom 自定义地图：sync_custom_map 把 trajectories/*.json 同步为点位（id=文件名去扩展名，trajectory 字段指向原文件）；enabled 集控制启用状态（None=全量）
- custom_enabled_names：读 08_custom/points/chests.json 的 trajectory 集合（勾选状态持久化）
- load_guide_targets/load_guide_regions：GUI 展示用

## 轨迹数据（knowledge/trajectories/）

- 结构：version/recorded_at/client_w/client_h/game_sensitivity/events[]/count
- 事件类型：key（+duration）/ click（nx/ny/duration）/ view_dx/view_dy（归一化位移）
- 示例 自定义-1.json：1920x1080 录制，game_sensitivity=4，视角事件 time_sleep 1-2s

## 配置（config/settings.py）

- .env 文件 + 环境变量 + 运行时覆盖（set_override 进程内生效）
- PyInstaller：_MEIPASS 兼容
- 关键函数：qwen_*（VLM 配置）、default_map、knowledge_root、runtime_db_path、march7_root
- validate_config：启动自检

## 生命周期/资源（runtime/lifecycle.py + resource.py）

- AppLifecycle：AppState 枚举 + StartupStage（启动卡点报告）
- resource.register/_shutdown：进程级清理注册表 + atexit 倒序清理
- ResourceMonitor：10s 采样 CPU/内存（psutil 降级 ctypes），告警日志；history 60 条

## 可疑点（阶段二验证）

1. `db.record_event` 每次 commit——WAL 下高频事件（action/observation）每事件一次 commit，性能可优化（批量）；但同步性优先，可接受
2. 08_custom/areas/custom.json 和 map.json 每次 sync_custom_map 都重写——多进程并发写可能交错（GUI + runner？）——实际只有 GUI 调用，OK
3. sync_custom_map 写文件无锁——refresh_command_deck 与启动同步可能并发（同线程顺序执行，OK）
4. custom_enabled_names 空集 vs None 语义（第 10 轮修复：空集→None 全量启用）——已修
5. `KnowledgePackage.workflow` 缓存无上限（target_id 无限增长？——目标集有限，OK）
6. guides map.json 的 game_version=3.x vs 运行器 EXPECTED_GAME_VERSION=2.x——告警但继续；注意 02 地图声明 3.x 会每次加载告警（噪音但无害）
