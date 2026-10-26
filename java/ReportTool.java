/*
 * ReportTool.java – Innov8 Java JDBC Expense Reporting Tool
 * ==========================================================
 * Purpose:
 *   This CLI report tool demonstrates database interoperability:
 *   it reads the SAME SQLite database (innov8.db) created by Python/Flask
 *   using Java Database Connectivity (JDBC).
 *
 * Concepts to explain in a Viva:
 *   1. JDBC (Java Database Connectivity):
 *      - Java's standard API for connecting and executing queries against
 *        relational databases.
 *      - Architecture: Your Code -> JDBC API (java.sql.*) -> JDBC Driver (sqlite-jdbc.jar) -> Database.
 *
 *   2. DriverManager.getConnection("jdbc:sqlite:innov8.db"):
 *      - Establishes a database connection using the SQLite JDBC driver URL.
 *
 *   3. PreparedStatement vs Statement:
 *      - PreparedStatement uses pre-compiled SQL queries with placeholders (?)
 *      - Immunizes the application against SQL Injection attacks.
 *
 *   4. ResultSet:
 *      - A cursor pointing to table rows returned by an executed SQL query.
 *      - Use rs.next() to advance row-by-row and rs.getLong("column") to extract values.
 *
 *   5. Try-with-resources:
 *      - Automatically closes Connections, Statements, and ResultSets
 *        even if an exception occurs, avoiding memory / file lock leaks.
 *
 * Compilation & Execution:
 *   Linux / macOS:
 *     javac -cp "lib/*:." ReportTool.java
 *     java  -cp "lib/*:." ReportTool [groupId] [dbPath]
 *
 *   Windows (Command Prompt):
 *     javac -cp "lib/*;." ReportTool.java
 *     java  -cp "lib/*;." ReportTool [groupId] [dbPath]
 */

import java.io.File;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Statement;
import java.util.ArrayList;
import java.util.List;

public class ReportTool {

    // Default paths relative to the Innov8/java directory
    private static final String DEFAULT_DB_PATH = "../backend/innov8.db";

    /**
     * Helper method to convert integer paise into formatted Rupee string.
     * Example: 240000 paise -> "Rs. 2400.00"
     */
    private static String formatRupees(long paise) {
        long absPaise = Math.abs(paise);
        long rupees = absPaise / 100;
        long cents = absPaise % 100;
        String sign = (paise < 0) ? "-" : " ";
        return String.format("%sRs. %d.%02d", sign, rupees, cents);
    }

    /**
     * Prints a list of all existing groups in the database if no specific
     * group ID is passed.
     */
    private static void listGroups(Connection conn) throws SQLException {
        String sql = "SELECT id, name, created_at FROM groups ORDER BY id ASC";
        try (Statement stmt = conn.createStatement();
             ResultSet rs = stmt.executeQuery(sql)) {

            System.out.println("\nAvailable Groups in Database:");
            System.out.println("--------------------------------------------------");
            System.out.printf(" %-6s | %-24s | %-16s\n", "ID", "Group Name", "Created At");
            System.out.println("-------+--------------------------+---------------");

            boolean found = false;
            while (rs.next()) {
                found = true;
                System.out.printf(" %-6d | %-24s | %-16s\n",
                        rs.getInt("id"),
                        rs.getString("name"),
                        rs.getString("created_at"));
            }

            if (!found) {
                System.out.println(" (No groups found. Please seed the database first)");
            }
            System.out.println("--------------------------------------------------\n");
        }
    }

