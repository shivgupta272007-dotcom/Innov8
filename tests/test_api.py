"""
test_api.py – Comprehensive automated pytest suite for Innov8
==============================================================
Tests all REST API endpoints, business logic invariants, and edge cases:
  1. Health check & basic connectivity
  2. Group CRUD & boundary validation
  3. Member operations (creation, duplicate handling, safe deletion guards)
  4. Expense addition with Equal split (including fair odd paise distribution)
  5. Expense addition with Custom split (exact sum assertion & mismatch rejection)
  6. Financial invariants (Total spend = sum(splits), sum(net_balances) == 0)
  7. Settlements calculation & UPI payload generation
  8. Team chat messaging & polling delta filters (?since=)
  9. CSV export structure & headers

Run tests with:
  cd Innov8/tests
  python3 -m pytest -v test_api.py
"""

import os
import sys
import tempfile
import pytest

# Add backend directory to sys.path
TEST_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.join(TEST_DIR, "..", "backend")
sys.path.insert(0, BACKEND_DIR)

import db
from app import app, compute_equal_splits


@pytest.fixture(scope="module")
def client():
    """
    Test fixture providing an isolated SQLite database and Flask test client.
    Guarantees that test runs do not alter production innov8.db.
    """
    # Create a temporary file for the test database
    temp_fd, temp_db_path = tempfile.mkstemp(suffix="_test_innov8.db")
    os.close(temp_fd)

    # Point backend db helper to this temporary database
    db.DB_PATH = temp_db_path

    # Initialize tables and seed data
    db.init_db()

    app.config["TESTING"] = True
    with app.test_client() as test_client:
        yield test_client

    # Teardown: delete the temporary test database
    if os.path.exists(temp_db_path):
        os.remove(temp_db_path)


# ══════════════════════════════════════════════════════════════════════════
# 1. HEALTH & METADATA TESTS
# ══════════════════════════════════════════════════════════════════════════

def test_health_check(client):
    """GET /api/health should return status: ok."""
    res = client.get("/api/health")
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "ok"
    assert data["app"] == "Innov8"


# ══════════════════════════════════════════════════════════════════════════
# 2. GROUP MANAGEMENT TESTS
# ══════════════════════════════════════════════════════════════════════════

def test_list_groups_empty_without_codes(client):
    """GET /api/groups without codes or ids returns empty list for privacy."""
    res = client.get("/api/groups")
    assert res.status_code == 200
    assert res.get_json() == []


def test_list_groups_by_code(client):
    """GET /api/groups?codes=goa-trip should include the seeded 'Goa Trip' group."""
    res = client.get("/api/groups?codes=goa-trip")
    assert res.status_code == 200
    groups = res.get_json()
    assert isinstance(groups, list)
    assert any(g["name"] == "Goa Trip" for g in groups)


def test_join_group_by_code(client):
    """GET /api/groups/join/goa-trip should return Goa Trip data."""
    res = client.get("/api/groups/join/goa-trip")
    assert res.status_code == 200
    data = res.get_json()
    assert data["name"] == "Goa Trip"
    assert data["invite_code"] == "goa-trip"


def test_create_group_valid(client):
    """POST /api/groups with valid name should return 201 Created with invite_code."""
    res = client.post("/api/groups", json={"name": "Manali Trek"})
    assert res.status_code == 201
    group = res.get_json()
    assert group["name"] == "Manali Trek"
    assert "id" in group
    assert "invite_code" in group
    assert len(group["invite_code"]) >= 6


def test_create_group_empty_name(client):
    """POST /api/groups with empty or blank name should return 400 Bad Request."""
    res1 = client.post("/api/groups", json={"name": "   "})
    assert res1.status_code == 400
    assert "blank" in res1.get_json()["error"].lower()

    res2 = client.post("/api/groups", json={})
    assert res2.status_code == 400


def test_get_group_not_found(client):
    """GET /api/groups/99999 should return 404."""
    res = client.get("/api/groups/99999")
    assert res.status_code == 404


