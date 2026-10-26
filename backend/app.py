"""
app.py  –  Innov8 Flask REST API
==================================
This is the heart of the backend.  Every URL the frontend calls is
defined here as a Python function decorated with @app.route().

HOW FLASK WORKS (for viva):
  - Flask maps URL paths to Python functions (called "views").
  - @app.route("/api/groups", methods=["GET","POST"]) means:
      GET  /api/groups  → list groups
      POST /api/groups  → create a group
  - request.get_json() reads the JSON body the frontend sends.
  - jsonify(...)       converts a Python dict/list to a JSON response.
  - We return (data, status_code) tuples, e.g. (json, 201) for "Created".

ERROR CONVENTION:
  Every error response looks like:  {"error": "human-readable message"}
  Every success response contains the actual data.

MONEY:
  All amounts travel over the API in PAISE (integer).
  The frontend divides by 100 to display rupees.
"""

import csv
import io
import math
import os
from flask import Flask, request, jsonify, make_response, send_from_directory
from flask_cors import CORS
from db import get_db, init_db
from settlements import compute_settlements

# ── App setup ──────────────────────────────────────────────────────────────
FRONTEND_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "frontend")
app = Flask(__name__, static_folder=FRONTEND_DIR, static_url_path="")

# CORS = Cross-Origin Resource Sharing.
# Browsers block JS from calling APIs on a different port/domain unless
# the server explicitly allows it.
CORS(app)

# Initialise DB (creates tables + seeds demo data) when the server starts.
init_db()

@app.route("/")
def serve_index():
    """Serve the single-page application frontend directly at root URL."""
    return send_from_directory(FRONTEND_DIR, "index.html")



# ══════════════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════

def err(msg: str, code: int = 400):
    """Return a consistent JSON error response."""
    return jsonify({"error": msg}), code


def row_to_dict(row) -> dict:
    """Convert a sqlite3.Row to a plain Python dict."""
    return dict(row)


def rows_to_list(rows) -> list:
    """Convert a list of sqlite3.Row objects to a list of dicts."""
    return [dict(r) for r in rows]


def compute_equal_splits(amount_paise: int, member_ids: list) -> list[tuple]:
    """
    Split `amount_paise` equally among `member_ids`.

    INTEGER DIVISION STRATEGY:
      Divide using integer floor division.  If there is a remainder,
      give 1 extra paisa to the first `remainder` members.

    Example: ₹10.01 (1001 paise) among 3 people
      base = 1001 // 3 = 333
      remainder = 1001 % 3 = 2
      → members 0,1 get 334 paise; member 2 gets 333 paise
      → total = 334 + 334 + 333 = 1001 ✓

    Returns: list of (member_id, share_paise) tuples
    """
    n = len(member_ids)
    base      = amount_paise // n        # floor division
    remainder = amount_paise % n         # left-over paise

    splits = []
    for i, mid in enumerate(member_ids):
        # First `remainder` members get one extra paisa
        share = base + (1 if i < remainder else 0)
        splits.append((mid, share))
    return splits


# ══════════════════════════════════════════════════════════════════════════
# GROUPS  –  /api/groups
# ══════════════════════════════════════════════════════════════════════════

@app.route("/api/groups", methods=["GET"])
def list_groups():
    """
    GET /api/groups?codes=code1,code2 or ?ids=1,2
    Returns groups matching the specified invite codes or ids.
    If no codes/ids are passed, returns empty list (unless ?all=1 is explicitly requested),
    ensuring private capability-based isolation so strangers cannot view other trips.
    """
    conn = get_db()
    codes = request.args.get("codes")
    ids = request.args.get("ids")
    show_all = request.args.get("all") == "1"

    if codes:
        code_list = [c.strip().lower() for c in codes.split(",") if c.strip()]
        if code_list:
            placeholders = ",".join("?" for _ in code_list)
            rows = conn.execute(
                f"SELECT id, name, invite_code, created_at FROM groups WHERE lower(invite_code) IN ({placeholders}) ORDER BY created_at DESC",
                code_list
            ).fetchall()
        else:
            rows = []
    elif ids:
        id_list = [int(i.strip()) for i in ids.split(",") if i.strip().isdigit()]
        if id_list:
            placeholders = ",".join("?" for _ in id_list)
            rows = conn.execute(
                f"SELECT id, name, invite_code, created_at FROM groups WHERE id IN ({placeholders}) ORDER BY created_at DESC",
                id_list
            ).fetchall()
        else:
            rows = []
    elif show_all:
        rows = conn.execute(
            "SELECT id, name, invite_code, created_at FROM groups ORDER BY created_at DESC"
        ).fetchall()
    else:
        # Default private behavior: return empty list if caller has no codes
        rows = []

    conn.close()
    return jsonify(rows_to_list(rows))


