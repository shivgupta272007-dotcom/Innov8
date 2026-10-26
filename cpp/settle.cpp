/*
 * settle.cpp  –  Greedy debt simplification via two max-heaps
 * ============================================================
 *
 * PROBLEM:
 *   Given n people with net balances (positive = owed money, negative = owes),
 *   find the minimum set of bank transfers to settle all debts.
 *
 * INSIGHT:
 *   At any moment, match the person who is owed the MOST with the person who
 *   OWES the most.  One transaction either fully clears the debtor, the
 *   creditor, or both.  So in at most (n-1) rounds, everyone is settled.
 *
 * DATA STRUCTURES:
 *   std::priority_queue = a max-heap in C++ (largest element on top).
 *   We store {amount, id} pairs so the heap sorts by amount automatically.
 *
 * COMPILE (see build commands in README):
 *   macOS / Linux:  g++ -std=c++17 -shared -fPIC -O2 -o settle.so settle.cpp
 *   Windows:        g++ -std=c++17 -shared -O2 -o settle.dll settle.cpp
 */

#include "settle.h"
#include <queue>       // std::priority_queue
#include <utility>     // std::pair
#include <algorithm>   // std::min

extern "C" {

int settle(
    long long* member_ids,
    long long* net_paise,
    int        n,
    long long* out_from,
    long long* out_to,
    long long* out_amount,
    int        max_out
) {
    /*
     * std::priority_queue<pair<long long, long long>>
     *   is a MAX-heap of (amount, member_id) pairs.
     *   The pair with the LARGEST first element stays on top.
     *
     * We use two separate heaps:
     *   creditors → people with net > 0  (they are owed money)
     *   debtors   → people with net < 0  (they owe money, stored as positive)
     */
    using pll = std::pair<long long, long long>;
    std::priority_queue<pll> creditors;   // (credit_amount, member_id)
    std::priority_queue<pll> debtors;     // (debt_amount,   member_id)  ← stored positive

    /* Step 1 – Populate the two heaps */
    for (int i = 0; i < n; i++) {
        if (net_paise[i] > 0) {
            creditors.push({net_paise[i], member_ids[i]});
        } else if (net_paise[i] < 0) {
            /* Store the debt as a positive number for the max-heap */
            debtors.push({-net_paise[i], member_ids[i]});
        }
        /* net == 0 → already settled, skip */
    }

    int count = 0;   /* number of transactions produced */

    /* Step 2 – Greedily match largest creditor with largest debtor */
    while (!creditors.empty() && !debtors.empty() && count < max_out) {

        /* Pop the person owed the most */
        auto [credit_amt, credit_id] = creditors.top();
        creditors.pop();

        /* Pop the person who owes the most */
        auto [debt_amt, debt_id] = debtors.top();
        debtors.pop();

        /*
         * The actual transfer is the SMALLER of the two.
         *   - If credit > debt → creditor is only partially paid; push remainder.
         *   - If debt > credit → debtor still owes the rest; push remainder.
         *   - If equal        → both are fully settled; push nothing.
         */
        long long transfer = std::min(credit_amt, debt_amt);

        /* Record the transaction */
        out_from[count]   = debt_id;     /* debtor  pays... */
        out_to[count]     = credit_id;   /* ...creditor     */
        out_amount[count] = transfer;
        count++;

        /* Push back any remainder */
        if (credit_amt > transfer) {
            creditors.push({credit_amt - transfer, credit_id});
        }
        if (debt_amt > transfer) {
            debtors.push({debt_amt - transfer, debt_id});
        }
    }

    return count;   /* total number of transactions */
}

} /* extern "C" */
