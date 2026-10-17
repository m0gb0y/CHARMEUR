ALTER TABLE partner_listings
    ADD COLUMN IF NOT EXISTS point_courses TEXT NOT NULL DEFAULT '';

CREATE TABLE IF NOT EXISTS partner_categories (
    id TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    display_order INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS partner_categories_label_ci_unique
    ON partner_categories (LOWER(label));