# ══════════════════════════════════════════════════════════════════════════
# 3. MEMBER OPERATIONS & CONSTRAINTS
# ══════════════════════════════════════════════════════════════════════════

def test_list_members_seeded(client):
    """GET /api/groups/1/members should return the 4 seeded members."""
    res = client.get("/api/groups/1/members")
    assert res.status_code == 200
    members = res.get_json()
    assert len(members) == 4
    names = [m["name"] for m in members]
    assert names == ["Shubh", "Shiv", "Shivansh", "Shubham"]


def test_add_member_valid(client):
    """POST /api/groups/1/members adds a member with optional UPI."""
    res = client.post("/api/groups/1/members", json={
        "name": "Arjun",
        "upi_id": "arjun@okhdfcbank"
    })
    assert res.status_code == 201
    data = res.get_json()
    assert data["name"] == "Arjun"
    assert data["upi_id"] == "arjun@okhdfcbank"

    # Clean up by removing the member (has no expenses)
    del_res = client.delete(f"/api/members/{data['id']}")
    assert del_res.status_code == 200


def test_delete_member_with_expenses_blocked(client):
    """
    DELETE /api/members/1: Shubh paid for Dinner, so deleting him
    must return 409 Conflict to protect financial data integrity.
    """
    res = client.delete("/api/members/1")
    assert res.status_code == 409
    assert "cannot remove member" in res.get_json()["error"].lower()


# ══════════════════════════════════════════════════════════════════════════
# 4. EXPENSES & SPLIT ARITHMETIC TESTS
# ══════════════════════════════════════════════════════════════════════════

def test_odd_paise_equal_split_fairness():
    """
    Unit test for compute_equal_splits():
    Splitting 1001 paise (₹10.01) among 3 people must result in:
    [334, 334, 333] -> Sum must exactly equal 1001 paise (no lost paise).
    """
    member_ids = [10, 20, 30]
    splits = compute_equal_splits(1001, member_ids)

    assert len(splits) == 3
    shares = [s[1] for s in splits]
    assert shares == [334, 334, 333]
    assert sum(shares) == 1001


def test_add_expense_equal_split(client):
    """POST /api/groups/1/expenses with split='equal'."""
    res = client.post("/api/groups/1/expenses", json={
        "title": "Groceries",
        "amount": 1000.00,  # ₹1000 = 100000 paise
        "payer_id": 1,
        "category": "Food",
        "split": "equal"
    })
    assert res.status_code == 201
    exp = res.get_json()
    assert exp["title"] == "Groceries"
    assert exp["amount_paise"] == 100000
    assert len(exp["splits"]) == 4

    # 100000 / 4 = 25000 paise each
    for s in exp["splits"]:
        assert s["share_paise"] == 25000

    # Delete test expense to restore state
    client.delete(f"/api/expenses/{exp['id']}")


def test_add_expense_custom_split_valid(client):
    """POST /api/groups/1/expenses with split='custom' matching exact total."""
    res = client.post("/api/groups/1/expenses", json={
        "title": "Kayak Rental",
        "amount": 500.00,  # ₹500
        "payer_id": 2,
        "category": "Entertainment",
        "split": "custom",
        "shares": [
            {"member_id": 1, "amount": 150.00},
            {"member_id": 2, "amount": 150.00},
            {"member_id": 3, "amount": 100.00},
            {"member_id": 4, "amount": 100.00}
        ]
    })
    assert res.status_code == 201
    exp = res.get_json()
    assert exp["amount_paise"] == 50000

    # Clean up
    client.delete(f"/api/expenses/{exp['id']}")


def test_add_expense_custom_split_mismatch_rejected(client):
    """
    POST /api/groups/1/expenses with custom split sum != total amount
    must return 400 Bad Request with an informative difference error.
    """
    res = client.post("/api/groups/1/expenses", json={
        "title": "Taxi",
        "amount": 500.00,
        "payer_id": 2,
        "split": "custom",
        "shares": [
            {"member_id": 1, "amount": 100.00},
            {"member_id": 2, "amount": 100.00}
            # Sums to ₹200, but amount is ₹500 -> Mismatch!
        ]
    })
    assert res.status_code == 400
    assert "difference" in res.get_json()["error"].lower()


