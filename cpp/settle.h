/*
 * settle.h  –  Public interface for the Innov8 debt-simplification library
 *
 * WHY extern "C"?
 *   C++ compilers do "name mangling" – they rename functions to encode
 *   parameter types (e.g. settle → _Z6settlePllliS_S_S_i).
 *   Python's ctypes cannot find a mangled name.
 *   extern "C" tells the compiler to use a plain C-style name so ctypes
 *   can locate the function by its exact name "settle".
 */

#ifndef SETTLE_H
#define SETTLE_H

#ifdef __cplusplus
extern "C" {
#endif

/*
 * settle() – Greedy minimum-transaction debt simplification
 *
 * ALGORITHM:
 *   1. Separate members into CREDITORS (net > 0, they are owed money)
 *      and DEBTORS (net < 0, they owe money).
 *   2. Use a max-heap for both groups (largest first).
 *   3. Repeat until one heap is empty:
 *      a. Pop the largest creditor  (most owed)  and largest debtor (most owing).
 *      b. Transfer = min(credit, debt).
 *      c. Record the transaction (debtor → creditor, amount = transfer).
 *      d. If any remainder exists, push it back onto the appropriate heap.
 *   4. Each iteration eliminates at least one person, so at most (n-1)
 *      transactions are ever needed for n people.
 *
 * PARAMETERS (all arrays must be pre-allocated by the caller):
 *   member_ids  – array of n member IDs (integers)
 *   net_paise   – net balance per member in paise
 *                 positive → this person is owed money
 *                 negative → this person owes money
 *   n           – number of members
 *   out_from    – [OUTPUT] array: from-member IDs  (the payer)
 *   out_to      – [OUTPUT] array: to-member IDs    (the receiver)
 *   out_amount  – [OUTPUT] array: transfer amounts in paise
 *   max_out     – maximum entries to write to output arrays
 *
 * RETURNS:
 *   Number of transactions written (0 if already settled).
 */
int settle(
    long long* member_ids,
    long long* net_paise,
    int        n,
    long long* out_from,
    long long* out_to,
    long long* out_amount,
    int        max_out
);

#ifdef __cplusplus
}
#endif

#endif /* SETTLE_H */
