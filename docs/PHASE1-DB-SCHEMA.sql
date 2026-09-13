-- Phase 1 数据库建表语句
-- 基于 PHASE1-ARCHITECTURE.md
-- 项目: AI Agent Platform

-- 启用 UUID 扩展
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================
-- 1. Agent 表
-- ============================================
CREATE TABLE agent (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(100) NOT NULL,
    description TEXT,
    status VARCHAR(20) NOT NULL DEFAULT 'stopped',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    is_deleted BOOLEAN NOT NULL DEFAULT FALSE
);

COMMENT ON TABLE agent IS 'AI Agent 主表';
COMMENT ON COLUMN agent.status IS 'running | stopped | error';

-- ============================================
-- 2. Persona 表
-- ============================================
CREATE TABLE persona (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(100) NOT NULL,
    description TEXT,
    personality JSONB NOT NULL DEFAULT '{}',
    version INTEGER NOT NULL DEFAULT 1,
    parent_id UUID REFERENCES persona(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    is_deleted BOOLEAN NOT NULL DEFAULT FALSE
);

COMMENT ON TABLE persona IS 'Persona 风格定义表';
COMMENT ON COLUMN persona.personality IS '{"tone":"professional","reply_length":"concise","proactiveness":"medium","style_boundaries":[]}';
COMMENT ON COLUMN persona.parent_id IS '父版本 ID，用于版本历史追溯';

-- ============================================
-- 3. Account 表
-- ============================================
CREATE TABLE account (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    platform_id VARCHAR(50) NOT NULL,
    name VARCHAR(100) NOT NULL,
    username VARCHAR(200),
    password_encrypted TEXT,
    status VARCHAR(20) NOT NULL DEFAULT 'disconnected',
    last_login TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    is_deleted BOOLEAN NOT NULL DEFAULT FALSE
);

COMMENT ON TABLE account IS '平台账号表';
COMMENT ON COLUMN account.status IS 'connected | disconnected | failed';

-- ============================================
-- 4. Platform 表
-- ============================================
CREATE TABLE platform (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    code VARCHAR(50) NOT NULL UNIQUE,
    name VARCHAR(100) NOT NULL,
    capabilities JSONB NOT NULL DEFAULT '[]',
    adapter_class VARCHAR(200),
    config JSONB DEFAULT '{}',
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    is_deleted BOOLEAN NOT NULL DEFAULT FALSE
);

COMMENT ON TABLE platform IS '平台注册表';
COMMENT ON COLUMN platform.code IS '平台唯一编码，如 wechat, douyin';
COMMENT ON COLUMN platform.capabilities IS '["messaging", "friend_management", "moment"]';
COMMENT ON COLUMN platform.adapter_class IS '适配器类路径，如 platforms.wechat.WeChatAdapter';

-- ============================================
-- 5. Browser Profile 表
-- ============================================
CREATE TABLE browser_profile (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    provider VARCHAR(50) NOT NULL DEFAULT 'bitbrowser',
    profile_id VARCHAR(100) NOT NULL,
    name VARCHAR(100),
    connection_status VARCHAR(20) NOT NULL DEFAULT 'disconnected',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    is_deleted BOOLEAN NOT NULL DEFAULT FALSE
);

COMMENT ON TABLE browser_profile IS '浏览器 Profile 表';
COMMENT ON COLUMN browser_profile.provider IS 'bitbrowser | adspower | local_chromium (V1仅bitbrowser)';

-- ============================================
-- 6. Proxy 表
-- ============================================
CREATE TABLE proxy (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(100) NOT NULL,
    type VARCHAR(10) NOT NULL,
    host VARCHAR(200) NOT NULL,
    port INTEGER NOT NULL,
    username VARCHAR(100),
    password_encrypted TEXT,
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    last_tested TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    is_deleted BOOLEAN NOT NULL DEFAULT FALSE
);

COMMENT ON TABLE proxy IS '代理服务器表';
COMMENT ON COLUMN proxy.type IS 'http | https | socks5';

-- ============================================
-- 7. Agent-Persona 绑定表
-- ============================================
CREATE TABLE agent_persona_binding (
    agent_id UUID NOT NULL REFERENCES agent(id) ON DELETE CASCADE,
    persona_id UUID NOT NULL REFERENCES persona(id) ON DELETE CASCADE,
    is_primary BOOLEAN NOT NULL DEFAULT FALSE,
    bound_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (agent_id, persona_id)
);

COMMENT ON TABLE agent_persona_binding IS 'Agent 与 Persona 的多对多绑定';

-- ============================================
-- 8. Account-Browser 绑定表
-- ============================================
CREATE TABLE account_browser_binding (
    account_id UUID NOT NULL REFERENCES account(id) ON DELETE CASCADE,
    profile_id UUID NOT NULL REFERENCES browser_profile(id) ON DELETE CASCADE,
    bound_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (account_id, profile_id)
);

COMMENT ON TABLE account_browser_binding IS '账号与浏览器 Profile 的绑定';

-- ============================================
-- 9. Account-Proxy 绑定表
-- ============================================
CREATE TABLE account_proxy_binding (
    account_id UUID NOT NULL REFERENCES account(id) ON DELETE CASCADE,
    proxy_id UUID NOT NULL REFERENCES proxy(id) ON DELETE CASCADE,
    bound_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (account_id, proxy_id)
);

COMMENT ON TABLE account_proxy_binding IS '账号与代理的绑定';

-- ============================================
-- 索引
-- ============================================
CREATE INDEX idx_agent_status ON agent(status) WHERE is_deleted = FALSE;
CREATE INDEX idx_agent_name ON agent(name) WHERE is_deleted = FALSE;
CREATE INDEX idx_persona_version ON persona(parent_id, version) WHERE is_deleted = FALSE;
CREATE INDEX idx_account_platform ON account(platform_id) WHERE is_deleted = FALSE;
CREATE INDEX idx_account_status ON account(status) WHERE is_deleted = FALSE;
CREATE INDEX idx_browser_profile_provider ON browser_profile(provider) WHERE is_deleted = FALSE;
CREATE INDEX idx_proxy_status ON proxy(status) WHERE is_deleted = FALSE;

-- ============================================
-- 触发器：自动更新 updated_at
-- ============================================
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_agent_updated_at BEFORE UPDATE ON agent
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_persona_updated_at BEFORE UPDATE ON persona
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_account_updated_at BEFORE UPDATE ON account
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_browser_profile_updated_at BEFORE UPDATE ON browser_profile
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_proxy_updated_at BEFORE UPDATE ON proxy
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================
-- 初始数据：内置平台
-- ============================================
INSERT INTO platform (code, name, capabilities, adapter_class) VALUES
    ('wechat', '微信', '["messaging","friend_management","moment","group"]', 'platforms.wechat.WeChatAdapter'),
    ('douyin', '抖音', '["messaging","comment_reply"]', 'platforms.douyin.DouyinAdapter'),
    ('xiaohongshu', '小红书', '["messaging","comment_reply"]', 'platforms.xiaohongshu.XiaoHongShuAdapter');
