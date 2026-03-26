-- Farming Schema Migration
-- Creates tables for farming automation addon

-- Farming seeds configuration
CREATE TABLE IF NOT EXISTS farming_seeds (
    seed_id INTEGER PRIMARY KEY AUTOINCREMENT,
    seed_type TEXT UNIQUE NOT NULL,
    enabled INTEGER DEFAULT 0,
    water_time INTEGER DEFAULT 30,
    fertilize_time INTEGER DEFAULT 60,
    harvest_time INTEGER DEFAULT 120,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Farming inventory
CREATE TABLE IF NOT EXISTS farming_inventory (
    inventory_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    item_type TEXT NOT NULL,
    quantity INTEGER DEFAULT 0,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id),
    UNIQUE(user_id, item_type)
);

-- Farming plants
CREATE TABLE IF NOT EXISTS farming_plants (
    plant_id TEXT PRIMARY KEY,
    user_id INTEGER,
    plant_type TEXT NOT NULL,
    status TEXT DEFAULT 'planted',
    planted_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_watered TIMESTAMP,
    last_fertilized TIMESTAMP,
    next_action TEXT DEFAULT 'water',
    instance_id TEXT,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

-- Farming harvest statistics
CREATE TABLE IF NOT EXISTS farming_harvest_stats (
    stat_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    plant_type TEXT NOT NULL,
    total_harvested INTEGER DEFAULT 0,
    last_harvest TIMESTAMP,
    average_yield REAL DEFAULT 3.0,
    instance_id TEXT,
    FOREIGN KEY (user_id) REFERENCES users(user_id),
    UNIQUE(user_id, plant_type)
);

-- Insert default seeds
INSERT OR IGNORE INTO farming_seeds (seed_type, enabled, water_time, fertilize_time, harvest_time) VALUES
('carrot', 0, 30, 60, 120),
('wheat', 0, 25, 50, 100),
('tomato', 0, 35, 70, 140),
('potato', 0, 40, 80, 160),
('corn', 0, 45, 90, 180),
('strawberry', 0, 20, 40, 80),
('pumpkin', 0, 50, 100, 200),
('basil', 0, 15, 30, 60),
('thyme', 0, 15, 30, 60),
('parsley', 0, 15, 30, 60),
('sage', 0, 20, 40, 80),
('rosemary', 0, 20, 40, 80),
('sunflower', 0, 30, 60, 120),
('daisy', 0, 15, 30, 60),
('tulip', 0, 20, 40, 80),
('rose', 0, 25, 50, 100),
('orchid', 0, 35, 70, 140),
('apple', 0, 60, 120, 240),
('pear', 0, 60, 120, 240),
('cherry', 0, 60, 120, 240),
('peach', 0, 60, 120, 240),
('mushroom', 0, 25, 50, 100),
('cactus', 0, 40, 80, 160),
('bamboo', 0, 45, 90, 180),
('grape', 0, 30, 60, 120);

-- Insert default inventory items
INSERT OR IGNORE INTO farming_inventory (user_id, item_type, quantity) VALUES
(1, 'empty_bottles', 0),
(1, 'water', 0),
(1, 'fertilizer', 0);

-- Insert farming addon settings
INSERT OR IGNORE INTO settings (user_id, addon_name, setting_key, setting_value) VALUES
(1, 'farming_automation', 'auto_harvest', 'false'),
(1, 'farming_automation', 'auto_water', 'false'),
(1, 'farming_automation', 'auto_fertilize', 'false'),
(1, 'farming_automation', 'chat_monitoring', 'true'),
(1, 'farming_automation', 'action_delay', '1.0');