@app.route("/api/groups/sync", methods=["POST"])
def sync_groups():
    """
    POST /api/groups/sync
    Body: {
      "trips": [
        {
          "name": "...",
          "invite_code": "...",
          "members": [ { "name": "...", "upi_id": "..." } ],
          "expenses": [ { "title": "...", "amount_paise": ..., "payer_name": "...", "category": "...", "splits": [ { "member_name": "...", "share_paise": ... } ] } ]
        }
      ]
    }
    Ensures all trips, members, and expenses in the caller's storage exist in this database instance.
    If a serverless container cold-started, dynamically re-registers the trip and re-populates its members and expenses.
    Returns the synchronized list of groups with current IDs and member rosters.
    """
    data = request.get_json(silent=True) or {}
    trips = data.get("trips", [])
    if not isinstance(trips, list):
        return err("Field 'trips' must be a list.")

    conn = get_db()
    results = []

    for item in trips:
        if not isinstance(item, dict):
            continue
        code = (item.get("invite_code") or "").strip().lower()
        name = (item.get("name") or "").strip()
        members_input = item.get("members", [])
        expenses_input = item.get("expenses", [])
        if not code and not name:
            continue

        row = None
        if code:
            row = conn.execute(
                "SELECT id, name, invite_code, created_at FROM groups WHERE lower(invite_code) = ?",
                (code,)
            ).fetchone()

        if row is None and name:
            import secrets
            if not code:
                code = secrets.token_hex(4)
            try:
                cur = conn.execute(
                    "INSERT INTO groups (name, invite_code) VALUES (?, ?)",
                    (name[:100], code)
                )
                conn.commit()
                row = conn.execute(
                    "SELECT id, name, invite_code, created_at FROM groups WHERE id = ?",
                    (cur.lastrowid,)
                ).fetchone()
            except Exception:
                row = conn.execute(
                    "SELECT id, name, invite_code, created_at FROM groups WHERE lower(invite_code) = ?",
                    (code,)
                ).fetchone()

        if row:
            gid = row["id"]

            # Re-hydrate members if provided
            if isinstance(members_input, list) and len(members_input) > 0:
                for m in members_input:
                    if not isinstance(m, dict):
                        continue
                    m_name = (m.get("name") or "").strip()
                    m_upi = (m.get("upi_id") or "").strip() or None
                    if not m_name:
                        continue
                    m_exists = conn.execute(
                        "SELECT id FROM members WHERE group_id = ? AND lower(name) = lower(?)",
                        (gid, m_name)
                    ).fetchone()
                    if not m_exists:
                        conn.execute(
                            "INSERT INTO members (group_id, name, upi_id) VALUES (?, ?, ?)",
                            (gid, m_name[:80], m_upi)
                        )
                conn.commit()

            # Re-hydrate expenses if provided
            if isinstance(expenses_input, list) and len(expenses_input) > 0:
                for exp in expenses_input:
                    if not isinstance(exp, dict):
                        continue
                    exp_title = (exp.get("title") or "").strip()
                    exp_amount = exp.get("amount_paise")
                    exp_payer = (exp.get("payer_name") or "").strip()
                    exp_cat = (exp.get("category") or "General").strip()
                    splits = exp.get("splits", [])
                    if not exp_title or not exp_amount or not exp_payer:
                        continue

                    payer_row = conn.execute(
                        "SELECT id FROM members WHERE group_id = ? AND lower(name) = lower(?)",
                        (gid, exp_payer)
                    ).fetchone()
                    if not payer_row:
                        continue
                    payer_id = payer_row["id"]

                    exp_exists = conn.execute(
                        "SELECT id FROM expenses WHERE group_id = ? AND title = ? AND amount_paise = ?",
                        (gid, exp_title, exp_amount)
                    ).fetchone()
                    if not exp_exists:
                        cur_e = conn.execute(
                            "INSERT INTO expenses (group_id, title, amount_paise, payer_id, category) VALUES (?, ?, ?, ?, ?)",
                            (gid, exp_title, exp_amount, payer_id, exp_cat)
                        )
                        new_eid = cur_e.lastrowid
                        for s in splits:
                            s_name = (s.get("member_name") or "").strip()
                            s_share = s.get("share_paise", 0)
                            s_mem = conn.execute(
                                "SELECT id FROM members WHERE group_id = ? AND lower(name) = lower(?)",
                                (gid, s_name)
                            ).fetchone()
                            if s_mem:
                                conn.execute(
                                    "INSERT OR IGNORE INTO expense_splits (expense_id, member_id, share_paise) VALUES (?, ?, ?)",
                                    (new_eid, s_mem["id"], s_share)
                                )
                conn.commit()

            # Fetch live members for this group to return to caller
            m_rows = conn.execute(
                "SELECT id, name, upi_id FROM members WHERE group_id = ? ORDER BY id",
                (gid,)
            ).fetchall()

            res = row_to_dict(row)
            res["members"] = rows_to_list(m_rows)
            results.append(res)

    conn.close()
    return jsonify(results)


