-- 首次启动时 postgres 会自动执行本文件（docker-entrypoint-initdb.d）
-- 注意：只在数据卷为空时执行一次。改了这里要 `docker compose down -v` 才会重跑。
--
-- ⚠️ 依赖 pgvector/pgvector:pg16 镜像，官方 postgres 镜像里没有 vector 扩展

-- pgvector：让 postgres 兼任向量库（另一个选择是 compose 里那个 qdrant）
-- 必须放在最前面：CREATE EXTENSION 失败会让整个脚本中止，
-- 后面建表的语句一条都不会执行（这个坑真的踩过，见 §41.7）
CREATE EXTENSION IF NOT EXISTS vector;

CREATE DATABASE langfuse;

CREATE TABLE IF NOT EXISTS documents (
    id          BIGSERIAL PRIMARY KEY,
    tenant      TEXT        NOT NULL,
    source      TEXT        NOT NULL,
    version     INTEGER     NOT NULL DEFAULT 1,
    content     TEXT        NOT NULL,
    -- 1536 维是 OpenAI text-embedding-3-small 的默认维度；换模型要改这里
    embedding   vector(1536),
    indexed_at  TIMESTAMPTZ,
    deleted_at  TIMESTAMPTZ,
    UNIQUE (tenant, source, version)
);

-- 多租户隔离靠这个索引 + 查询里**永远带 tenant 条件**（见第 39 章）
CREATE INDEX IF NOT EXISTS idx_documents_tenant ON documents (tenant) WHERE deleted_at IS NULL;

CREATE TABLE IF NOT EXISTS chat_sessions (
    id          TEXT PRIMARY KEY,
    tenant      TEXT NOT NULL,
    user_id     TEXT NOT NULL,
    -- 每个检查点是一份完整快照，所以要有上限策略（见第 23 章）
    state       JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS jobs (
    id          TEXT PRIMARY KEY,
    tenant      TEXT NOT NULL,
    -- 幂等键由客户端提供（见 §41.4）
    idem_key    TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'queued',
    result      JSONB,
    attempts    INTEGER NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    UNIQUE (tenant, idem_key)
);
