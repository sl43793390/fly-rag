-- ============================================================
-- 知识库 RAG 平台 MySQL 初始化脚本
-- 用法: mysql -uroot -p < sql/init.sql
-- 库名 / 账号可用环境变量覆盖(见 api/api_config.py):
--   MYSQL_HOST / MYSQL_PORT / MYSQL_USER / MYSQL_PASSWORD / MYSQL_DB
-- ============================================================

CREATE DATABASE IF NOT EXISTS kb_rag
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_unicode_ci;

USE kb_rag;

-- ------------------------------------------------------------
-- 知识库:每个知识库对应一个 Milvus collection(kb_{id})
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS knowledge_base (
  id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  name            VARCHAR(128)  NOT NULL COMMENT '知识库名称',
  description     VARCHAR(512)  NOT NULL DEFAULT '' COMMENT '描述',
  collection_name VARCHAR(128)  NOT NULL COMMENT 'Milvus collection 名(kb_{id})',
  splitter        VARCHAR(32)   NOT NULL DEFAULT 'auto'
                  COMMENT '切分器: auto/sentence/text/token/simple/markdown/html/json',
  chunk_size      INT           NOT NULL DEFAULT 1024 COMMENT '切块大小',
  chunk_overlap   INT           NOT NULL DEFAULT 200 COMMENT '相邻块重叠',
  created_at      DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  updated_at      DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP
                                ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  UNIQUE KEY uk_name (name)
) ENGINE = InnoDB COMMENT = '知识库';

-- ------------------------------------------------------------
-- 知识库文档:上传记录 + 解析状态机
--   status: pending -> processing -> done / failed
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS kb_document (
  id            BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  kb_id         BIGINT UNSIGNED NOT NULL COMMENT '所属知识库',
  file_name     VARCHAR(255) NOT NULL COMMENT '原始文件名',
  file_path     VARCHAR(512) NOT NULL COMMENT '服务器落盘路径',
  file_ext      VARCHAR(16)  NOT NULL DEFAULT '' COMMENT '小写后缀',
  file_size     BIGINT       NOT NULL DEFAULT 0 COMMENT '文件大小(字节)',
  status        VARCHAR(16)  NOT NULL DEFAULT 'pending'
                COMMENT '状态: pending/processing/done/failed',
  node_count    INT          NOT NULL DEFAULT 0 COMMENT '切分出的向量节点数',
  error_msg     VARCHAR(1024) NOT NULL DEFAULT '' COMMENT '失败原因',
  splitter      VARCHAR(32)  NOT NULL DEFAULT 'auto' COMMENT '实际使用的切分器',
  chunk_size    INT          NOT NULL DEFAULT 1024,
  chunk_overlap INT          NOT NULL DEFAULT 200,
  created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
                              ON UPDATE CURRENT_TIMESTAMP,
  KEY idx_kb_id (kb_id),
  KEY idx_status (status),
  CONSTRAINT fk_document_kb FOREIGN KEY (kb_id)
    REFERENCES knowledge_base (id) ON DELETE CASCADE
) ENGINE = InnoDB COMMENT = '知识库文档';

-- ------------------------------------------------------------
-- 对话会话:归属于某个知识库(可空,支持纯 LLM 对话)
--   kb_id 可空:空表示不挂知识库,直接与大模型对话
--   owner_id 可空:未登录用户共享匿名会话池
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS chat_session (
  id         BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  kb_id      BIGINT UNSIGNED NULL COMMENT '关联知识库(可空,纯 LLM 对话)',
  owner_id   BIGINT UNSIGNED NULL COMMENT '会话所有者(用户 id,可空为匿名会话)',
  title      VARCHAR(255) NOT NULL DEFAULT '新会话' COMMENT '会话标题',
  mode       VARCHAR(16)  NOT NULL DEFAULT 'rag'
             COMMENT '会话模式: rag(知识库对话) / chat(纯 LLM 对话)',
  created_at DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
                          ON UPDATE CURRENT_TIMESTAMP,
  KEY idx_kb_id (kb_id),
  KEY idx_owner_id (owner_id),
  KEY idx_mode (mode),
  CONSTRAINT fk_session_kb FOREIGN KEY (kb_id)
    REFERENCES knowledge_base (id) ON DELETE CASCADE
) ENGINE = InnoDB COMMENT = '对话会话';