@app.route("/api/groups/join/<string:code>", methods=["GET"])
def join_group_by_code(code):
    """
    GET /api/groups/join/<invite_code>
    Looks up a group by its secret invite code (case-insensitive).
    Returns the group object or 404 if not found.
    """
    code_clean = code.strip().lower()
    conn = get_db()
    row = conn.execute(
        "SELECT id, name, invite_code, created_at FROM groups WHERE lower(invite_code) = ?",
        (code_clean,)
    ).fetchone()
    conn.close()

    if row is None:
        return err("Invalid invite code or group not found.", 404)
    return jsonify(row_to_dict(row))


@app.route("/api/groups", methods=["POST"])
def create_group():
    """
    POST /api/groups
    Body: { "name": "Weekend Trip" }
    Returns the newly created group with an unguessable invite_code.
    """
    data = request.get_json(silent=True)  # silent=True → returns None on bad JSON

    # ── Validate ──
    if not data or not isinstance(data.get("name"), str):
        return err("Field 'name' (string) is required.")

    name = data["name"].strip()
    if not name:
        return err("Group name cannot be blank.")
    if len(name) > 100:
        return err("Group name too long (max 100 chars).")

    # Generate unique 8-char hex invite code
    import secrets
    invite_code = secrets.token_hex(4)

    # ── Insert (parameterized query prevents SQL injection) ──
    conn = get_db()
    cur  = conn.execute("INSERT INTO groups (name, invite_code) VALUES (?, ?)", (name, invite_code))
    conn.commit()
    group_id = cur.lastrowid

    row = conn.execute(
        "SELECT id, name, invite_code, created_at FROM groups WHERE id = ?", (group_id,)
    ).fetchone()
    conn.close()

    return jsonify(row_to_dict(row)), 201   # 201 = Created


@app.route("/api/groups/<int:gid>", methods=["GET"])
def get_group(gid):
    """
    GET /api/groups/<id>
    Returns one group or 404 if not found.
    """
    conn = get_db()
    row  = conn.execute(
        "SELECT id, name, invite_code, created_at FROM groups WHERE id = ?", (gid,)
    ).fetchone()
    conn.close()

    if row is None:
        return err("Group not found.", 404)
    return jsonify(row_to_dict(row))


@app.route("/api/groups/<int:gid>", methods=["DELETE"])
def delete_group(gid):
    """
    DELETE /api/groups/<id>
    Deletes the group.  ON DELETE CASCADE removes all related rows.
    """
    conn = get_db()
    cur  = conn.execute("DELETE FROM groups WHERE id = ?", (gid,))
    conn.commit()
    conn.close()

    if cur.rowcount == 0:
        return err("Group not found.", 404)
    return jsonify({"message": "Group deleted."})


# ══════════════════════════════════════════════════════════════════════════
# MEMBERS  –  /api/groups/<gid>/members
# ══════════════════════════════════════════════════════════════════════════

@app.route("/api/groups/<int:gid>/members", methods=["GET"])
def list_members(gid):
    """
    GET /api/groups/<id>/members
    Returns all members of a group.
    """
    conn = get_db()
    # Check group exists first
    if not conn.execute("SELECT 1 FROM groups WHERE id=?", (gid,)).fetchone():
        conn.close()
        return err("Group not found.", 404)

    rows = conn.execute(
        "SELECT id, name, upi_id, created_at FROM members WHERE group_id=? ORDER BY id",
        (gid,)
    ).fetchall()
    conn.close()
    return jsonify(rows_to_list(rows))


@app.route("/api/groups/<int:gid>/members", methods=["POST"])
def add_member(gid):
    """
    POST /api/groups/<id>/members
    Body: { "name": "Alice", "upi_id": "alice@upi" }
    upi_id is optional.
    """
    conn = get_db()

    # Check group exists
    if not conn.execute("SELECT 1 FROM groups WHERE id=?", (gid,)).fetchone():
        conn.close()
        return err("Group not found.", 404)

    data = request.get_json(silent=True)
    if not data or not isinstance(data.get("name"), str):
        conn.close()
        return err("Field 'name' (string) is required.")

    name   = data["name"].strip()
    upi_id = data.get("upi_id", "").strip() or None

    if not name:
        conn.close()
        return err("Member name cannot be blank.")
    if len(name) > 80:
        conn.close()
        return err("Name too long (max 80 chars).")

    cur = conn.execute(
        "INSERT INTO members (group_id, name, upi_id) VALUES (?, ?, ?)",
        (gid, name, upi_id)
    )
    conn.commit()
    member_id = cur.lastrowid

    row = conn.execute(
        "SELECT id, name, upi_id, created_at FROM members WHERE id=?", (member_id,)
    ).fetchone()
    conn.close()
    return jsonify(row_to_dict(row)), 201


