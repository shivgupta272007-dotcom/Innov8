-- =============================================================
-- seed.sql  –  Demo data for "Goa Trip" group
-- Run AFTER schema.sql.
-- All amounts converted to paise (* 100).
-- =============================================================

PRAGMA foreign_keys = ON;

-- ── Group ─────────────────────────────────────────────────────
INSERT INTO groups (name, invite_code) VALUES ('Goa Trip', 'goa-trip');
-- groups.id = 1

-- ── Members (Shubh=1, Shiv=2, Shivansh=3, Shubham=4) ─────────
INSERT INTO members (group_id, name, upi_id) VALUES
    (1, 'Shubh',    'shubh@upi'),
    (1, 'Shiv',     'shiv@upi'),
    (1, 'Shivansh', 'shivansh@upi'),
    (1, 'Shubham',  'shubham@upi');

-- ── Expenses ──────────────────────────────────────────────────
-- Dinner ₹2400  paid by Shubh  (member_id = 1)
INSERT INTO expenses (group_id, title, amount_paise, payer_id, category)
    VALUES (1, 'Dinner', 240000, 1, 'Food');

-- Cab ₹860  paid by Shiv  (member_id = 2)
INSERT INTO expenses (group_id, title, amount_paise, payer_id, category)
    VALUES (1, 'Cab', 86000, 2, 'Transport');

-- Hotel ₹6000  paid by Shivansh  (member_id = 3)
INSERT INTO expenses (group_id, title, amount_paise, payer_id, category)
    VALUES (1, 'Hotel', 600000, 3, 'Stay');

-- Snacks ₹540  paid by Shubham  (member_id = 4)
INSERT INTO expenses (group_id, title, amount_paise, payer_id, category)
    VALUES (1, 'Snacks', 54000, 4, 'Food');

-- ── Splits (equal split, 4 members) ───────────────────────────
-- Dinner ₹2400 / 4 = ₹600 each = 60000 paise each  (exact)
INSERT INTO expense_splits (expense_id, member_id, share_paise) VALUES
    (1, 1, 60000), (1, 2, 60000), (1, 3, 60000), (1, 4, 60000);

-- Cab ₹860 / 4 = ₹215 each = 21500 paise each  (exact)
INSERT INTO expense_splits (expense_id, member_id, share_paise) VALUES
    (2, 1, 21500), (2, 2, 21500), (2, 3, 21500), (2, 4, 21500);

-- Hotel ₹6000 / 4 = ₹1500 each = 150000 paise each  (exact)
INSERT INTO expense_splits (expense_id, member_id, share_paise) VALUES
    (3, 1, 150000), (3, 2, 150000), (3, 3, 150000), (3, 4, 150000);

-- Snacks ₹540 / 4 = ₹135 each = 13500 paise each  (exact)
INSERT INTO expense_splits (expense_id, member_id, share_paise) VALUES
    (4, 1, 13500), (4, 2, 13500), (4, 3, 13500), (4, 4, 13500);

-- ── Seed chat messages ────────────────────────────────────────
INSERT INTO messages (group_id, sender, body) VALUES
    (1, 'Shubh',    'Hey everyone, let us track all Goa expenses here!'),
    (1, 'Shiv',     'Great idea! I already paid for the cab.'),
    (1, 'Shivansh', 'Hotel is done from my side.'),
    (1, 'Shubham',  'Added snacks. Let us settle at the end of the trip.');
