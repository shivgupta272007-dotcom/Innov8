"""
settlements.py  –  Debt simplification: C++ library via ctypes, with Python fallback
======================================================================================

HOW ctypes WORKS (for viva):
  ctypes is a Python standard library module that lets Python call functions
  compiled in C or C++ shared libraries (.so on Linux/macOS, .dll on Windows).

  Steps:
    1.  ctypes.CDLL("settle.so")  →  loads the shared library into memory.
    2.  We tell ctypes the function's parameter types (argtypes) and return type.
    3.  We create C-style arrays using ctypes array types and pass their pointers.
    4.  The C++ function writes results into those arrays; Python reads them back.

FALLBACK:
  If the .so / .dll is missing (e.g., compiler not installed), we run the same
  greedy algorithm in pure Python using the heapq module.
  Python's heapq is a MIN-heap; to simulate a max-heap, we store negatives.

MONEY:
  Everything is in integer PAISE throughout this module.
"""

import ctypes
import heapq
import os
import sys
from typing import Optional

# ── Locate the shared library ─────────────────────────────────────────────
_BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
_CPP_DIR   = os.path.join(_BASE_DIR, "..", "cpp")

# Library filename differs by OS
if sys.platform == "win32":
    _LIB_NAME = "settle.dll"
else:
    _LIB_NAME = "settle.so"

_LIB_PATH = os.path.join(_CPP_DIR, _LIB_NAME)

# ── Try loading the C++ library ───────────────────────────────────────────
_lib: Optional[ctypes.CDLL] = None

try:
    _lib = ctypes.CDLL(_LIB_PATH)

    # Tell ctypes the types of settle()'s parameters (must match settle.h)
    # c_longlong = 64-bit signed integer = C's long long
    # POINTER(c_longlong) = long long* (pointer to array)
    _lib.settle.argtypes = [
        ctypes.POINTER(ctypes.c_longlong),  # member_ids[]
        ctypes.POINTER(ctypes.c_longlong),  # net_paise[]
        ctypes.c_int,                        # n (count)
        ctypes.POINTER(ctypes.c_longlong),  # out_from[]
        ctypes.POINTER(ctypes.c_longlong),  # out_to[]
        ctypes.POINTER(ctypes.c_longlong),  # out_amount[]
        ctypes.c_int,                        # max_out
    ]
    _lib.settle.restype = ctypes.c_int       # return type: int (transaction count)

    print("[settle] C++ library loaded:", _LIB_PATH)

except OSError as e:
    print(f"[settle] WARNING – C++ library not found ({e}).")
    print("[settle] Using pure-Python fallback (same algorithm, heapq).")
    _lib = None


# ══════════════════════════════════════════════════════════════════════════
# PURE-PYTHON FALLBACK  (identical algorithm to C++)
# ══════════════════════════════════════════════════════════════════════════

def _python_settle(net_balances: dict) -> list[dict]:
    """
    Greedy debt simplification using Python's heapq (min-heap).

    net_balances: {member_id: net_paise}
      positive  → this member is owed money (creditor)
      negative  → this member owes money     (debtor)

    Returns: list of {"from_id":…, "to_id":…, "amount_paise":…}

    MIN-HEAP TRICK:
      Python's heapq gives the SMALLEST element first.
      To get the LARGEST, we negate all values before inserting,
      then negate again when we pop.
    """
    # Build max-heaps (stored as negatives for heapq)
    creditors = []   # (-credit_paise, member_id)
    debtors   = []   # (-debt_paise,   member_id)

    for mid, net in net_balances.items():
        if net > 0:
            heapq.heappush(creditors, (-net, mid))    # negate → max on top
        elif net < 0:
            heapq.heappush(debtors, (net, mid))       # already negative → min = most negative = largest debt

    transactions = []

    while creditors and debtors:
        neg_credit, credit_id = heapq.heappop(creditors)   # most owed
        neg_debt,   debt_id   = heapq.heappop(debtors)     # most owing

        credit_amt = -neg_credit    # restore positive
        debt_amt   = -neg_debt      # restore positive

        transfer = min(credit_amt, debt_amt)

        transactions.append({
            "from_id":      debt_id,
            "to_id":        credit_id,
            "amount_paise": transfer
        })

        # Push back any remainder
        if credit_amt > transfer:
            heapq.heappush(creditors, (-(credit_amt - transfer), credit_id))
        if debt_amt > transfer:
            heapq.heappush(debtors, (-(debt_amt - transfer), debt_id))

    return transactions


# ══════════════════════════════════════════════════════════════════════════
# C++ WRAPPER
# ══════════════════════════════════════════════════════════════════════════