@app.route("/api/members/<int:mid>", methods=["DELETE"])
def remove_member(mid):
    """
    DELETE /api/members/<id>
    Removes a member.  ON DELETE CASCADE removes their splits/settlements too.
    Refuses to remove if they are a payer of any expense (would lose data).
    """
    conn = get_db()

    # Safety check – do not delete if this member paid any expense
    paid = conn.execute(
        "SELECT COUNT(*) FROM expenses WHERE payer_id=?", (mid,)
    ).fetchone()[0]

    if paid > 0:
        conn.close()
        return err(
            f"Cannot remove member: they paid {paid} expense(s). "
            "Delete those expenses first.", 409   # 409 = Conflict
        )

    cur = conn.execute("DELETE FROM members WHERE id=?", (mid,))
    conn.commit()
    conn.close()

    if cur.rowcount == 0:
        return err("Member not found.", 404)
    return jsonify({"message": "Member removed."})


# ══════════════════════════════════════════════════════════════════════════
# EXPENSES  –  /api/groups/<gid>/expenses
# ══════════════════════════════════════════════════════════════════════════

@app.route("/api/groups/<int:gid>/expenses", methods=["GET"])
def list_expenses(gid):
    """
    GET /api/groups/<id>/expenses
    Returns expenses with payer name and split details.
    """
    conn = get_db()

    if not conn.execute("SELECT 1 FROM groups WHERE id=?", (gid,)).fetchone():
        conn.close()
        return err("Group not found.", 404)

    # JOIN to get payer name alongside the expense
    expenses = conn.execute("""
        SELECT e.id, e.title, e.amount_paise, e.category, e.created_at,
               m.id   AS payer_id,
               m.name AS payer_name
        FROM   expenses e
        JOIN   members  m ON e.payer_id = m.id
        WHERE  e.group_id = ?
        ORDER  BY e.created_at DESC
    """, (gid,)).fetchall()

    result = []
    for exp in expenses:
        exp_dict = dict(exp)

        # Fetch individual splits for this expense
        splits = conn.execute("""
            SELECT m.id AS member_id, m.name AS member_name, s.share_paise
            FROM   expense_splits s
            JOIN   members        m ON s.member_id = m.id
            WHERE  s.expense_id = ?
        """, (exp["id"],)).fetchall()

        exp_dict["splits"] = rows_to_list(splits)
        result.append(exp_dict)

    conn.close()
    return jsonify(result)