-- ------------------------------------------------------------
-- 对话消息:user / assistant,assistant 可携带 RAG 引用来源
--   is_summary=1 表示该条消息是历史压缩生成的摘要(占位消息)
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS chat_message (
  id          BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  session_id  BIGINT UNSIGNED NOT NULL COMMENT '所属会话',
  role        VARCHAR(16) NOT NULL COMMENT '角色: user/assistant',
  content     MEDIUMTEXT  COMMENT '消息内容',
  sources     JSON        NULL COMMENT 'RAG 引用来源 [{text,score,file_name}]',
  is_summary  TINYINT(1)  NOT NULL DEFAULT 0 COMMENT '是否为压缩摘要消息',
  created_at  DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_session_id (session_id),
  CONSTRAINT fk_message_session FOREIGN KEY (session_id)
    REFERENCES chat_session (id) ON DELETE CASCADE
) ENGINE = InnoDB COMMENT = '对话消息';

-- ============================================================
-- 用户 / 角色 / 权限(RBAC)
-- ============================================================

-- ------------------------------------------------------------
-- 用户
--   password_hash: pbkdf2_hmac(sha256) 摘要,格式 "pbkdf2_sha256$iter$salt$b64hash"
--   status: active / disabled
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `user` (
  id            BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  username      VARCHAR(64)  NOT NULL COMMENT '登录名',
  password_hash VARCHAR(255) NOT NULL COMMENT '密码哈希',
  email         VARCHAR(128) NOT NULL DEFAULT '' COMMENT '邮箱',
  status        VARCHAR(16)  NOT NULL DEFAULT 'active'
                COMMENT '状态: active/disabled',
  remark        VARCHAR(255) NOT NULL DEFAULT '' COMMENT '备注',
  last_login_at DATETIME     NULL COMMENT '最近登录时间',
  created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
                              ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uk_username (username)
) ENGINE = InnoDB COMMENT = '用户';

-- ------------------------------------------------------------
-- 角色
--   code: 唯一编码,如 admin / kb_manager / chat_user
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `role` (
  id          BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  name        VARCHAR(64)  NOT NULL COMMENT '角色名称',
  code        VARCHAR(64)  NOT NULL COMMENT '角色编码',
  description VARCHAR(255) NOT NULL DEFAULT '' COMMENT '描述',
  created_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
                            ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uk_code (code)
) ENGINE = InnoDB COMMENT = '角色';

-- ------------------------------------------------------------
-- 权限
--   code: 形如 user:read / kb:create,后端做 has_permission 校验
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `permission` (
  id          BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  name        VARCHAR(64)  NOT NULL COMMENT '权限名称',
  code        VARCHAR(128) NOT NULL COMMENT '权限编码',
  description VARCHAR(255) NOT NULL DEFAULT '' COMMENT '描述',
  created_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uk_code (code)
) ENGINE = InnoDB COMMENT = '权限';

-- ------------------------------------------------------------
-- 用户-角色关联(多对多)
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `user_role` (
  user_id BIGINT UNSIGNED NOT NULL,
  role_id BIGINT UNSIGNED NOT NULL,
  PRIMARY KEY (user_id, role_id),
  CONSTRAINT fk_ur_user FOREIGN KEY (user_id)
    REFERENCES `user` (id) ON DELETE CASCADE,
  CONSTRAINT fk_ur_role FOREIGN KEY (role_id)
    REFERENCES `role` (id) ON DELETE CASCADE
) ENGINE = InnoDB COMMENT = '用户-角色';

-- ------------------------------------------------------------
-- 角色-权限关联(多对多)
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `role_permission` (
  role_id       BIGINT UNSIGNED NOT NULL,
  permission_id BIGINT UNSIGNED NOT NULL,
  PRIMARY KEY (role_id, permission_id),
  CONSTRAINT fk_rp_role FOREIGN KEY (role_id)
    REFERENCES `role` (id) ON DELETE CASCADE,
  CONSTRAINT fk_rp_perm FOREIGN KEY (permission_id)
    REFERENCES `permission` (id) ON DELETE CASCADE
) ENGINE = InnoDB COMMENT = '角色-权限';