    /**
     * Generates a comprehensive audit report for a specific group.
     */
    private static void generateGroupReport(Connection conn, int groupId) throws SQLException {
        // 1. Fetch Group Details
        String groupName = null;
        String createdAt = null;
        String groupSql = "SELECT name, created_at FROM groups WHERE id = ?";
        try (PreparedStatement pstmt = conn.prepareStatement(groupSql)) {
            pstmt.setInt(1, groupId);
            try (ResultSet rs = pstmt.executeQuery()) {
                if (rs.next()) {
                    groupName = rs.getString("name");
                    createdAt = rs.getString("created_at");
                } else {
                    System.err.printf("Error: Group with ID %d does not exist.\n", groupId);
                    return;
                }
            }
        }

        // 2. Fetch Group Total Spend and Member Count
        long totalSpendPaise = 0;
        int memberCount = 0;

        String totalSql = "SELECT COALESCE(SUM(amount_paise), 0) AS total FROM expenses WHERE group_id = ?";
        try (PreparedStatement pstmt = conn.prepareStatement(totalSql)) {
            pstmt.setInt(1, groupId);
            try (ResultSet rs = pstmt.executeQuery()) {
                if (rs.next()) {
                    totalSpendPaise = rs.getLong("total");
                }
            }
        }

        String countSql = "SELECT COUNT(*) AS cnt FROM members WHERE group_id = ?";
        try (PreparedStatement pstmt = conn.prepareStatement(countSql)) {
            pstmt.setInt(1, groupId);
            try (ResultSet rs = pstmt.executeQuery()) {
                if (rs.next()) {
                    memberCount = rs.getInt("cnt");
                }
            }
        }

        long perHeadPaise = (memberCount > 0) ? (totalSpendPaise / memberCount) : 0;

        // Print Report Header
        System.out.println("\n================================================================================");
        System.out.println("                 INNOV8 EXPENSE MANAGER – JDBC AUDIT REPORT                    ");
        System.out.println("================================================================================");
        System.out.printf(" Group Name    : %s (ID: %d)\n", groupName, groupId);
        System.out.printf(" Created At    : %s\n", createdAt);
        System.out.printf(" Total Spend   : %s (%d paise)\n", formatRupees(totalSpendPaise), totalSpendPaise);
        System.out.printf(" Total Members : %d\n", memberCount);
        System.out.printf(" Per-Head Share: %s (%d paise)\n", formatRupees(perHeadPaise), perHeadPaise);
        System.out.println("--------------------------------------------------------------------------------");

        // 3. Category Breakdown
        System.out.println("\n[SECTION 1] SPENDING BY CATEGORY");
        System.out.println("------------------------------------------------------------------");
        System.out.printf(" %-18s | %-16s | %-12s\n", "Category", "Amount", "% of Total");
        System.out.println("-------------------+------------------+-------------");

        String catSql = "SELECT category, SUM(amount_paise) as cat_total " +
                        "FROM expenses WHERE group_id = ? GROUP BY category ORDER BY cat_total DESC";
        try (PreparedStatement pstmt = conn.prepareStatement(catSql)) {
            pstmt.setInt(1, groupId);
            try (ResultSet rs = pstmt.executeQuery()) {
                while (rs.next()) {
                    long catPaise = rs.getLong("cat_total");
                    double pct = (totalSpendPaise > 0) ? (catPaise * 100.0 / totalSpendPaise) : 0.0;
                    System.out.printf(" %-18s | %-16s | %6.2f%%\n",
                            rs.getString("category"),
                            formatRupees(catPaise),
                            pct);
                }
            }
        }

        // 4. Detailed Expense Log
        System.out.println("\n[SECTION 2] DETAILED EXPENSE LOG");
        System.out.println("------------------------------------------------------------------");
        System.out.printf(" %-4s | %-16s | %-12s | %-14s | %-12s\n",
                "ID", "Title", "Category", "Amount", "Paid By");
        System.out.println("------+------------------+--------------+----------------+--------------");

        String expSql = "SELECT e.id, e.title, e.category, e.amount_paise, m.name AS payer_name " +
                        "FROM expenses e JOIN members m ON e.payer_id = m.id " +
                        "WHERE e.group_id = ? ORDER BY e.id ASC";
        try (PreparedStatement pstmt = conn.prepareStatement(expSql)) {
            pstmt.setInt(1, groupId);
            try (ResultSet rs = pstmt.executeQuery()) {
                while (rs.next()) {
                    System.out.printf(" %-4d | %-16s | %-12s | %-14s | %-12s\n",
                            rs.getInt("id"),
                            rs.getString("title"),
                            rs.getString("category"),
                            formatRupees(rs.getLong("amount_paise")),
                            rs.getString("payer_name"));
                }
            }
        }

        // 5. Member Financial Ledger (Paid, Owed, Net)
        System.out.println("\n[SECTION 3] MEMBER BALANCES LEDGER");
        System.out.println("------------------------------------------------------------------");
        System.out.printf(" %-14s | %-14s | %-14s | %-14s | %-12s\n",
                "Member Name", "Total Paid", "Total Owed", "Net Balance", "Standing");
        System.out.println("---------------+----------------+----------------+----------------+-------------");

        String memSql = "SELECT id, name, upi_id FROM members WHERE group_id = ? ORDER BY id ASC";
        long sumNetBalancesPaise = 0;

        try (PreparedStatement pstmt = conn.prepareStatement(memSql)) {
            pstmt.setInt(1, groupId);
            try (ResultSet rs = pstmt.executeQuery()) {
                while (rs.next()) {
                    int memberId = rs.getInt("id");
                    String memberName = rs.getString("name");

                    // Compute Paid
                    long paidPaise = 0;
                    String paidSql = "SELECT COALESCE(SUM(amount_paise), 0) FROM expenses WHERE payer_id = ? AND group_id = ?";
                    try (PreparedStatement paidPstmt = conn.prepareStatement(paidSql)) {
                        paidPstmt.setInt(1, memberId);
                        paidPstmt.setInt(2, groupId);
                        try (ResultSet paidRs = paidPstmt.executeQuery()) {
                            if (paidRs.next()) paidPaise = paidRs.getLong(1);
                        }
                    }

                    // Compute Owed (sum of splits in this group)
                    long owedPaise = 0;
                    String owedSql = "SELECT COALESCE(SUM(s.share_paise), 0) FROM expense_splits s " +
                                     "JOIN expenses e ON s.expense_id = e.id WHERE s.member_id = ? AND e.group_id = ?";
                    try (PreparedStatement owedPstmt = conn.prepareStatement(owedSql)) {
                        owedPstmt.setInt(1, memberId);
                        owedPstmt.setInt(2, groupId);
                        try (ResultSet owedRs = owedPstmt.executeQuery()) {
                            if (owedRs.next()) owedPaise = owedRs.getLong(1);
                        }
                    }

                    long netPaise = paidPaise - owedPaise;
                    sumNetBalancesPaise += netPaise;

                    String standing = (netPaise > 0) ? "GETS BACK" : (netPaise < 0 ? "OWES MONEY" : "SETTLED");
                    System.out.printf(" %-14s | %-14s | %-14s | %-14s | %-12s\n",
                            memberName,
                            formatRupees(paidPaise),
                            formatRupees(owedPaise),
                            formatRupees(netPaise),
                            standing);
                }
            }
        }
        System.out.println("---------------+----------------+----------------+----------------+-------------");
        System.out.printf(" Net Balances Sum Check: %s (%d paise)\n",
                formatRupees(sumNetBalancesPaise), sumNetBalancesPaise);

        // 6. Current Settlements
        System.out.println("\n[SECTION 4] DEBT SIMPLIFICATION SETTLEMENT TRANSFERS");
        System.out.println("------------------------------------------------------------------");
        System.out.printf(" %-14s -> %-14s | %-14s | %-10s\n", "Debtor (From)", "Creditor (To)", "Amount", "Status");
        System.out.println("----------------+----------------+----------------+-----------");

        String setSql = "SELECT f.name AS from_name, t.name AS to_name, s.amount_paise, s.status " +
                        "FROM settlements s " +
                        "JOIN members f ON s.from_member = f.id " +
                        "JOIN members t ON s.to_member = t.id " +
                        "WHERE s.group_id = ? ORDER BY s.id ASC";
        try (PreparedStatement pstmt = conn.prepareStatement(setSql)) {
            pstmt.setInt(1, groupId);
            try (ResultSet rs = pstmt.executeQuery()) {
                boolean hasSettlements = false;
                while (rs.next()) {
                    hasSettlements = true;
                    System.out.printf(" %-14s -> %-14s | %-14s | %-10s\n",
                            rs.getString("from_name"),
                            rs.getString("to_name"),
                            formatRupees(rs.getLong("amount_paise")),
                            rs.getString("status").toUpperCase());
                }
                if (!hasSettlements) {
                    System.out.println(" (No settlement plan recorded yet in DB)");
                }
            }
        }

        // 7. Integrity Audit Summary
        System.out.println("\n================================================================================");
        System.out.println("                         DATABASE INTEGRITY AUDIT                               ");
        System.out.println("================================================================================");
        boolean sumZero = (sumNetBalancesPaise == 0);
        System.out.printf("  Conservation of Money Check : %s (Sum = %d paise)\n",
                sumZero ? "PASS" : "FAIL", sumNetBalancesPaise);
        System.out.println("================================================================================\n");
    }