@app.route("/api/groups/<int:gid>/expenses", methods=["POST"])
def add_expense(gid):
    """
    POST /api/groups/<id>/expenses

    Body for EQUAL split:
    {
      "title":    "Dinner",
      "amount":   2400,          ← rupees (we convert to paise)
      "payer_id": 1,
      "category": "Food",        ← optional, default "General"
      "split":    "equal"        ← split all members equally
    }

    Body for CUSTOM split:
    {
      "title":    "Snacks",
      "amount":   540,
      "payer_id": 4,
      "category": "Food",
      "split":    "custom",
      "shares":   [              ← must sum to amount (rupees)
        {"member_id": 1, "amount": 200},
        {"member_id": 2, "amount": 150},
        {"member_id": 3, "amount": 100},
        {"member_id": 4, "amount": 90}
      ]
    }
    """
    conn = get_db()

    if not conn.execute("SELECT 1 FROM groups WHERE id=?", (gid,)).fetchone():
        conn.close()
        return err("Group not found.", 404)

    data = request.get_json(silent=True)
    if not data:
        conn.close()
        return err("JSON body required.")

    # ── Field validation ──
    title    = str(data.get("title",    "")).strip()
    category = str(data.get("category", "General")).strip() or "General"
    split    = str(data.get("split",    "equal")).lower()

    if not title:
        conn.close()
        return err("'title' is required.")
    if len(title) > 120:
        conn.close()
        return err("Title too long (max 120 chars).")

    # Amount must be a positive number (rupees from frontend)
    try:
        amount_rupees = float(data["amount"])
    except (KeyError, TypeError, ValueError):
        conn.close()
        return err("'amount' must be a positive number (in rupees).")

    if amount_rupees <= 0:
        conn.close()
        return err("Amount must be greater than zero.")

    # Convert rupees → paise using round() to handle floating-point noise
    amount_paise = round(amount_rupees * 100)

    payer_id = data.get("payer_id")
    if not isinstance(payer_id, int):
        conn.close()
        return err("'payer_id' must be an integer member ID.")

    # Check payer exists in this group
    payer = conn.execute(
        "SELECT id FROM members WHERE id=? AND group_id=?", (payer_id, gid)
    ).fetchone()
    if not payer:
        conn.close()
        return err("Payer not found in this group.", 404)

    if split not in ("equal", "custom"):
        conn.close()
        return err("'split' must be 'equal' or 'custom'.")

    # ── Build splits list ──────────────────────────────────────
    if split == "equal":
        # Get all member IDs in the group
        member_ids = [
            r["id"] for r in conn.execute(
                "SELECT id FROM members WHERE group_id=? ORDER BY id", (gid,)
            ).fetchall()
        ]
        if not member_ids:
            conn.close()
            return err("Group has no members.")

        splits_data = compute_equal_splits(amount_paise, member_ids)
        # splits_data = [(member_id, share_paise), ...]

    else:  # custom split
        shares = data.get("shares")
        if not isinstance(shares, list) or len(shares) == 0:
            conn.close()
            return err("'shares' list required for custom split.")

        # Validate each share entry
        splits_data = []
        total_custom_paise = 0
        seen_members = set()

        for s in shares:
            mid = s.get("member_id")
            amt = s.get("amount")  # in rupees

            if not isinstance(mid, int) or not isinstance(amt, (int, float)):
                conn.close()
                return err("Each share needs integer 'member_id' and numeric 'amount'.")

            if mid in seen_members:
                conn.close()
                return err(f"Duplicate member_id {mid} in shares.")
            seen_members.add(mid)

            # Check member belongs to this group
            if not conn.execute(
                "SELECT 1 FROM members WHERE id=? AND group_id=?", (mid, gid)
            ).fetchone():
                conn.close()
                return err(f"Member {mid} not in this group.", 404)

            share_paise = round(float(amt) * 100)
            if share_paise < 0:
                conn.close()
                return err("Share amounts cannot be negative.")

            total_custom_paise += share_paise
            splits_data.append((mid, share_paise))

        # Custom splits MUST sum exactly to the total
        if total_custom_paise != amount_paise:
            diff = (total_custom_paise - amount_paise) / 100
            conn.close()
            return err(
                f"Custom splits sum to ₹{total_custom_paise/100:.2f}, "
                f"but expense is ₹{amount_paise/100:.2f} "
                f"(difference: ₹{diff:.2f})."
            )

    # ── Insert expense ─────────────────────────────────────────
    cur = conn.execute(
        """INSERT INTO expenses (group_id, title, amount_paise, payer_id, category)
           VALUES (?, ?, ?, ?, ?)""",
        (gid, title, amount_paise, payer_id, category)
    )
    expense_id = cur.lastrowid

    # ── Insert splits ──────────────────────────────────────────
    for (mid, share_paise) in splits_data:
        conn.execute(
            """INSERT INTO expense_splits (expense_id, member_id, share_paise)
               VALUES (?, ?, ?)""",
            (expense_id, mid, share_paise)
        )

    conn.commit()

    # Return the newly created expense with its splits
    row = conn.execute(
        """SELECT e.id, e.title, e.amount_paise, e.category, e.created_at,
                  m.name AS payer_name
           FROM expenses e JOIN members m ON e.payer_id=m.id
           WHERE e.id=?""",
        (expense_id,)
    ).fetchone()
    conn.close()

    response = dict(row)
    response["splits"] = [{"member_id": mid, "share_paise": sp} for mid, sp in splits_data]
    return jsonify(response), 201


@app.route("/api/expenses/<int:eid>", methods=["DELETE"])
def delete_expense(eid):
    """
    DELETE /api/expenses/<id>
    Deletes an expense and its splits (CASCADE handles splits).
    """
    conn = get_db()
    cur  = conn.execute("DELETE FROM expenses WHERE id=?", (eid,))
    conn.commit()
    conn.close()

    if cur.rowcount == 0:
        return err("Expense not found.", 404)
    return jsonify({"message": "Expense deleted."})


# ══════════════════════════════════════════════════════════════════════════
# SUMMARY (DASHBOARD)  –  /api/groups/<gid>/summary
# ══════════════════════════════════════════════════════════════════════════

