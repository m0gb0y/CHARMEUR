CREATE TABLE IF NOT EXISTS partner_category_settings (
    category_id TEXT PRIMARY KEY,
    display_order INTEGER NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);
