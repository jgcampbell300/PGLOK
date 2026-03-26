-- LokFarmer Addon Database Schema
-- Extends the unified PGLOK database with farming-specific tables

-- LokFarmer addon settings
CREATE TABLE IF NOT EXISTS lokfarmer_settings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    setting_key TEXT NOT NULL,
    setting_value TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id),
    UNIQUE(user_id, setting_key)
);

-- Growable items database
CREATE TABLE IF NOT EXISTS growable_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_name TEXT NOT NULL UNIQUE,
    seed_name TEXT,
    growth_time INTEGER NOT NULL, -- in minutes
    base_yield INTEGER DEFAULT 1,
    bonus_yield INTEGER DEFAULT 0,
    water_per_cycle INTEGER DEFAULT 1,
    fertilizer_per_cycle INTEGER DEFAULT 0,
    music_bonus BOOLEAN DEFAULT FALSE,
    stack_size INTEGER DEFAULT 1,
    item_type TEXT DEFAULT 'plant',
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Item stack sizes
CREATE TABLE IF NOT EXISTS item_stack_sizes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_name TEXT NOT NULL UNIQUE,
    stack_size INTEGER NOT NULL DEFAULT 1,
    item_type TEXT,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Farming recipes
CREATE TABLE IF NOT EXISTS farming_recipes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recipe_name TEXT NOT NULL,
    result_item TEXT NOT NULL,
    result_count INTEGER DEFAULT 1,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Recipe ingredients
CREATE TABLE IF NOT EXISTS recipe_ingredients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recipe_id INTEGER NOT NULL,
    ingredient_item TEXT NOT NULL,
    ingredient_count INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (recipe_id) REFERENCES farming_recipes(id) ON DELETE CASCADE
);

-- Planting cycles tracking
CREATE TABLE IF NOT EXISTS planting_cycles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    plant_name TEXT NOT NULL,
    planted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expected_harvest TIMESTAMP,
    actual_harvest TIMESTAMP,
    yield_count INTEGER DEFAULT 0,
    bonus_yield INTEGER DEFAULT 0,
    water_used INTEGER DEFAULT 0,
    fertilizer_used INTEGER DEFAULT 0,
    music_bonus BOOLEAN DEFAULT FALSE,
    status TEXT DEFAULT 'planted', -- planted, growing, harvested, failed
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

-- Inventory snapshots
CREATE TABLE IF NOT EXISTS inventory_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    snapshot_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    total_items INTEGER DEFAULT 0,
    free_slots INTEGER DEFAULT 0,
    water_count INTEGER DEFAULT 0,
    fertilizer_count INTEGER DEFAULT 0,
    empty_bottles_count INTEGER DEFAULT 0,
    seeds_count INTEGER DEFAULT 0,
    json_data TEXT, -- Full inventory JSON
    FOREIGN KEY (user_id) REFERENCES users(id)
);

-- Chat logs tracking
CREATE TABLE IF NOT EXISTS chat_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    message_type TEXT,
    message_text TEXT NOT NULL,
    raw_message TEXT,
    processed BOOLEAN DEFAULT FALSE,
    category TEXT, -- harvest, growth, error, other
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

-- Automation statistics
CREATE TABLE IF NOT EXISTS automation_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    stat_date DATE NOT NULL,
    total_cycles INTEGER DEFAULT 0,
    successful_harvests INTEGER DEFAULT 0,
    failed_cycles INTEGER DEFAULT 0,
    total_yield INTEGER DEFAULT 0,
    water_used INTEGER DEFAULT 0,
    fertilizer_used INTEGER DEFAULT 0,
    music_plays INTEGER DEFAULT 0,
    inventory_sorts INTEGER DEFAULT 0,
    stack_optimizations INTEGER DEFAULT 0,
    uptime_minutes INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id),
    UNIQUE(user_id, stat_date)
);

-- Shortcut bar configurations
CREATE TABLE IF NOT EXISTS shortcut_configs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    slot_number INTEGER NOT NULL CHECK (slot_number BETWEEN 1 AND 12),
    action_type TEXT NOT NULL, -- music_instrument, use_item, select_next, etc.
    item_name TEXT,
    key_binding TEXT,
    enabled BOOLEAN DEFAULT TRUE,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id),
    UNIQUE(user_id, slot_number)
);

-- Alerts and notifications
CREATE TABLE IF NOT EXISTS farming_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    alert_type TEXT NOT NULL, -- low_resources, inventory_full, error, etc.
    alert_message TEXT NOT NULL,
    alert_level TEXT DEFAULT 'info', -- info, warning, error
    acknowledged BOOLEAN DEFAULT FALSE,
    acknowledged_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

-- Insert default growable items
INSERT OR IGNORE INTO growable_items (item_name, seed_name, growth_time, base_yield, bonus_yield, water_per_cycle, fertilizer_per_cycle, music_bonus, stack_size, item_type, description) VALUES
('Cotton', 'Cotton Seed', 30, 5, 2, 1, 0, TRUE, 50, 'plant', 'Cotton for crafting cloth'),
('Flax', 'Flax Seed', 25, 2, 1, 1, 0, TRUE, 50, 'plant', 'Flax for crafting linen'),
('Wheat', 'Wheat Seed', 20, 3, 1, 1, 0, TRUE, 50, 'plant', 'Wheat for baking and crafting'),
('Carrot', 'Carrot Seed', 15, 2, 1, 1, 0, FALSE, 20, 'plant', 'Carrots for cooking'),
('Potato', 'Potato Seed', 18, 3, 1, 1, 0, FALSE, 20, 'plant', 'Potatoes for cooking'),
('Tomato', 'Tomato Seed', 22, 4, 2, 1, 0, TRUE, 30, 'plant', 'Tomatoes for cooking'),
('Corn', 'Corn Seed', 35, 6, 3, 2, 1, TRUE, 40, 'plant', 'Corn for food and crafting'),
('Pumpkin', 'Pumpkin Seed', 40, 4, 2, 2, 1, FALSE, 10, 'plant', 'Pumpkins for Halloween and food'),
('Strawberry', 'Strawberry Seed', 12, 3, 2, 1, 0, TRUE, 25, 'plant', 'Strawberries for desserts'),
('Grapes', 'Grape Seed', 28, 8, 4, 2, 1, TRUE, 30, 'plant', 'Grapes for wine and food');