@app.route("/api/groups/<int:gid>/summary", methods=["GET"])
def group_summary(gid):
    """
    GET /api/groups/<id>/summary

    Returns:
    {
      "total_paise": 980000,
      "member_count": 4,
      "per_head_paise": 245000,     ← total / member_count
      "members": [
        {
          "id": 1, "name": "Shubh",
          "paid_paise": 240000,      ← how much they paid out
          "owes_paise": 245000,      ← their share of all expenses
          "net_paise":  -5000        ← positive = others owe them; negative = they owe
        }, ...
      ]
    }

    NET BALANCE FORMULA:
      net = paid − owes
      net > 0  →  this person is owed money (they overpaid)
      net < 0  →  this person owes money   (they underpaid)
      Sum of all nets must = 0 (money is conserved).
    """
    conn = get_db()

    if not conn.execute("SELECT 1 FROM groups WHERE id=?", (gid,)).fetchone():
        conn.close()
        return err("Group not found.", 404)

    # Total amount spent in the group
    total_row    = conn.execute(
        "SELECT COALESCE(SUM(amount_paise),0) FROM expenses WHERE group_id=?", (gid,)
    ).fetchone()
    total_paise  = total_row[0]

    # All members
    members      = conn.execute(
        "SELECT id, name, upi_id FROM members WHERE group_id=? ORDER BY id", (gid,)
    ).fetchall()
    member_count = len(members)

    per_head = (total_paise // member_count) if member_count else 0

    result_members = []
    for m in members:
        mid = m["id"]

        # How much did this person PAY? (sum of expenses where payer_id = mid)
        paid = conn.execute(
            "SELECT COALESCE(SUM(amount_paise),0) FROM expenses WHERE payer_id=? AND group_id=?",
            (mid, gid)
        ).fetchone()[0]

        # How much is this person's SHARE? (sum of their splits in this group)
        owes = conn.execute(
            """SELECT COALESCE(SUM(s.share_paise),0)
               FROM expense_splits s
               JOIN expenses e ON s.expense_id = e.id
               WHERE s.member_id=? AND e.group_id=?""",
            (mid, gid)
        ).fetchone()[0]

        net = paid - owes   # positive = owed by others; negative = owes others

        result_members.append({
            "id":         mid,
            "name":       m["name"],
            "upi_id":     m["upi_id"],
            "paid_paise": paid,
            "owes_paise": owes,
            "net_paise":  net
        })

    conn.close()
    return jsonify({
        "group_id":      gid,
        "total_paise":   total_paise,
        "member_count":  member_count,
        "per_head_paise": per_head,
        "members":       result_members
    })


# ══════════════════════════════════════════════════════════════════════════
# ANALYTICS  –  /api/groups/<gid>/analytics
# ══════════════════════════════════════════════════════════════════════════

@app.route("/api/groups/<int:gid>/analytics", methods=["GET"])
def group_analytics(gid):
    """
    GET /api/groups/<id>/analytics

    Returns two datasets for the frontend charts:
    {
      "by_member": [
        {"name": "Shubh", "paid_paise": 240000}, ...
      ],
      "by_category": [
        {"category": "Food", "total_paise": 294000}, ...
      ]
    }
    """
    conn = get_db()

    if not conn.execute("SELECT 1 FROM groups WHERE id=?", (gid,)).fetchone():
        conn.close()
        return err("Group not found.", 404)

    # Spend aggregated by payer
    by_member = conn.execute("""
        SELECT m.name, COALESCE(SUM(e.amount_paise),0) AS paid_paise
        FROM   members  m
        LEFT JOIN expenses e ON e.payer_id = m.id AND e.group_id = m.group_id
        WHERE  m.group_id = ?
        GROUP  BY m.id
        ORDER  BY paid_paise DESC
    """, (gid,)).fetchall()

    # Spend aggregated by category
    by_category = conn.execute("""
        SELECT category, SUM(amount_paise) AS total_paise
        FROM   expenses
        WHERE  group_id = ?
        GROUP  BY category
        ORDER  BY total_paise DESC
    """, (gid,)).fetchall()

    conn.close()
    return jsonify({
        "by_member":   rows_to_list(by_member),
        "by_category": rows_to_list(by_category)
    })


# ══════════════════════════════════════════════════════════════════════════
# MESSAGES (CHAT)  –  /api/groups/<gid>/messages
# ══════════════════════════════════════════════════════════════════════════

@app.route("/api/groups/<int:gid>/messages", methods=["GET"])
def list_messages(gid):
    """
    GET /api/groups/<id>/messages?since=<id>

    For live chat we use polling: the frontend calls this every 5 seconds.
    The optional `since` query-param lets it ask only for NEW messages
    (messages with id > since), avoiding re-downloading old ones.

    Example: GET /api/groups/1/messages?since=12
    Returns messages 13, 14, 15 ...
    """
    conn = get_db()

    if not conn.execute("SELECT 1 FROM groups WHERE id=?", (gid,)).fetchone():
        conn.close()
        return err("Group not found.", 404)

    since = request.args.get("since", 0, type=int)  # default 0 = all messages

    rows = conn.execute(
        """SELECT id, sender, body, created_at
           FROM   messages
           WHERE  group_id = ? AND id > ?
           ORDER  BY id ASC""",
        (gid, since)
    ).fetchall()
    conn.close()
    return jsonify(rows_to_list(rows))


@app.route("/api/groups/<int:gid>/messages", methods=["POST"])
def send_message(gid):
    """
    POST /api/groups/<id>/messages
    Body: { "sender": "Shubh", "body": "Who paid for the cab?" }
    """
    conn = get_db()

    if not conn.execute("SELECT 1 FROM groups WHERE id=?", (gid,)).fetchone():
        conn.close()
        return err("Group not found.", 404)

    data   = request.get_json(silent=True)
    sender = str(data.get("sender", "")).strip() if data else ""
    body   = str(data.get("body",   "")).strip() if data else ""

    if not sender:
        conn.close()
        return err("'sender' is required.")
    if not body:
        conn.close()
        return err("'body' (message text) is required.")
    if len(body) > 500:
        conn.close()
        return err("Message too long (max 500 chars).")

    cur = conn.execute(
        "INSERT INTO messages (group_id, sender, body) VALUES (?,?,?)",
        (gid, sender, body)
    )
    conn.commit()
    msg_id = cur.lastrowid

    row = conn.execute(
        "SELECT id, sender, body, created_at FROM messages WHERE id=?", (msg_id,)
    ).fetchone()
    conn.close()
    return jsonify(row_to_dict(row)), 201


# ══════════════════════════════════════════════════════════════════════════
# CSV EXPORT  –  /api/groups/<gid>/export.csv
# ══════════════════════════════════════════════════════════════════════════

@app.route("/api/groups/<int:gid>/export.csv", methods=["GET"])
def export_csv(gid):
    """
    GET /api/groups/<id>/export.csv

    Downloads a CSV file with all expenses and per-member splits.
    The C validator (Stage 5) and Java report tool (Stage 6) read this file.

    CSV columns:
      expense_id, title, category, amount_paise, payer_name,
      member_name, share_paise, created_at
    """
    conn = get_db()

    if not conn.execute("SELECT 1 FROM groups WHERE id=?", (gid,)).fetchone():
        conn.close()
        return err("Group not found.", 404)

    group_name = conn.execute(
        "SELECT name FROM groups WHERE id=?", (gid,)
    ).fetchone()["name"]

    rows = conn.execute("""
        SELECT e.id        AS expense_id,
               e.title,
               e.category,
               e.amount_paise,
               p.name      AS payer_name,
               m.name      AS member_name,
               s.share_paise,
               e.created_at
        FROM   expense_splits s
        JOIN   expenses       e ON s.expense_id = e.id
        JOIN   members        p ON e.payer_id   = p.id
        JOIN   members        m ON s.member_id  = m.id
        WHERE  e.group_id = ?
        ORDER  BY e.id, m.id
    """, (gid,)).fetchall()
    conn.close()

    # Build CSV in-memory using Python's csv module
    output = io.StringIO()
    writer = csv.writer(output)

    # Header row
    writer.writerow([
        "expense_id", "title", "category",
        "amount_paise", "payer_name",
        "member_name", "share_paise", "created_at"
    ])

    for r in rows:
        writer.writerow([
            r["expense_id"], r["title"], r["category"],
            r["amount_paise"], r["payer_name"],
            r["member_name"], r["share_paise"], r["created_at"]
        ])

    # Build the HTTP response with correct Content-Type for file download
    response = make_response(output.getvalue())
    response.headers["Content-Type"] = "text/csv"
    # This header tells the browser to download the file instead of showing it
    safe_name = group_name.replace(" ", "_")
    response.headers["Content-Disposition"] = f'attachment; filename="{safe_name}_expenses.csv"'
    return response


# ══════════════════════════════════════════════════════════════════════════
# HEALTH CHECK
# ══════════════════════════════════════════════════════════════════════════

@app.route("/api/health", methods=["GET"])
def health():
    """Simple ping endpoint – useful to check if the server is running."""
    return jsonify({"status": "ok", "app": "Innov8"})


@app.route("/api/network-info", methods=["GET"])
def network_info():
    """Returns local LAN IP and public cloudflare tunnel URL for easy multi-device connection."""
    import socket
    local_ip = "127.0.0.1"
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
    except Exception:
        pass

    public_url = "https://decreased-pregnant-interaction-testimonials.trycloudflare.com"
    return jsonify({
        "local_ip": local_ip,
        "local_url": f"http://{local_ip}:5000",
        "public_url": public_url,
    })


# ══════════════════════════════════════════════════════════════════════════
# SETTLEMENTS  –  /api/groups/<gid>/settlements
# ══════════════════════════════════════════════════════════════════════════

@app.route("/api/groups/<int:gid>/settlements", methods=["GET"])
def get_settlements(gid):
    """
    GET /api/groups/<id>/settlements

    Fetches stored settlements for the group.  If none exist yet,
    automatically computes them using the greedy algorithm and saves them.

    Also enriches each settlement with a UPI deep link and QR URL so the
    frontend can show a one-tap payment button.

    UPI DEEP LINK FORMAT:
      upi://pay?pa=<upi_id>&pn=<name>&am=<amount_rupees>&cu=INR
      pa = Payee Address (UPI ID), pn = Payee Name, am = Amount, cu = Currency
    """
    conn = get_db()

    if not conn.execute("SELECT 1 FROM groups WHERE id=?", (gid,)).fetchone():
        conn.close()
        return err("Group not found.", 404)

    # Check if settlements already computed for this group
    existing = conn.execute(
        "SELECT COUNT(*) FROM settlements WHERE group_id=?", (gid,)
    ).fetchone()[0]

    if existing == 0:
        # Compute net balances from the DB
        members = conn.execute(
            "SELECT id FROM members WHERE group_id=?", (gid,)
        ).fetchall()

        net_balances = {}
        for m in members:
            mid = m["id"]
            paid = conn.execute(
                "SELECT COALESCE(SUM(amount_paise),0) FROM expenses WHERE payer_id=? AND group_id=?",
                (mid, gid)
            ).fetchone()[0]
            owes = conn.execute(
                """SELECT COALESCE(SUM(s.share_paise),0)
                   FROM expense_splits s
                   JOIN expenses e ON s.expense_id=e.id
                   WHERE s.member_id=? AND e.group_id=?""",
                (mid, gid)
            ).fetchone()[0]
            net_balances[mid] = paid - owes

        # Run the greedy algorithm (C++ or Python fallback)
        transactions = compute_settlements(net_balances)

        # Save each transaction to the settlements table
        for t in transactions:
            conn.execute(
                """INSERT INTO settlements
                   (group_id, from_member, to_member, amount_paise, status)
                   VALUES (?, ?, ?, ?, 'pending')""",
                (gid, t["from_id"], t["to_id"], t["amount_paise"])
            )
        conn.commit()

    # Fetch all settlements with member names and UPI IDs
    rows = conn.execute("""
        SELECT s.id, s.amount_paise, s.status, s.created_at,
               f.id   AS from_id,   f.name AS from_name, f.upi_id AS from_upi,
               t.id   AS to_id,     t.name AS to_name,   t.upi_id AS to_upi
        FROM   settlements s
        JOIN   members f ON s.from_member = f.id
        JOIN   members t ON s.to_member   = t.id
        WHERE  s.group_id = ?
        ORDER  BY s.id
    """, (gid,)).fetchall()
    conn.close()

    result = []
    for r in rows:
        amount_rupees = r["amount_paise"] / 100

        # Build UPI deep link (only if receiver has a UPI ID)
        upi_link = None
        if r["to_upi"]:
            upi_link = (
                f"upi://pay"
                f"?pa={r['to_upi']}"
                f"&pn={r['to_name'].replace(' ', '%20')}"
                f"&am={amount_rupees:.2f}"
                f"&cu=INR"
            )

        # QR code via Google Charts (no library needed – just a URL)
        qr_url = None
        if upi_link:
            import urllib.parse
            encoded = urllib.parse.quote(upi_link)
            qr_url  = f"https://api.qrserver.com/v1/create-qr-code/?size=200x200&data={encoded}"

        result.append({
            "id":           r["id"],
            "from_id":      r["from_id"],
            "from_name":    r["from_name"],
            "to_id":        r["to_id"],
            "to_name":      r["to_name"],
            "amount_paise": r["amount_paise"],
            "status":       r["status"],
            "created_at":   r["created_at"],
            "upi_link":     upi_link,
            "qr_url":       qr_url
        })

    return jsonify(result)


@app.route("/api/groups/<int:gid>/settlements/recalculate", methods=["POST"])
def recalculate_settlements(gid):
    """
    POST /api/groups/<id>/settlements/recalculate

    Deletes old settlements and recomputes them.
    Call this whenever new expenses are added.
    """
    conn = get_db()

    if not conn.execute("SELECT 1 FROM groups WHERE id=?", (gid,)).fetchone():
        conn.close()
        return err("Group not found.", 404)

    # Delete old settlements for this group
    conn.execute("DELETE FROM settlements WHERE group_id=?", (gid,))
    conn.commit()
    conn.close()

    # Re-use the GET endpoint logic to recompute
    return get_settlements(gid)


@app.route("/api/settlements/<int:sid>", methods=["PATCH"])
def mark_settlement_done(sid):
    """
    PATCH /api/settlements/<id>
    Body: { "status": "done" }

    Marks a settlement as paid.  Used when UPI payment is confirmed.
    """
    data   = request.get_json(silent=True)
    status = (data or {}).get("status", "done")

    if status not in ("pending", "done"):
        return err("status must be 'pending' or 'done'.")

    conn = get_db()
    cur  = conn.execute(
        "UPDATE settlements SET status=? WHERE id=?", (status, sid)
    )
    conn.commit()
    conn.close()

    if cur.rowcount == 0:
        return err("Settlement not found.", 404)
    return jsonify({"message": f"Settlement marked as {status}."})


# ── Entry point ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # debug=True → auto-restarts when you save a file.  Disable in production!
    # host="0.0.0.0" → accessible from other devices on the same Wi-Fi (for demos).
    app.run(debug=True, host="0.0.0.0", port=5000)

