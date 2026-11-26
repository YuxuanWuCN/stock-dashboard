-- =============================================================================
-- R-FOF 下周期 · 软工程平台（成员 3 / SE）
-- SQLite 业务与行为日志库（SQLite 3.35+，启用外键、CHECK 与 WAL）
--
-- 设计口径（与 Issue #13 信管同学 B 的字段对齐）
--   * 全表禁止出现真实姓名 / 身份证 / 手机号 / 精确住址 / IP 等可识别字段；
--   * 匿名主体只以 session_id（前端生成的 32 位十六进制）标识；
--   * ui_ab_events 的字段名严格采用 Issue #14 约定：
--     session_id, ab_group, age_group, scenario_dd, panic_redeem_clicked,
--     decision_latency_ms, comprehension_score
--   * scenario_dd 为“模拟市场暴跌幅度（百分数）”，取值集合 {0, -10, -20}；
--     comprehension_score 为 3 道规则理解小测试的答对题数，取值 [0, 3]；
--   * 时间统一存 UTC ISO-8601（毫秒精度），展示层再按 Asia/Shanghai 渲染。
--
-- 可重复执行：本文件全部使用 IF NOT EXISTS / OR REPLACE，重复 apply 不会破坏数据。
-- =============================================================================

-- 连接级 PRAGMA：只在当前连接生效，随 init 脚本再次设置，避免依赖客户端默认值。
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;

