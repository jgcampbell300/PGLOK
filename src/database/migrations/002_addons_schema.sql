-- Addons Schema Migration
-- Extends database for addon management

-- No new tables needed for basic addon management
-- This migration exists for future addon-specific features

-- Add addon-specific settings
INSERT OR IGNORE INTO settings (user_id, addon_name, setting_key, setting_value)
VALUES (1, 'addon_manager', 'auto_load', 'true');

INSERT OR IGNORE INTO settings (user_id, addon_name, setting_key, setting_value)
VALUES (1, 'addon_manager', 'load_order', '[]');
