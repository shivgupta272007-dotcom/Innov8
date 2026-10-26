/*
 * validate_csv.c – Innov8 CSV Expense Validator CLI
 * ==================================================
 * Purpose:
 *   This standalone CLI tool parses and validates an exported CSV of expenses
 *   from Innov8 to ensure cryptographic & financial integrity:
 *     1. All individual splits for an expense must sum up to the total expense amount.
 *     2. Total group expenditure matches the sum of distinct expense amounts.
 *     3. Each member's net balance is computed: Net = Total Paid - Total Owed.
 *     4. Conservation of Money invariant: The sum of all members' net balances
 *        MUST BE EXACTLY ZERO.
 *
 * Compilation:
 *   gcc -std=c99 -Wall -Wextra -O2 validate_csv.c -o validate_csv
 *
 * Usage:
 *   ./validate_csv <path_to_exported_expenses.csv>
 *
 * Why C?
 *   - Direct memory management and low overhead.
 *   - Demonstrates multi-language systems interoperability (Python/C++/C/Java)
 *     sharing the exact same domain data model and financial invariants.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdbool.h>

#define MAX_LINE_LEN    1024
#define MAX_MEMBERS     64
#define MAX_EXPENSES    256
#define MAX_NAME_LEN    64
#define MAX_TITLE_LEN   128

/* Structure representing each distinct member and their financial standing */
typedef struct {
    char name[MAX_NAME_LEN];
    long long paid_paise;   /* Total money paid out by this member */
    long long owed_paise;   /* Total share owed by this member */
    long long net_paise;    /* net = paid - owed */
} MemberSummary;

/* Structure tracking each distinct expense to verify its split totals */
typedef struct {
    long long expense_id;
    char title[MAX_TITLE_LEN];
    char payer_name[MAX_NAME_LEN];
    long long amount_paise;
    long long recorded_split_sum; /* Sum of individual split shares */
    int split_count;
} ExpenseCheck;

/* Helper: format paise (integer) into Indian Rupees (₹X.XX) */
static void format_rupees(long long paise, char *out_buf, size_t buf_size) {
    long long abs_paise = (paise < 0) ? -paise : paise;
    long long rupees = abs_paise / 100;
    long long remainder = abs_paise % 100;

    if (paise < 0) {
        snprintf(out_buf, buf_size, "-Rs. %lld.%02lld", rupees, remainder);
    } else {
        snprintf(out_buf, buf_size, " Rs. %lld.%02lld", rupees, remainder);
    }
}

/* Helper: find or insert a member in our members array */
static int get_or_create_member(MemberSummary members[], int *num_members, const char *name) {
    for (int i = 0; i < *num_members; i++) {
        if (strcmp(members[i].name, name) == 0) {
            return i;
        }
    }
    if (*num_members >= MAX_MEMBERS) {
        fprintf(stderr, "Error: Exceeded maximum members capacity (%d)\n", MAX_MEMBERS);
        exit(1);
    }
    int idx = *num_members;
    strncpy(members[idx].name, name, MAX_NAME_LEN - 1);
    members[idx].name[MAX_NAME_LEN - 1] = '\0';
    members[idx].paid_paise = 0;
    members[idx].owed_paise = 0;
    members[idx].net_paise = 0;
    (*num_members)++;
    return idx;
}

/* Helper: find or insert an expense in our expenses array */
static int get_or_create_expense(ExpenseCheck expenses[], int *num_expenses,
                                 long long exp_id, const char *title,
                                 const char *payer_name, long long amount_paise) {
    for (int i = 0; i < *num_expenses; i++) {
        if (expenses[i].expense_id == exp_id) {
            return i;
        }
    }
    if (*num_expenses >= MAX_EXPENSES) {
        fprintf(stderr, "Error: Exceeded maximum expenses capacity (%d)\n", MAX_EXPENSES);
        exit(1);
    }
    int idx = *num_expenses;
    expenses[idx].expense_id = exp_id;
    strncpy(expenses[idx].title, title, MAX_TITLE_LEN - 1);
    expenses[idx].title[MAX_TITLE_LEN - 1] = '\0';
    strncpy(expenses[idx].payer_name, payer_name, MAX_NAME_LEN - 1);
    expenses[idx].payer_name[MAX_NAME_LEN - 1] = '\0';
    expenses[idx].amount_paise = amount_paise;
    expenses[idx].recorded_split_sum = 0;
    expenses[idx].split_count = 0;
    (*num_expenses)++;
    return idx;
}