-- -----------------------------------------------------------------------------
-- 0. 元数据：schema 版本（供后续迁移脚本比对）
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS schema_meta (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

INSERT INTO schema_meta (key, value) VALUES ('schema_version', '1')
    ON CONFLICT(key) DO UPDATE SET
        value      = excluded.value,
        updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now');

-- -----------------------------------------------------------------------------
-- 1. user_profiles：匿名会话画像（不含任何直接标识）
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS user_profiles (
    profile_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id       TEXT NOT NULL UNIQUE
                     CHECK (length(session_id) BETWEEN 8 AND 64),
    -- 青年 / 长者 / 未申明（社区平板实地采集允许不填）
    age_group        TEXT NOT NULL
                     CHECK (age_group IN ('youth', 'elder', 'unspecified')),
    -- 采集渠道：校园预实验 / 社区调研 / 线上 / 实验室
    cohort           TEXT NOT NULL DEFAULT 'online'
                     CHECK (cohort IN ('campus', 'community', 'online', 'lab')),
    -- A/B 实验分组（组间设计，会话建立时一次性分配，之后不可变更）
    ab_group         TEXT NOT NULL
                     CHECK (ab_group IN ('A', 'B')),
    -- 知情同意范围：仅统计 / 统计 + 研究引用（不涉及二次识别）
    consent_scope    TEXT NOT NULL DEFAULT 'analytics_only'
                     CHECK (consent_scope IN ('analytics_only', 'analytics_and_research')),
    device_class     TEXT NOT NULL DEFAULT 'unknown'
                     CHECK (device_class IN ('phone', 'tablet', 'desktop', 'unknown')),
    -- 只保留时区名（如 Asia/Shanghai），不保存经纬度或住址
    client_zone      TEXT CHECK (client_zone IS NULL OR length(client_zone) <= 64),
    created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_profiles_group_age
    ON user_profiles (ab_group, age_group);

-- 画像一旦创建，ab_group / age_group / cohort 不允许被改写（组间设计完整性）。
CREATE TRIGGER IF NOT EXISTS trg_profiles_immutable_group
BEFORE UPDATE OF ab_group, age_group, cohort ON user_profiles
WHEN NEW.ab_group IS NOT OLD.ab_group
  OR NEW.age_group IS NOT OLD.age_group
  OR NEW.cohort IS NOT OLD.cohort
BEGIN
    SELECT RAISE(ABORT, 'profile assignment is immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_profiles_touch
AFTER UPDATE ON user_profiles
WHEN NEW.updated_at = OLD.updated_at
BEGIN
    UPDATE user_profiles
       SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
     WHERE profile_id = NEW.profile_id;
END;

-- -----------------------------------------------------------------------------
-- 2. survey_responses：长表（一行一个题项），字段与 #13 问卷对齐
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS survey_responses (
    response_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id    TEXT NOT NULL
                  REFERENCES user_profiles(session_id) ON DELETE CASCADE,
    -- sus: 系统可用性量表；lsi: 养老焦虑/损失敏感度量表；rules_quiz: 3 题规则理解
    instrument    TEXT NOT NULL
                  CHECK (instrument IN ('sus', 'lsi', 'rules_quiz')),
    item_code     TEXT NOT NULL CHECK (length(item_code) BETWEEN 1 AND 32),
    item_value    REAL NOT NULL,
    sequence      INTEGER NOT NULL DEFAULT 0 CHECK (sequence >= 0),
    answered_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    -- 同一会话同一量表的同一题项只保留最后一次作答（upsert 语义由 DAO 保证）
    UNIQUE (session_id, instrument, item_code)
);

CREATE INDEX IF NOT EXISTS idx_survey_session ON survey_responses (session_id);
CREATE INDEX IF NOT EXISTS idx_survey_instrument ON survey_responses (instrument, item_code);

-- 题项取值域：SUS 单题 1-5；LSI 单题 1-5；规则理解单题 0/1
CREATE TRIGGER IF NOT EXISTS trg_survey_value_range
BEFORE INSERT ON survey_responses
WHEN (NEW.instrument IN ('sus', 'lsi') AND (NEW.item_value < 1 OR NEW.item_value > 5))
  OR (NEW.instrument = 'rules_quiz' AND NEW.item_value NOT IN (0, 1))
BEGIN
    SELECT RAISE(ABORT, 'survey item value out of range');
END;

-- upsert 走 UPDATE 分支时 INSERT 触发器不会触发，这里补一道 UPDATE 闸门。
CREATE TRIGGER IF NOT EXISTS trg_survey_value_range_update
BEFORE UPDATE OF item_value ON survey_responses
WHEN (NEW.instrument IN ('sus', 'lsi') AND (NEW.item_value < 1 OR NEW.item_value > 5))
  OR (NEW.instrument = 'rules_quiz' AND NEW.item_value NOT IN (0, 1))
BEGIN
    SELECT RAISE(ABORT, 'survey item value out of range');
END;

-- -----------------------------------------------------------------------------
-- 3. lifecycle_ledger：各策略逐日账本归档（由 #12 的净值序列灌入）
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS lifecycle_ledger (
    ledger_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    -- 如 'R-FOF-A4' / 'TDF-2040' / 'A-only'
    strategy_id    TEXT NOT NULL CHECK (length(strategy_id) BETWEEN 1 AND 48),
    -- base: 真实历史；dd10/dd20: 暴跌压力情景
    scenario       TEXT NOT NULL CHECK (scenario IN ('base', 'dd10', 'dd20')),
    trade_date     TEXT NOT NULL
                   CHECK (trade_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    nav            REAL NOT NULL CHECK (nav > 0),
    daily_return   REAL CHECK (daily_return IS NULL OR daily_return > -1),
    -- 回撤以负数百分数记录（-12.5 表示 -12.5%）
    drawdown       REAL NOT NULL CHECK (drawdown <= 0),
    -- 单向棘轮已锁定的养老安全垫金额（元，>=0）
    locked_floor   REAL NOT NULL CHECK (locked_floor >= 0),
    source_sha256  TEXT CHECK (source_sha256 IS NULL OR length(source_sha256) = 64),
    UNIQUE (strategy_id, scenario, trade_date)
);

CREATE INDEX IF NOT EXISTS idx_ledger_strategy_date
    ON lifecycle_ledger (strategy_id, trade_date);

-- -----------------------------------------------------------------------------
-- 4. ui_ab_events：A/B 实验交互日志（Issue #14 约定字段，一个事件一行）
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ui_ab_events (
    event_id               INTEGER PRIMARY KEY AUTOINCREMENT,
    -- 前端生成的事件 UUID，用于离线补传幂等（同一 UUID 只落库一次）
    event_uuid             TEXT NOT NULL UNIQUE
                           CHECK (length(event_uuid) BETWEEN 8 AND 64),
    session_id             TEXT NOT NULL
                           REFERENCES user_profiles(session_id) ON DELETE CASCADE,
    ab_group               TEXT NOT NULL CHECK (ab_group IN ('A', 'B')),
    age_group              TEXT NOT NULL
                           CHECK (age_group IN ('youth', 'elder', 'unspecified')),
    -- 模拟市场暴跌幅度（百分数）：0 / -10 / -20
    scenario_dd            REAL NOT NULL
                           CHECK (scenario_dd IN (0.0, -10.0, -20.0)),
    event_type             TEXT NOT NULL DEFAULT 'decision'
                           CHECK (event_type IN ('page_load', 'scenario_view',
                                                 'decision', 'quiz_submit')),
    panic_redeem_clicked   INTEGER NOT NULL DEFAULT 0
                           CHECK (panic_redeem_clicked IN (0, 1)),
    -- 决策耗时（毫秒），0 - 3600000（上限 1 小时，越界视为异常采集）
    decision_latency_ms    INTEGER NOT NULL
                           CHECK (decision_latency_ms BETWEEN 0 AND 3600000),
    -- 3 道规则理解测试答对题数
    comprehension_score    REAL NOT NULL DEFAULT 0
                           CHECK (comprehension_score BETWEEN 0 AND 3),
    -- 兼容离线浏览器的原始采集时间（客户端时钟，仅作参考）
    client_ts              TEXT,
    server_ts              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    source                 TEXT NOT NULL DEFAULT 'web'
                           CHECK (source IN ('web', 'offline_import', 'lab')),
    export_batch           TEXT
);

CREATE INDEX IF NOT EXISTS idx_events_session ON ui_ab_events (session_id);
CREATE INDEX IF NOT EXISTS idx_events_group_age
    ON ui_ab_events (ab_group, age_group, scenario_dd);
CREATE INDEX IF NOT EXISTS idx_events_type ON ui_ab_events (event_type, server_ts);
CREATE INDEX IF NOT EXISTS idx_events_source ON ui_ab_events (source);

-- -----------------------------------------------------------------------------
-- 5. 分析视图：直接服务 #13 的卡方 / Fisher / Logistic 取数
-- -----------------------------------------------------------------------------
CREATE VIEW IF NOT EXISTS v_ab_decision_stats AS
SELECT
    ab_group,
    age_group,
    scenario_dd,
    COUNT(*)                                            AS decisions,
    SUM(panic_redeem_clicked)                           AS panic_redeems,
    ROUND(100.0 * SUM(panic_redeem_clicked) / COUNT(*), 2) AS panic_rate_pct,
    ROUND(AVG(decision_latency_ms), 1)                  AS avg_latency_ms,
    ROUND(AVG(comprehension_score), 2)                  AS avg_comprehension
FROM ui_ab_events
WHERE event_type = 'decision'
GROUP BY ab_group, age_group, scenario_dd;

CREATE VIEW IF NOT EXISTS v_ab_session_coverage AS
SELECT
    p.ab_group,
    p.age_group,
    p.cohort,
    COUNT(DISTINCT p.session_id)                        AS sessions,
    COUNT(DISTINCT e.session_id)                        AS sessions_with_events,
    SUM(CASE WHEN e.event_type = 'quiz_submit' THEN 1 ELSE 0 END) AS quiz_submissions
FROM user_profiles AS p
LEFT JOIN ui_ab_events AS e ON e.session_id = p.session_id
GROUP BY p.ab_group, p.age_group, p.cohort;

CREATE VIEW IF NOT EXISTS v_survey_wide AS
SELECT
    r.session_id,
    p.ab_group,
    p.age_group,
    p.cohort,
    SUM(CASE WHEN r.instrument = 'sus' THEN r.item_value END) AS sus_total,
    SUM(CASE WHEN r.instrument = 'rules_quiz' THEN r.item_value END) AS quiz_total
FROM survey_responses AS r
JOIN user_profiles AS p ON p.session_id = r.session_id
GROUP BY r.session_id, p.ab_group, p.age_group, p.cohort;