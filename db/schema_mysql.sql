-- 问答沉淀：MySQL 表结构（生产）
-- 本地开发用 tools/qa_store.py 的 SQLite 镜像，字段一致，导出语句见 `qa_store.py export-sql`。
-- 字符集必须 utf8mb4：分析师会输入 emoji 和生僻字，utf8mb3 会静默截断。

CREATE DATABASE IF NOT EXISTS dw_qa
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_0900_ai_ci;

USE dw_qa;

-- 一个会话 = 一个分析师的一次连续使用（含所有追问）
CREATE TABLE IF NOT EXISTS qa_session (
  session_id    VARCHAR(64)  NOT NULL COMMENT '会话 id',
  started_at    DATETIME     NOT NULL COMMENT '首次提问时间',
  user_hash     CHAR(32)     NULL     COMMENT '提问者哈希，不存真名',
  channel       VARCHAR(32)  NULL     COMMENT '入口：dsh / web / api',
  turn_cnt      INT          NOT NULL DEFAULT 0 COMMENT '轮数，由 qa_turn 汇总',
  PRIMARY KEY (session_id),
  KEY idx_started (started_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='问答会话';

-- 一轮 = 一问一答（追问是同一会话里的下一轮）
CREATE TABLE IF NOT EXISTS qa_turn (
  qa_id          VARCHAR(32)  NOT NULL COMMENT 'Q+日期+序号',
  session_id     VARCHAR(64)  NOT NULL COMMENT '所属会话',
  turn_no        INT          NOT NULL COMMENT '第几轮，从 1 开始',
  asked_at       DATETIME     NOT NULL COMMENT '提问时间',
  question       MEDIUMTEXT   NOT NULL COMMENT '分析师原话，不许改写',
  answer         MEDIUMTEXT   NOT NULL COMMENT '系统回答',
  sql_text       MEDIUMTEXT   NULL     COMMENT '给出的 SQL（有就存）',
  sql_hash       CHAR(64)     NULL     COMMENT 'SQL 指纹，去重与复用统计',
  intent         VARCHAR(16)  NULL     COMMENT '取数/分析/口径确认/排障/其他',
  tables_json    JSON         NULL     COMMENT '涉及的物理表',
  entities_json  JSON         NULL     COMMENT '涉及的本体 id',
  feedback       TINYINT      NOT NULL DEFAULT 0 COMMENT '1 有用 / -1 无用 / 0 未评',
  feedback_note  VARCHAR(255) NULL     COMMENT '一句话理由',
  model          VARCHAR(64)  NULL     COMMENT '作答模型',
  latency_ms     INT          NULL     COMMENT '耗时，用于发现慢问题',
  ingested_at    DATETIME     NOT NULL COMMENT '入库时间',
  PRIMARY KEY (qa_id),
  KEY idx_session (session_id, turn_no),
  KEY idx_asked (asked_at),
  KEY idx_feedback (feedback)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='问答轮次（知识库的主要原料）';

-- 从问答里挖出来的候选知识，人审通过才进 knowledge/ 或转 ontology_delta
CREATE TABLE IF NOT EXISTS qa_candidate (
  candidate_id   VARCHAR(32)  NOT NULL COMMENT 'C+日期+序号',
  kind           VARCHAR(16)  NOT NULL COMMENT 'correction/faq/term/join',
  title          VARCHAR(255) NOT NULL,
  evidence_json  JSON         NOT NULL COMMENT '证据：qa_id 列表 + 摘录',
  hit_count      INT          NOT NULL DEFAULT 1 COMMENT '命中次数',
  status         VARCHAR(16)  NOT NULL DEFAULT 'pending' COMMENT 'pending/promoted/rejected',
  promoted_path  VARCHAR(255) NULL     COMMENT '转正后的文件路径',
  created_at     DATETIME     NOT NULL,
  decided_at     DATETIME     NULL,
  PRIMARY KEY (candidate_id),
  KEY idx_status (status, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='候选知识（自动挖掘 + 人工裁决）';

-- 分析师最常问的表组合：用来反推该补哪条取数路径
CREATE OR REPLACE VIEW v_table_pair AS
SELECT tables_json, COUNT(*) AS cnt
FROM qa_turn
WHERE tables_json IS NOT NULL
GROUP BY tables_json
ORDER BY cnt DESC;