def _cpp_settle(net_balances: dict) -> list[dict]:
    """
    Call the C++ settle() function via ctypes.

    net_balances: {member_id: net_paise}

    HOW ctypes ARRAYS WORK:
      (ctypes.c_longlong * n)()  creates a C-style array of n long longs.
      We fill it with Python values, then pass it to the C++ function.
      The function fills out_from/out_to/out_amount with results.
    """
    ids  = list(net_balances.keys())
    nets = list(net_balances.values())
    n    = len(ids)

    if n == 0:
        return []

    # Create C arrays of size n for input
    ArrType = ctypes.c_longlong * n
    c_ids   = ArrType(*ids)
    c_nets  = ArrType(*nets)

    # Output arrays: worst case n-1 transactions
    max_out   = max(n - 1, 1)
    OutType   = ctypes.c_longlong * max_out
    c_from    = OutType()
    c_to      = OutType()
    c_amounts = OutType()

    # Call the C++ function
    count = _lib.settle(c_ids, c_nets, n, c_from, c_to, c_amounts, max_out)

    # Read results back from C arrays into Python list
    transactions = []
    for i in range(count):
        transactions.append({
            "from_id":      c_from[i],
            "to_id":        c_to[i],
            "amount_paise": c_amounts[i]
        })

    return transactions


# ══════════════════════════════════════════════════════════════════════════
# PUBLIC FUNCTION
# ══════════════════════════════════════════════════════════════════════════

def compute_settlements(net_balances: dict) -> list[dict]:
    """
    Given a dict of {member_id: net_paise}, returns a minimal list of
    transfers needed to settle all debts.

    Automatically uses C++ library if available; falls back to Python.

    Example:
      net_balances = {1: 35500, 2: -19100, 3: -16400}
      → [{from_id: 2, to_id: 1, amount_paise: 19100},
         {from_id: 3, to_id: 1, amount_paise: 16400}]
    """
    if _lib is not None:
        return _cpp_settle(net_balances)
    else:
        return _python_settle(net_balances)


# ══════════════════════════════════════════════════════════════════════════
# SELF-TEST (5 test cases – run with: python3 settlements.py)
# ══════════════════════════════════════════════════════════════════════════

def _run_tests():
    """
    5 test cases that validate the settle algorithm.
    Each case prints expected vs actual and PASS/FAIL.
    """
    print("\n" + "="*60)
    print("  Innov8 Settlement Algorithm – 5 Test Cases")
    print("="*60)

    tests = [
        # ── Test 1: Simplest case – two people ─────────────────────
        {
            "name": "T1: Two people (A paid for B)",
            "input": {1: 50000, 2: -50000},       # A: +₹500, B: -₹500
            "expected_txns": 1,
            "expected_sum":  0,
        },

        # ── Test 2: One payer, three owing ──────────────────────────
        {
            "name": "T2: One payer, three borrowers",
            "input": {1: 300000, 2: -100000, 3: -100000, 4: -100000},
            "expected_txns": 3,
            "expected_sum":  0,
        },

        # ── Test 3: Multiple creditors and debtors ──────────────────
        # Goa Trip actual balances (from Stage 2 live output):
        # Shivansh: +355000, Shubh: -5000, Shiv: -159000, Shubham: -191000
        {
            "name": "T3: Goa Trip real balances (4 people)",
            "input": {3: 355000, 1: -5000, 2: -159000, 4: -191000},
            "expected_txns": 3,   # at most n-1 = 3
            "expected_sum":  0,
        },

        # ── Test 4: Already settled – all zero ──────────────────────
        {
            "name": "T4: Already settled (all net = 0)",
            "input": {1: 0, 2: 0, 3: 0},
            "expected_txns": 0,
            "expected_sum":  0,
        },

        # ── Test 5: Odd remainder paise distribution ─────────────────
        # 3 people, total = 1001 paise, each owes 333 or 334
        # After equal split: member 1 paid 1001, each owes 334/334/333
        # net: 1: +667, 2: -334, 3: -333
        {
            "name": "T5: Odd paise remainder after 3-way split",
            "input": {1: 667, 2: -334, 3: -333},
            "expected_txns": 2,
            "expected_sum":  0,
        },
    ]

    all_pass = True

    for t in tests:
        result  = compute_settlements(t["input"])
        n_txns  = len(result)

        # Verify net sum of transfers = 0 (money is conserved)
        net_check = sum(t["input"].values())

        # Verify total transferred equals total debt resolved
        total_transferred = sum(r["amount_paise"] for r in result)
        total_positive    = sum(v for v in t["input"].values() if v > 0)

        txns_ok  = (n_txns == t["expected_txns"])
        input_ok = (net_check == 0)          # input must sum to 0
        total_ok = (total_transferred == total_positive)  # transfers cover all debts

        passed   = txns_ok and input_ok and total_ok
        all_pass = all_pass and passed

        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"\n{status}  {t['name']}")
        print(f"       Input net sum: {net_check} paise  (must be 0)")
        print(f"       Transactions:  {n_txns}  (expected {t['expected_txns']})")
        print(f"       Total transferred: {total_transferred} paise  (creditors are owed {total_positive})")
        for r in result:
            rs = f"₹{r['amount_paise']/100:.2f}"
            print(f"         Member {r['from_id']:>2} → Member {r['to_id']:>2} : {rs}")

    print("\n" + "="*60)
    print(f"  Result: {'ALL TESTS PASSED ✅' if all_pass else 'SOME TESTS FAILED ❌'}")
    print("="*60 + "\n")


if __name__ == "__main__":
    _run_tests()