-- ============================================================
-- 初始数据:内置角色 / 权限 / 超级管理员
-- ============================================================

-- 角色
INSERT INTO `role` (name, code, description)
VALUES
  ('超级管理员', 'admin',  '拥有全部权限'),
  ('知识库管理员', 'kb_manager', '知识库/文档管理权限'),
  ('对话用户', 'chat_user', '可使用 RAG 与纯 LLM 对话')
ON DUPLICATE KEY UPDATE name = VALUES(name);

-- 权限
INSERT INTO `permission` (name, code, description)
VALUES
  ('用户查看', 'user:read',   '查看用户列表'),
  ('用户创建', 'user:create', '创建用户'),
  ('用户更新', 'user:update', '更新用户/分配角色'),
  ('用户删除', 'user:delete', '删除用户'),
  ('角色查看', 'role:read',   '查看角色列表'),
  ('角色创建', 'role:create', '创建角色'),
  ('角色更新', 'role:update', '更新角色/分配权限'),
  ('角色删除', 'role:delete', '删除角色'),
  ('权限查看', 'perm:read',   '查看权限列表'),
  ('知识库创建', 'kb:create', '创建知识库'),
  ('知识库删除', 'kb:delete', '删除知识库')
ON DUPLICATE KEY UPDATE name = VALUES(name);

-- admin 角色拥有全部权限
INSERT INTO `role_permission` (role_id, permission_id)
SELECT r.id, p.id FROM `role` r, `permission` p
WHERE r.code = 'admin'
ON DUPLICATE KEY UPDATE role_id = role_id;

-- kb_manager 拥有 role:read / perm:read / kb:create / kb:delete
INSERT INTO `role_permission` (role_id, permission_id)
SELECT r.id, p.id FROM `role` r, `permission` p
WHERE r.code = 'kb_manager' AND p.code IN ('role:read', 'perm:read', 'kb:create', 'kb:delete')
ON DUPLICATE KEY UPDATE role_id = role_id;

-- chat_user 无管理类权限,仅聊天
-- -------------------------------------------------------
-- 超级管理员账号由后端首次启动时自动创建(见 api.user.services.ensure_default_admin),
-- 默认账号: admin / admin123,登录后请立即修改密码。
-- 如需在 SQL 层手动初始化,可使用如下语句(密码 admin123 的有效哈希):
--   INSERT INTO `user` (username, password_hash, email, status, remark)
--   VALUES ('admin', '<pbkdf2_sha256$...>', '', 'active', '内置超级管理员');
--   INSERT INTO `user_role` (user_id, role_id)
--   SELECT u.id, r.id FROM `user` u, `role` r
--   WHERE u.username = 'admin' AND r.code = 'admin';
-- 这里不在脚本中硬编码假哈希,避免无法登录。
-- -------------------------------------------------------

-- ============================================================
-- 老库增量升级:补齐 chat_session / chat_message 缺失字段、把 kb_id 改为可空
--   说明:CREATE TABLE IF NOT EXISTS 不会修改已存在的表。
--   后端启动时也会自动执行等价 ALTER(见 api.database.ensure_schema_upgrades),
--   本段仅作手动运维兜底;重复执行已存在字段会报错,可忽略。
-- ============================================================
-- chat_session 增加 owner_id / mode(老库没有这两列)
--   ALTER TABLE chat_session ADD COLUMN owner_id BIGINT NULL COMMENT '会话所有者(用户 id,可空为匿名会话)';
--   ALTER TABLE chat_session ADD COLUMN mode VARCHAR(16) NOT NULL DEFAULT 'rag' COMMENT '会话模式: rag/chat';
--   CREATE INDEX idx_chat_session_owner ON chat_session(owner_id);
--   CREATE INDEX idx_chat_session_mode  ON chat_session(mode);
-- chat_session.kb_id 改为可空(支持纯 LLM 对话,外键约束本身允许 NULL)
--   ALTER TABLE chat_session MODIFY COLUMN kb_id BIGINT NULL;
-- chat_message 增加 is_summary
--   ALTER TABLE chat_message ADD COLUMN is_summary TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否为压缩摘要消息';
