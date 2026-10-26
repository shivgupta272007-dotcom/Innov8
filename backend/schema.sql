-- =============================================================
-- schema.sql  –  Innov8 Smart Expense Manager
-- Run once to create the database structure.
-- All money is stored as INTEGER paise (1 rupee = 100 paise)
-- so we never lose precision with floating-point arithmetic.
-- =============================================================

PRAGMA foreign_keys = ON;   -- enforce FK rules in SQLite

-- ─────────────────────────────────────────
-- TABLE: groups
-- One row per expense-sharing group.
-- ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS groups (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL CHECK(length(trim(name)) > 0),
    invite_code TEXT,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_groups_invite_code ON groups(invite_code);

-- ─────────────────────────────────────────
-- TABLE: members
-- People inside a group.  No login needed –
-- just a display name linked to a group.
-- ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS members (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id   INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    name       TEXT    NOT NULL CHECK(length(trim(name)) > 0),
    upi_id     TEXT,           -- optional UPI id for settlement QR
    created_at TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_members_group ON members(group_id);

-- ─────────────────────────────────────────
-- TABLE: expenses
-- A single expense paid by one member.
-- amount_paise must be positive.
-- ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS expenses (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id     INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    title        TEXT    NOT NULL CHECK(length(trim(title)) > 0),
    amount_paise INTEGER NOT NULL CHECK(amount_paise > 0),
    payer_id     INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    category     TEXT    NOT NULL DEFAULT 'General',
    created_at   TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_expenses_group ON expenses(group_id);

-- ─────────────────────────────────────────
-- TABLE: expense_splits
-- How much each member owes for one expense.
-- share_paise >= 0 (a member may owe 0 if
-- excluded from an expense).
-- All rows for an expense_id must sum exactly
-- to expenses.amount_paise (enforced in Python).
-- ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS expense_splits (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    expense_id  INTEGER NOT NULL REFERENCES expenses(id) ON DELETE CASCADE,
    member_id   INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    share_paise INTEGER NOT NULL CHECK(share_paise >= 0),
    UNIQUE(expense_id, member_id)   -- one row per member per expense
);

CREATE INDEX IF NOT EXISTS idx_splits_expense ON expense_splits(expense_id);

-- ─────────────────────────────────────────
-- TABLE: messages
-- Simple group chat.  No authentication.
-- ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id   INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    sender     TEXT    NOT NULL CHECK(length(trim(sender)) > 0),
    body       TEXT    NOT NULL CHECK(length(trim(body)) > 0),
    created_at TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_messages_group ON messages(group_id);

-- ─────────────────────────────────────────
-- TABLE: settlements
-- Minimum-transfer plan produced by the C++
-- greedy algorithm.  status: 'pending'|'done'
-- ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS settlements (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id      INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    from_member   INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    to_member     INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    amount_paise  INTEGER NOT NULL CHECK(amount_paise > 0),
    status        TEXT    NOT NULL DEFAULT 'pending'
                          CHECK(status IN ('pending','done')),
    created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_settlements_group ON settlements(group_id);