-- Insert default stack sizes
INSERT OR IGNORE INTO item_stack_sizes (item_name, stack_size, item_type, notes) VALUES
('Water', 5, 'liquid', 'Filled water bottles stack to 5'),
('Fertilizer', 5, 'material', 'Filled fertilizer bottles stack to 5'),
('Empty Bottle', 10, 'container', 'Empty bottles stack to 10'),
('Cotton', 50, 'plant', 'Cotton fibers'),
('Flax', 50, 'plant', 'Flax fibers'),
('Wheat', 50, 'plant', 'Wheat grains'),
('Carrot', 20, 'food', 'Carrots'),
('Potato', 20, 'food', 'Potatoes'),
('Tomato', 30, 'food', 'Tomatoes'),
('Corn', 40, 'food', 'Corn cobs'),
('Pumpkin', 10, 'food', 'Pumpkins'),
('Strawberry', 25, 'food', 'Strawberries'),
('Grapes', 30, 'food', 'Grapes'),
('Cotton Seed', 50, 'seed', 'Cotton seeds'),
('Flax Seed', 50, 'seed', 'Flax seeds'),
('Wheat Seed', 50, 'seed', 'Wheat seeds'),
('Carrot Seed', 50, 'seed', 'Carrot seeds'),
('Potato Seed', 50, 'seed', 'Potato seeds'),
('Tomato Seed', 50, 'seed', 'Tomato seeds'),
('Corn Seed', 50, 'seed', 'Corn seeds'),
('Pumpkin Seed', 50, 'seed', 'Pumpkin seeds'),
('Strawberry Seed', 50, 'seed', 'Strawberry seeds'),
('Grape Seed', 50, 'seed', 'Grape seeds');

-- Insert default farming recipes
INSERT OR IGNORE INTO farming_recipes (recipe_name, result_item, result_count, description) VALUES
('Basic Fertilizer', 'Fertilizer', 1, 'Basic fertilizer from water and bottles'),
('Enhanced Fertilizer', 'Enhanced Fertilizer', 1, 'Enhanced fertilizer with bonus effects'),
('Growth Potion', 'Growth Potion', 1, 'Potion that accelerates plant growth'),
('Music Charm', 'Music Charm', 1, 'Charm that increases music bonus effects');

-- Insert recipe ingredients
INSERT OR IGNORE INTO recipe_ingredients (recipe_id, ingredient_item, ingredient_count) VALUES
(1, 'Water', 1),
(1, 'Empty Bottle', 1),
(2, 'Fertilizer', 1),
(2, 'Special Herb', 1),
(3, 'Water', 2),
(3, 'Magic Dust', 1),
(3, 'Empty Bottle', 1),
(4, 'Wood', 2),
(4, 'String', 1);

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_lokfarmer_settings_user_key ON lokfarmer_settings(user_id, setting_key);
CREATE INDEX IF NOT EXISTS idx_planting_cycles_user ON planting_cycles(user_id);
CREATE INDEX IF NOT EXISTS idx_planting_cycles_status ON planting_cycles(status);
CREATE INDEX IF NOT EXISTS idx_inventory_snapshots_user_time ON inventory_snapshots(user_id, snapshot_time);
CREATE INDEX IF NOT EXISTS idx_chat_logs_user_time ON chat_logs(user_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_automation_stats_user_date ON automation_stats(user_id, stat_date);
CREATE INDEX IF NOT EXISTS idx_farming_alerts_user_type ON farming_alerts(user_id, alert_type);

-- Create triggers for automatic timestamp updates
CREATE TRIGGER IF NOT EXISTS update_lokfarmer_settings_timestamp 
    AFTER UPDATE ON lokfarmer_settings
    FOR EACH ROW
BEGIN
    UPDATE lokfarmer_settings SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;

CREATE TRIGGER IF NOT EXISTS update_growable_items_timestamp 
    AFTER UPDATE ON growable_items
    FOR EACH ROW
BEGIN
    UPDATE growable_items SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;

CREATE TRIGGER IF NOT EXISTS update_item_stack_sizes_timestamp 
    AFTER UPDATE ON item_stack_sizes
    FOR EACH ROW
BEGIN
    UPDATE item_stack_sizes SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;

CREATE TRIGGER IF NOT EXISTS update_farming_recipes_timestamp 
    AFTER UPDATE ON farming_recipes
    FOR EACH ROW
BEGIN
    UPDATE farming_recipes SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;

CREATE TRIGGER IF NOT EXISTS update_automation_stats_timestamp 
    AFTER UPDATE ON automation_stats
    FOR EACH ROW
BEGIN
    UPDATE automation_stats SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;

CREATE TRIGGER IF NOT EXISTS update_shortcut_configs_timestamp 
    AFTER UPDATE ON shortcut_configs
    FOR EACH ROW
BEGIN
    UPDATE shortcut_configs SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;