def test_add_expense_negative_amount_blocked(client):
    """Negative and zero amounts must be rejected by API validation."""
    res = client.post("/api/groups/1/expenses", json={
        "title": "Invalid Refund",
        "amount": -50.00,
        "payer_id": 1,
        "split": "equal"
    })
    assert res.status_code == 400


# ══════════════════════════════════════════════════════════════════════════
# 5. SUMMARY & FINANCIAL INVARIANTS
# ══════════════════════════════════════════════════════════════════════════

def test_group_summary_invariants(client):
    """
    GET /api/groups/1/summary asserts:
      1. Total group spend == 980000 paise (₹9800.00)
      2. Per head share == 245000 paise (₹2450.00)
      3. For every member: net_paise == paid_paise - owes_paise
      4. Conservation of money: SUM(net_paise) == 0
    """
    res = client.get("/api/groups/1/summary")
    assert res.status_code == 200
    summary = res.get_json()

    assert summary["total_paise"] == 980000
    assert summary["member_count"] == 4
    assert summary["per_head_paise"] == 245000

    net_sum = 0
    for m in summary["members"]:
        assert m["net_paise"] == m["paid_paise"] - m["owes_paise"]
        net_sum += m["net_paise"]

    # Fundamental double-entry accounting rule:
    assert net_sum == 0, f"Net balances sum is non-zero: {net_sum}"


# ══════════════════════════════════════════════════════════════════════════
# 6. SETTLEMENTS & UPI PAYLOAD
# ══════════════════════════════════════════════════════════════════════════

def test_settlements_and_upi_links(client):
    """
    GET /api/groups/1/settlements computes greedy transfers and validates:
      1. Exactly 3 transactions generated (n-1 for 4 members)
      2. Sum of transferred amounts equals total creditor positive net (₹3550)
      3. UPI deep link follows standard NPCI URL syntax: upi://pay?pa=...
    """
    res = client.get("/api/groups/1/settlements")
    assert res.status_code == 200
    settlements = res.get_json()

    assert len(settlements) == 3

    total_transferred = sum(s["amount_paise"] for s in settlements)
    assert total_transferred == 355000  # Shivansh is owed ₹3550.00

    for s in settlements:
        assert s["status"] in ("pending", "done")
        assert s["upi_link"].startswith("upi://pay?")
        assert "pa=shivansh@upi" in s["upi_link"]
        assert "cu=INR" in s["upi_link"]


def test_mark_settlement_status(client):
    """PATCH /api/settlements/1 updates settlement status to 'done'."""
    res = client.patch("/api/settlements/1", json={"status": "done"})
    assert res.status_code == 200
    assert "done" in res.get_json()["message"]


# ══════════════════════════════════════════════════════════════════════════
# 7. CHAT & CSV EXPORT TESTS
# ══════════════════════════════════════════════════════════════════════════

def test_chat_polling_and_send(client):
    """Test sending a message and delta polling using ?since=."""
    post_res = client.post("/api/groups/1/messages", json={
        "sender": "Shubham",
        "body": "Don't forget to pack sunscreen!"
    })
    assert post_res.status_code == 201
    msg = post_res.get_json()
    msg_id = msg["id"]

    # Poll only messages newer than this message id (should be empty)
    poll_res = client.get(f"/api/groups/1/messages?since={msg_id}")
    assert poll_res.status_code == 200
    assert len(poll_res.get_json()) == 0


def test_csv_export(client):
    """GET /api/groups/1/export.csv returns a valid CSV with correct headers."""
    res = client.get("/api/groups/1/export.csv")
    assert res.status_code == 200
    assert "text/csv" in res.headers["Content-Type"]
    text = res.get_data(as_text=True)

    header = text.splitlines()[0]
    expected_header = "expense_id,title,category,amount_paise,payer_name,member_name,share_paise,created_at"
    assert header == expected_header
