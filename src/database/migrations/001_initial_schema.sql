-- Initial Schema Migration
-- Creates basic database structure for PGLOK

-- Users table
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    email TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_login TIMESTAMP,
    settings TEXT,  -- JSON settings
    is_active INTEGER DEFAULT 1
);

-- Addons table
CREATE TABLE IF NOT EXISTS addons (
    addon_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    version TEXT NOT NULL,
    enabled INTEGER DEFAULT 1,
    config TEXT,  -- JSON config
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Settings table
CREATE TABLE IF NOT EXISTS settings (
    setting_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    addon_name TEXT,
    setting_key TEXT NOT NULL,
    setting_value TEXT,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id),
    UNIQUE(user_id, addon_name, setting_key)
);

-- Chat events table
CREATE TABLE IF NOT EXISTS chat_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    event_type TEXT NOT NULL,
    event_data TEXT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    processed INTEGER DEFAULT 0,
    instance_id TEXT,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

-- Migrations table
CREATE TABLE IF NOT EXISTS migrations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT UNIQUE NOT NULL,
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Insert default user
INSERT OR IGNORE INTO users (username, email) VALUES ('default_user', 'user@pglok.local');

-- Insert basic settings
INSERT OR IGNORE INTO settings (user_id, addon_name, setting_key, setting_value)
VALUES (1, 'pglok', 'theme', 'default');

INSERT OR IGNORE INTO settings (user_id, addon_name, setting_key, setting_value)
VALUES (1, 'pglok', 'chat_directory', '');