    public static void main(String[] args) {
        int targetGroupId = 1; // Default to Group 1 (Goa Trip)
        String dbPath = DEFAULT_DB_PATH;

        if (args.length >= 1) {
            try {
                targetGroupId = Integer.parseInt(args[0]);
            } catch (NumberFormatException e) {
                System.err.println("Warning: Invalid groupId argument. Using default group 1.");
            }
        }
        if (args.length >= 2) {
            dbPath = args[1];
        }

        File dbFile = new File(dbPath);
        if (!dbFile.exists()) {
            System.err.printf("Error: Database file '%s' was not found.\n", dbFile.getAbsolutePath());
            System.err.println("Please run 'python3 db.py' inside Innov8/backend first to initialize the database.");
            System.exit(1);
        }

        String jdbcUrl = "jdbc:sqlite:" + dbFile.getAbsolutePath();

        System.out.println("Connecting to Innov8 Database via JDBC...");
        System.out.println("JDBC URL: " + jdbcUrl);

        try {
            // Optional: explicit driver class load for legacy Java runtimes
            Class.forName("org.sqlite.JDBC");
        } catch (ClassNotFoundException e) {
            System.err.println("Warning: SQLite JDBC Driver class not found in classpath. Ensure sqlite-jdbc.jar is included.");
        }

        try (Connection conn = DriverManager.getConnection(jdbcUrl)) {
            // Display all available groups for reference
            listGroups(conn);

            // Generate detailed report for target group
            generateGroupReport(conn, targetGroupId);

        } catch (SQLException e) {
            System.err.println("Database error occurred: " + e.getMessage());
            e.printStackTrace();
            System.exit(1);
        }
    }
}