/* Helper: simple CSV tokenizer that handles basic commas */
static bool parse_csv_line(char *line, char *fields[], int expected_fields) {
    int field_idx = 0;
    char *ptr = line;
    fields[field_idx++] = ptr;

    while (*ptr && field_idx < expected_fields) {
        if (*ptr == ',') {
            *ptr = '\0';
            fields[field_idx++] = ptr + 1;
        }
        ptr++;
    }

    /* Strip trailing newline characters from last field */
    if (field_idx == expected_fields) {
        char *end = fields[expected_fields - 1] + strlen(fields[expected_fields - 1]) - 1;
        while (end >= fields[expected_fields - 1] && (*end == '\r' || *end == '\n' || *end == ' ')) {
            *end = '\0';
            end--;
        }
        return true;
    }
    return false;
}

int main(int argc, char *argv[]) {
    if (argc < 2) {
        fprintf(stderr, "Usage: %s <expenses.csv>\n", argv[0]);
        fprintf(stderr, "Example: %s ../export.csv\n", argv[0]);
        return 1;
    }

    const char *csv_filepath = argv[1];
    FILE *fp = fopen(csv_filepath, "r");
    if (!fp) {
        fprintf(stderr, "Error: Unable to open CSV file '%s'\n", csv_filepath);
        return 1;
    }

    MemberSummary members[MAX_MEMBERS];
    int num_members = 0;

    ExpenseCheck expenses[MAX_EXPENSES];
    int num_expenses = 0;

    char line[MAX_LINE_LEN];
    int line_number = 0;
    long long rows_parsed = 0;

    /*
     * Expected CSV Header:
     * expense_id,title,category,amount_paise,payer_name,member_name,share_paise,created_at
     * (8 fields)
     */
    while (fgets(line, sizeof(line), fp)) {
        line_number++;
        if (line_number == 1) {
            /* Skip header row */
            continue;
        }

        /* Skip empty lines */
        if (strlen(line) <= 1) continue;

        char *fields[8];
        if (!parse_csv_line(line, fields, 8)) {
            fprintf(stderr, "Warning: Malformed line %d in CSV, skipping.\n", line_number);
            continue;
        }

        long long exp_id       = atoll(fields[0]);
        char *title            = fields[1];
        /* fields[2] = category */
        long long amount_paise = atoll(fields[3]);
        char *payer_name       = fields[4];
        char *member_name      = fields[5];
        long long share_paise  = atoll(fields[6]);

        /* Track distinct expense and split sums */
        int exp_idx = get_or_create_expense(expenses, &num_expenses, exp_id, title, payer_name, amount_paise);
        expenses[exp_idx].recorded_split_sum += share_paise;
        expenses[exp_idx].split_count++;

        /* Track member owed amount */
        int member_idx = get_or_create_member(members, &num_members, member_name);
        members[member_idx].owed_paise += share_paise;

        rows_parsed++;
    }

    fclose(fp);

    if (num_expenses == 0 || num_members == 0) {
        printf("No valid expense records found in CSV file.\n");
        return 0;
    }

    /*
     * Compute Total Paid per member:
     * Each unique expense was paid by its stated payer_name.
     */
    long long total_group_spend_paise = 0;
    for (int i = 0; i < num_expenses; i++) {
        total_group_spend_paise += expenses[i].amount_paise;
        int payer_idx = get_or_create_member(members, &num_members, expenses[i].payer_name);
        members[payer_idx].paid_paise += expenses[i].amount_paise;
    }

    /* Compute Net Balance = Paid - Owed for each member */
    long long net_balances_sum_paise = 0;
    for (int i = 0; i < num_members; i++) {
        members[i].net_paise = members[i].paid_paise - members[i].owed_paise;
        net_balances_sum_paise += members[i].net_paise;
    }

    /* ════════════════════════════════════════════════════════════
     * VALIDATION & REPORT GENERATION
     * ════════════════════════════════════════════════════════════ */
    char buf1[64], buf2[64], buf3[64];

    printf("\n");
    printf("========================================================================\n");
    printf("           INNOV8 CSV FINANCIAL AUDIT & VALIDATION REPORT              \n");
    printf("========================================================================\n");
    printf(" File Audited: %s\n", csv_filepath);
    printf(" Rows Parsed : %lld split records across %d distinct expenses\n", rows_parsed, num_expenses);
    printf(" Member Count: %d active group participants\n", num_members);

    format_rupees(total_group_spend_paise, buf1, sizeof(buf1));
    long long per_head_paise = total_group_spend_paise / num_members;
    format_rupees(per_head_paise, buf2, sizeof(buf2));

    printf(" Total Spend : %s (%lld paise)\n", buf1, total_group_spend_paise);
    printf(" Per-Head    : %s (%lld paise)\n", buf2, per_head_paise);
    printf("------------------------------------------------------------------------\n\n");

    /* CHECK 1: Individual Expense Split Integrity */
    printf("--- [CHECK 1] Expense Split Sum Integrity ---\n");
    bool all_splits_valid = true;
    for (int i = 0; i < num_expenses; i++) {
        bool matches = (expenses[i].amount_paise == expenses[i].recorded_split_sum);
        if (!matches) all_splits_valid = false;

        format_rupees(expenses[i].amount_paise, buf1, sizeof(buf1));
        format_rupees(expenses[i].recorded_split_sum, buf2, sizeof(buf2));

        printf("  Expense #%-2lld [%-12s] Paid by: %-10s | Total: %s | Splits Sum: %s [%s]\n",
               expenses[i].expense_id,
               expenses[i].title,
               expenses[i].payer_name,
               buf1,
               buf2,
               matches ? "PASS" : "FAIL MISMATCH");
    }

    /* CHECK 2: Member Ledger & Net Balances */
    printf("\n--- [CHECK 2] Member Ledger & Net Balances (Net = Paid - Owed) ---\n");
    printf(" %-16s | %-16s | %-16s | %-16s\n", "Member Name", "Total Paid", "Total Owed", "Net Balance");
    printf(" -----------------+------------------+------------------+------------------\n");

    for (int i = 0; i < num_members; i++) {
        format_rupees(members[i].paid_paise, buf1, sizeof(buf1));
        format_rupees(members[i].owed_paise, buf2, sizeof(buf2));
        format_rupees(members[i].net_paise, buf3, sizeof(buf3));

        printf(" %-16s | %-16s | %-16s | %-16s\n",
               members[i].name, buf1, buf2, buf3);
    }
    printf(" -----------------+------------------+------------------+------------------\n");

    format_rupees(net_balances_sum_paise, buf1, sizeof(buf1));
    printf(" Net Balances Sum: %s (%lld paise)\n", buf1, net_balances_sum_paise);

    /* VERIFICATION SUMMARY */
    printf("\n========================================================================\n");
    printf("                            AUDIT SUMMARY                              \n");
    printf("========================================================================\n");

    bool split_check_passed   = all_splits_valid;
    bool balance_check_passed = (net_balances_sum_paise == 0);

    printf("  [1] All Expense Splits Match Stated Total : %s\n",
           split_check_passed ? "PASS (Exact Match)" : "FAIL (Mismatch detected)");
    printf("  [2] Conservation of Money (Sum of Nets=0) : %s\n",
           balance_check_passed ? "PASS (Sum is 0 paise)" : "FAIL (Non-zero sum)");

    bool overall_valid = split_check_passed && balance_check_passed;
    printf("\n  OVERALL CSV INTEGRITY VERDICT: %s\n",
           overall_valid ? ">>> VALID (Audit Passed) <<<" : ">>> INVALID (Integrity Violated) <<<");
    printf("========================================================================\n\n");

    return overall_valid ? 0 : 1;
}
