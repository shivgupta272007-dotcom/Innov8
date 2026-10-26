/**
 * app.js – Innov8 Frontend Logic
 * ================================
 * Single-Page Application (SPA) logic:
 *   - Live state & group selection
 *   - Fetch wrapper for REST API
 *   - Chart.js live analytics with fallback visual bars
 *   - Dynamic category badges & colorful avatars
 *   - 5-second delta chat polling
 *   - UPI QR settlement generator
 *   - XSS sanitization (esc() & textContent)
 */

"use strict";

// ══════════════════════════════════════════════════════════
// 1.  CONSTANTS & APPLICATION STATE
// ══════════════════════════════════════════════════════════

// Dynamic API URL: uses relative "/api" on all domains (Vercel, Cloudflare, LAN, local Flask)
const API = (window.location.port === "5500" || window.location.port === "3000")
  ? "http://localhost:5000/api"
  : "/api";

const state = {
  groupId:         null,
  groupInviteCode: null,
  groupName:       null,
  members:         [],
  lastMessageId:   0,
  chatPollTimer:   null,
  chartMember:     null,
  chartCategory:   null,
};

// ── Local Storage "My Trips" helpers ───────────────────────
function getMyTrips() {
  try {
    return JSON.parse(localStorage.getItem("innov8_my_trips")) || [];
  } catch (e) {
    return [];
  }
}

function saveMyTrip(trip) {
  if (!trip || !trip.id) return;
  let trips = getMyTrips();
  trips = trips.filter(t => t.id !== trip.id && (trip.invite_code ? (t.invite_code || "").toLowerCase() !== trip.invite_code.toLowerCase() : true));
  trips.unshift({
    id:          trip.id,
    name:        trip.name,
    invite_code: trip.invite_code || ""
  });
  localStorage.setItem("innov8_my_trips", JSON.stringify(trips));
}

/** Explicitly remove / leave a trip from this device's saved trips */
function removeTripFromDevice(id) {
  if (!id) return;
  let trips = getMyTrips().filter(t => t.id !== id);
  localStorage.setItem("innov8_my_trips", JSON.stringify(trips));
  if (state.groupId === id) {
    state.groupId = null;
    localStorage.removeItem("innov8_active_group_id");
  }
  loadGroups();
}

/** Local storage cache helpers for members and expenses per trip */
function getCachedMembers(code) {
  if (!code) return [];
  try {
    return JSON.parse(localStorage.getItem(`innov8_members_${code.toLowerCase()}`)) || [];
  } catch (e) {
    return [];
  }
}

function saveCachedMembers(code, members) {
  if (!code || !Array.isArray(members)) return;
  const list = members.map(m => ({ name: m.name, upi_id: m.upi_id || "" }));
  localStorage.setItem(`innov8_members_${code.toLowerCase()}`, JSON.stringify(list));
}

function getCachedExpenses(code) {
  if (!code) return [];
  try {
    return JSON.parse(localStorage.getItem(`innov8_expenses_${code.toLowerCase()}`)) || [];
  } catch (e) {
    return [];
  }
}

function saveCachedExpenses(code, expenses) {
  if (!code || !Array.isArray(expenses)) return;
  const list = expenses.map(e => ({
    title:        e.title,
    amount_paise: e.amount_paise,
    payer_name:   e.payer_name,
    category:     e.category || "General",
    splits:       (e.splits || []).map(s => ({ member_name: s.member_name, share_paise: s.share_paise }))
  }));
  localStorage.setItem(`innov8_expenses_${code.toLowerCase()}`, JSON.stringify(list));
}

// Category emoji icons and colors
const CATEGORY_ICONS = {
  Food:          "🍕",
  Transport:     "🚕",
  Stay:          "🏨",
  Entertainment: "🎟️",
  Shopping:      "🛍️",
  General:       "📦",
};

// Warm Beige and Navy coordinated color palette for charts & visual bars
const VIBRANT_COLORS = [
  "#dfc8a2", // Golden Champagne Beige
  "#56b6f7", // Marine Sky Blue
  "#22c55e", // Mint Green
  "#f59e0b", // Warm Amber
  "#b57edc", // Royal Lilac
  "#fb7185", // Coral Rose
  "#e0b589", // Warm Sand
  "#06b6d4", // Electric Teal
];

// ══════════════════════════════════════════════════════════
// 2.  HELPER FUNCTIONS
// ══════════════════════════════════════════════════════════

/** Escape special characters to prevent Cross-Site Scripting (XSS). */
function esc(str) {
  if (str === null || str === undefined) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

/** Convert integer paise to formatted Indian Rupee string. */
function rupees(paise) {
  const amount = (paise || 0) / 100;
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    minimumFractionDigits: 2,
  }).format(amount);
}

/** API wrapper using native fetch(). */
async function api(path, options = {}) {
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  const response = await fetch(`${API}${path}`, { ...options, headers });

  if (options._raw) return response;

  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || `HTTP ${response.status}`);
  }
  return data;
}

/** Toast notifications. */
function toast(msg, type = "success") {
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.className = `toast ${type}`;
  el.classList.remove("hidden");

  clearTimeout(el._timer);
  el._timer = setTimeout(() => el.classList.add("hidden"), 3200);
}

function openModal(id)  { document.getElementById(id).classList.remove("hidden"); }
function closeModal(id) { document.getElementById(id).classList.add("hidden"); }
function clearErr(id)   { document.getElementById(id).textContent = ""; }
function showErr(id, m) { document.getElementById(id).textContent = m; }

function formatTime(datetimeStr) {
  if (!datetimeStr) return "";
  const d = new Date(datetimeStr.replace(" ", "T") + "Z");
  return d.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" });
}

// ══════════════════════════════════════════════════════════
// 3.  TAB SWITCHING
// ══════════════════════════════════════════════════════════

function switchTab(tabName) {
  document.querySelectorAll(".tab-btn").forEach(btn => btn.classList.remove("active"));
  document.querySelectorAll(".panel").forEach(panel => panel.classList.remove("active"));

  const btn   = document.querySelector(`[data-tab="${tabName}"]`);
  const panel = document.getElementById(`panel-${tabName}`);

  if (btn)   btn.classList.add("active");
  if (panel) panel.classList.add("active");

  if (tabName === "members")   loadMembers();
  if (tabName === "expenses")  loadExpenses();
  if (tabName === "analytics") {
    // Delay slightly to ensure browser finishes rendering tab display:block
    setTimeout(loadAnalytics, 50);
  }
  if (tabName === "chat")      { loadChat(); loadSettlements(); }
}

// ══════════════════════════════════════════════════════════
// 4.  GROUP MANAGEMENT
// ══════════════════════════════════════════════════════════

async function loadGroups() {
  const select = document.getElementById("groupSelect");
  let myTrips = getMyTrips();

  select.innerHTML = `<option value="">— My Trips —</option>`;

  // On first visit ever, auto-seed the demo "Goa Trip" into local storage
  if (!localStorage.getItem("innov8_initialized") && myTrips.length === 0) {
    try {
      const defaultTrip = await api("/groups/join/goa-trip");
      if (defaultTrip && defaultTrip.id) {
        saveMyTrip(defaultTrip);
        myTrips = [defaultTrip];
      }
    } catch (e) {
      // Demo trip fallback
    } finally {
      localStorage.setItem("innov8_initialized", "1");
    }
  }

  // Sync client-side trips with the server instance so any newly spun-up containers
  // immediately register the group, its members, and expenses without 404s
  if (myTrips.length > 0) {
    try {
      const syncPayload = myTrips.map(t => {
        const code = t.invite_code || "";
        return {
          id:          t.id,
          name:        t.name,
          invite_code: code,
          members:     getCachedMembers(code),
          expenses:    getCachedExpenses(code)
        };
      });

      const syncedTrips = await api("/groups/sync", {
        method: "POST",
        body: JSON.stringify({ trips: syncPayload })
      });
      if (Array.isArray(syncedTrips) && syncedTrips.length > 0) {
        // Update trips with live IDs/metadata from server without deleting any trips
        syncedTrips.forEach(st => {
          const idx = myTrips.findIndex(t =>
            (t.invite_code && st.invite_code && t.invite_code.toLowerCase() === st.invite_code.toLowerCase()) ||
            t.id === st.id
          );
          if (idx >= 0) {
            myTrips[idx] = { id: st.id, name: st.name, invite_code: st.invite_code };
          } else {
            myTrips.push({ id: st.id, name: st.name, invite_code: st.invite_code });
          }
          if (st.invite_code && Array.isArray(st.members) && st.members.length > 0) {
            saveCachedMembers(st.invite_code, st.members);
          }
        });
        localStorage.setItem("innov8_my_trips", JSON.stringify(myTrips));
      }
    } catch (e) {
      console.warn("Trip sync note:", e);
    }
  }

  myTrips.forEach(g => {
    const opt = document.createElement("option");
    opt.value = g.id;
    opt.dataset.code = g.invite_code || "";
    opt.dataset.name = g.name;
    opt.textContent = `✈️ ${g.name}`;
    select.appendChild(opt);
  });

  // Restore previously active group from localStorage or default to the newest trip
  const savedActiveId = parseInt(localStorage.getItem("innov8_active_group_id"));
  const targetTrip = (state.groupId && myTrips.find(t => t.id === state.groupId))
    || (savedActiveId && myTrips.find(t => t.id === savedActiveId))
    || (myTrips.length > 0 ? myTrips[0] : null);

  if (targetTrip) {
    select.value = targetTrip.id;
    selectGroup(targetTrip.id);
  } else {
    selectGroup(null);
  }
}

function selectGroup(id) {
  state.groupId       = id ? parseInt(id) : null;
  state.lastMessageId = 0;

  if (state.groupId) {
    localStorage.setItem("innov8_active_group_id", state.groupId);
  } else {
    localStorage.removeItem("innov8_active_group_id");
  }

  // Show or hide "Leave Trip" button based on group selection
  const btnLeave = document.getElementById("btnLeaveTrip");
  if (btnLeave) {
    if (state.groupId) {
      btnLeave.classList.remove("hidden");
    } else {
      btnLeave.classList.add("hidden");
    }
  }

  if (state.chatPollTimer) {
    clearInterval(state.chatPollTimer);
    state.chatPollTimer = null;
  }

  const select = document.getElementById("groupSelect");
  const selectedOption = select.querySelector(`option[value="${id}"]`);
  if (selectedOption) {
    state.groupInviteCode = selectedOption.dataset.code || "";
    state.groupName       = selectedOption.dataset.name || "";
  } else {
    state.groupInviteCode = null;
    state.groupName       = null;
  }

  if (state.groupId) {
    document.getElementById("mainContent").classList.remove("hidden");
    document.getElementById("welcome").classList.add("hidden");

    document.getElementById("btnExportCSV").href =
      `${API}/groups/${state.groupId}/export.csv`;

    const activeTab = document.querySelector(".tab-btn.active")?.dataset.tab || "members";
    switchTab(activeTab);
  } else {
    document.getElementById("mainContent").classList.add("hidden");
    document.getElementById("welcome").classList.remove("hidden");
  }
}

async function createGroup(name) {
  try {
    const group = await api("/groups", {
      method: "POST",
      body: JSON.stringify({ name }),
    });

    saveMyTrip(group);
    localStorage.setItem("innov8_active_group_id", group.id);
    toast(`Trip "${group.name}" created! 🚀`);
    closeModal("modalNewGroup");
    document.getElementById("formNewGroup").reset();

    await loadGroups();
    document.getElementById("groupSelect").value = group.id;
    selectGroup(group.id);
  } catch (e) {
    showErr("errNewGroup", e.message);
  }
}

async function joinTripByCode(codeOrUrl, tripName = null) {
  if (!codeOrUrl) return;
  let code = codeOrUrl.trim();
  let nameFromUrl = tripName;

  // If user pasted a full URL
  if (code.includes("join=") || code.includes("group=") || code.includes("code=")) {
    try {
      const url = new URL(code, window.location.origin);
      code = url.searchParams.get("join") || url.searchParams.get("group") || url.searchParams.get("code") || code;
      if (!nameFromUrl) nameFromUrl = url.searchParams.get("name");
    } catch (e) {
      const m = code.match(/(?:join|group|code)=([a-zA-Z0-9_-]+)/);
      if (m) code = m[1];
    }
  }

  try {
    let group = null;
    try {
      group = await api(`/groups/join/${encodeURIComponent(code)}`);
    } catch (joinErr) {
      // If serverless container cold-started and doesn't have the code yet, sync it with name!
      if (nameFromUrl || code) {
        const synced = await api("/groups/sync", {
          method: "POST",
          body: JSON.stringify({ trips: [{ name: nameFromUrl || "Shared Trip", invite_code: code }] })
        });
        if (Array.isArray(synced) && synced.length > 0) {
          group = synced[0];
        }
      }
      if (!group) throw joinErr;
    }

    saveMyTrip(group);
    localStorage.setItem("innov8_active_group_id", group.id);
    closeModal("modalJoinTrip");
    document.getElementById("formJoinTrip")?.reset();
    toast(`Joined "${group.name}"! 🎉`);

    await loadGroups();
    document.getElementById("groupSelect").value = group.id;
    selectGroup(group.id);
  } catch (e) {
    showErr("errJoinTrip", e.message || "Invalid invite code or group not found.");
    toast(e.message || "Could not join trip", "error");
  }
}

// ══════════════════════════════════════════════════════════
// 5.  MEMBERS PANEL
// ══════════════════════════════════════════════════════════

async function loadMembers() {
  if (!state.groupId) return;

  const list = document.getElementById("membersList");
  list.innerHTML = `<p class="loading-msg">Loading members…</p>`;

  try {
    let summary = await api(`/groups/${state.groupId}/summary`);

    // Self-healing: If server returns 0 members but device has cached members (due to serverless restart):
    const cachedM = state.groupInviteCode ? getCachedMembers(state.groupInviteCode) : [];
    const cachedE = state.groupInviteCode ? getCachedExpenses(state.groupInviteCode) : [];
    if (summary.members.length === 0 && cachedM.length > 0) {
      try {
        await api("/groups/sync", {
          method: "POST",
          body: JSON.stringify({
            trips: [{
              id:          state.groupId,
              name:        state.groupName,
              invite_code: state.groupInviteCode,
              members:     cachedM,
              expenses:    cachedE
            }]
          })
        });
        summary = await api(`/groups/${state.groupId}/summary`);
      } catch (e) {
        console.warn("Member re-hydration attempt:", e);
      }
    }

    state.members = summary.members;
    if (state.groupInviteCode && summary.members.length > 0) {
      saveCachedMembers(state.groupInviteCode, summary.members);
    }

    // Render vivid summary cards with icons
    document.getElementById("summaryCards").innerHTML = `
      <div class="summary-card card-spend">
        <div class="sc-top">
          <span class="sc-label">Total Spend</span>
          <span class="sc-icon">💰</span>
        </div>
        <div class="sc-value">${rupees(summary.total_paise)}</div>
      </div>
      <div class="summary-card card-perhead">
        <div class="sc-top">
          <span class="sc-label">Per-Head Share</span>
          <span class="sc-icon">👤</span>
        </div>
        <div class="sc-value">${rupees(summary.per_head_paise)}</div>
      </div>
      <div class="summary-card card-members">
        <div class="sc-top">
          <span class="sc-label">Active Members</span>
          <span class="sc-icon">👥</span>
        </div>
        <div class="sc-value">${summary.member_count}</div>
      </div>
    `;

    if (!summary.members.length) {
      list.innerHTML = `<p class="empty-msg">No members yet. Click "+ Add Member" to get started!</p>`;
      return;
    }

    list.innerHTML = summary.members.map((m, idx) => {
      const netAbs  = Math.abs(m.net_paise);
      const isPos   = m.net_paise > 0;
      const isNeg   = m.net_paise < 0;

      const netCls  = isPos ? "positive" : isNeg ? "negative" : "zero";
      const netIcon = isPos ? "⬆️" : isNeg ? "⬇️" : "✨";
      const netText = isPos
        ? `Gets back ${rupees(netAbs)}`
        : isNeg
          ? `Owes ${rupees(netAbs)}`
          : "Settled up";

      const gradIndex = idx % 5;

      return `
        <div class="member-card">
          <div class="member-avatar avatar-grad-${gradIndex}">${esc(m.name.charAt(0).toUpperCase())}</div>
          <div class="member-info">
            <div class="member-name">${esc(m.name)}</div>
            <div class="member-upi">
              ${m.upi_id ? `💳 <span>${esc(m.upi_id)}</span>` : `<span style="opacity:0.5">No UPI added</span>`}
            </div>
          </div>
          <div class="member-balance">
            <div class="balance-pill ${netCls}">
              <span>${netIcon}</span>
              <span>${netText}</span>
            </div>
            <div class="balance-subtext">Paid: ${rupees(m.paid_paise)} · Share: ${rupees(m.owes_paise)}</div>
          </div>
          <button class="btn-remove" onclick="removeMember(${m.id}, '${esc(m.name)}')">
            ✕ Remove
          </button>
        </div>
      `;
    }).join("");

  } catch (e) {
    if (e.message && e.message.toLowerCase().includes("not found")) {
      // Container may have cold-booted; attempt automatic re-registration with server
      try {
        const myTrips = getMyTrips();
        if (myTrips.length > 0) {
          const syncPayload = myTrips.map(t => ({
            id:          t.id,
            name:        t.name,
            invite_code: t.invite_code || "",
            members:     getCachedMembers(t.invite_code),
            expenses:    getCachedExpenses(t.invite_code)
          }));
          const synced = await api("/groups/sync", {
            method: "POST",
            body: JSON.stringify({ trips: syncPayload })
          });
          if (Array.isArray(synced)) {
            const current = synced.find(s =>
              s.id === state.groupId ||
              (state.groupInviteCode && s.invite_code && s.invite_code.toLowerCase() === state.groupInviteCode.toLowerCase())
            );
            if (current && current.id !== state.groupId) {
              state.groupId = current.id;
              localStorage.setItem("innov8_active_group_id", current.id);
              return loadMembers();
            }
          }
        }
      } catch (syncErr) {
        console.warn("Auto-healing notice:", syncErr);
      }
    }
    list.innerHTML = `<p class="loading-msg">Notice: ${esc(e.message)}</p>`;
  }
}

async function addMember(name, upiId) {
  try {
    await api(`/groups/${state.groupId}/members`, {
      method: "POST",
      body: JSON.stringify({ name, upi_id: upiId }),
    });

    if (state.groupInviteCode) {
      const current = getCachedMembers(state.groupInviteCode);
      if (!current.some(m => m.name.toLowerCase() === name.toLowerCase())) {
        current.push({ name, upi_id: upiId || "" });
        saveCachedMembers(state.groupInviteCode, current);
      }
    }

    toast(`${name} joined the group! 🎉`);
    closeModal("modalAddMember");
    document.getElementById("formAddMember").reset();
    await loadMembers();
  } catch (e) {
    showErr("errAddMember", e.message);
  }
}

async function removeMember(memberId, name) {
  if (!confirm(`Remove ${name} from the group?`)) return;

  try {
    await api(`/members/${memberId}`, { method: "DELETE" });
    if (state.groupInviteCode) {
      const current = getCachedMembers(state.groupInviteCode).filter(m => m.name.toLowerCase() !== name.toLowerCase());
      saveCachedMembers(state.groupInviteCode, current);
    }
    toast(`${name} removed.`);
    await loadMembers();
  } catch (e) {
    toast(e.message, "error");
  }
}

// ══════════════════════════════════════════════════════════
// 6.  EXPENSES PANEL
// ══════════════════════════════════════════════════════════

async function loadExpenses() {
  if (!state.groupId) return;

  const list = document.getElementById("expensesList");
  list.innerHTML = `<p class="loading-msg">Loading expenses…</p>`;

  try {
    const expenses = await api(`/groups/${state.groupId}/expenses`);

    if (state.groupInviteCode && expenses.length > 0) {
      saveCachedExpenses(state.groupInviteCode, expenses);
    }

    if (!expenses.length) {
      list.innerHTML = `<p class="empty-msg">No expenses logged yet. Tap "+ Add Expense" to record one!</p>`;
      return;
    }

    list.innerHTML = expenses.map(exp => {
      const catIcon = CATEGORY_ICONS[exp.category] || "📦";
      const catClass = `cat-${exp.category || "General"}`;

      const splitChips = exp.splits.map(s =>
        `<span class="split-chip">${esc(s.member_name)}: <strong>${rupees(s.share_paise)}</strong></span>`
      ).join("");

      return `
        <div class="expense-card">
          <div class="expense-top">
            <div>
              <div class="expense-header-left">
                <span class="category-tag ${catClass}">${catIcon} ${esc(exp.category)}</span>
                <span class="expense-title">${esc(exp.title)}</span>
              </div>
              <div class="expense-meta">
                Paid by <strong>${esc(exp.payer_name)}</strong> · ${formatTime(exp.created_at)}
              </div>
            </div>
            <div class="expense-amount-badge">${rupees(exp.amount_paise)}</div>
          </div>
          <div class="expense-splits">${splitChips}</div>
          <div class="expense-footer">
            <button class="btn-remove btn-sm" onclick="deleteExpense(${exp.id}, '${esc(exp.title)}')">
              🗑️ Delete
            </button>
          </div>
        </div>
      `;
    }).join("");

  } catch (e) {
    list.innerHTML = `<p class="loading-msg">Error: ${esc(e.message)}</p>`;
  }
}

function populateExpenseForm() {
  const payerSelect = document.getElementById("inputExpPayer");
  payerSelect.innerHTML = `<option value="">— Select payer —</option>`;

  state.members.forEach(m => {
    const opt = document.createElement("option");
    opt.value = m.id;
    opt.textContent = m.name;
    payerSelect.appendChild(opt);
  });

  buildCustomSplitRows();
}

function buildCustomSplitRows() {
  const container = document.getElementById("customSplitInputs");
  container.innerHTML = "";

  state.members.forEach(m => {
    const row = document.createElement("div");
    row.className = "custom-split-row";

    const label = document.createElement("label");
    label.htmlFor = `split_${m.id}`;
    label.textContent = m.name;

    const input = document.createElement("input");
    input.type        = "number";
    input.id          = `split_${m.id}`;
    input.placeholder = "0.00";
    input.min         = "0";
    input.step        = "0.01";
    input.dataset.mid = m.id;
    input.addEventListener("input", updateSplitSum);

    row.appendChild(label);
    row.appendChild(input);
    container.appendChild(row);
  });
}

function updateSplitSum() {
  const totalInput  = parseFloat(document.getElementById("inputExpAmount").value) || 0;
  const splitInputs = document.querySelectorAll("#customSplitInputs input");

  let sum = 0;
  splitInputs.forEach(inp => { sum += parseFloat(inp.value) || 0; });

  const display = document.getElementById("splitSumDisplay");
  const diff    = Math.round((sum - totalInput) * 100);

  display.textContent = `Sum: ₹${sum.toFixed(2)} / ₹${totalInput.toFixed(2)}`;

  if (diff === 0) {
    display.className = "split-sum ok";
    display.textContent += "  ✓ Perfect Match";
  } else {
    display.className = "split-sum bad";
    display.textContent += diff > 0
      ? `  (+₹${(diff/100).toFixed(2)} over)`
      : `  (-₹${(Math.abs(diff)/100).toFixed(2)} remaining)`;
  }
}

async function addExpense() {
  const title     = document.getElementById("inputExpTitle").value.trim();
  const amount    = parseFloat(document.getElementById("inputExpAmount").value);
  const payerId   = parseInt(document.getElementById("inputExpPayer").value);
  const category  = document.getElementById("inputExpCategory").value;
  const splitType = document.querySelector('input[name="splitType"]:checked').value;

  clearErr("errAddExpense");

  if (!title) return showErr("errAddExpense", "Expense title is required.");
  if (!amount || amount <= 0) return showErr("errAddExpense", "Enter a valid positive amount.");
  if (!payerId) return showErr("errAddExpense", "Select who paid for this expense.");

  const body = { title, amount, payer_id: payerId, category, split: splitType };

  if (splitType === "custom") {
    const shares = [];
    let sum = 0;
    document.querySelectorAll("#customSplitInputs input").forEach(inp => {
      const share = parseFloat(inp.value) || 0;
      sum += share;
      shares.push({ member_id: parseInt(inp.dataset.mid), amount: share });
    });

    if (Math.abs(Math.round(sum * 100) - Math.round(amount * 100)) > 1) {
      return showErr("errAddExpense", `Custom shares sum to ₹${sum.toFixed(2)}, but total is ₹${amount.toFixed(2)}.`);
    }
    body.shares = shares;
  }

  try {
    await api(`/groups/${state.groupId}/expenses`, {
      method: "POST",
      body: JSON.stringify(body),
    });

    toast(`Expense "${title}" saved! 💸`);
    closeModal("modalAddExpense");
    document.getElementById("formAddExpense").reset();
    document.getElementById("customSplitRows").classList.add("hidden");

    loadExpenses();
    loadMembers();
  } catch (e) {
    showErr("errAddExpense", e.message);
  }
}

async function deleteExpense(expId, title) {
  if (!confirm(`Delete expense "${title}"?`)) return;

  try {
    await api(`/expenses/${expId}`, { method: "DELETE" });
    if (state.groupInviteCode) {
      const current = getCachedExpenses(state.groupInviteCode).filter(e => e.title !== title);
      saveCachedExpenses(state.groupInviteCode, current);
    }
    toast(`"${title}" deleted.`);
    loadExpenses();
    loadMembers();
  } catch (e) {
    toast(e.message, "error");
  }
}

// ══════════════════════════════════════════════════════════
// 7.  ANALYTICS PANEL (Charts + Visual Stat Cards)
// ══════════════════════════════════════════════════════════

async function loadAnalytics() {
  if (!state.groupId) return;

  try {
    const data = await api(`/groups/${state.groupId}/analytics`);
    const totalGroupSpend = data.by_category.reduce((acc, c) => acc + c.total_paise, 0);

    // ── 1. Key Metrics Stat Row ────────────────────────────
    const topPayer = data.by_member.length > 0 ? data.by_member[0] : null;
    const topCat   = data.by_category.length > 0 ? data.by_category[0] : null;

    const statRow = document.getElementById("analyticsStatRow");
    statRow.innerHTML = `
      <div class="stat-pill-card">
        <div class="stat-pill-icon">👑</div>
        <div class="stat-pill-info">
          <h4>Top Spender</h4>
          <div class="stat-val">${topPayer ? esc(topPayer.name) : "—"}</div>
          <small style="color:var(--accent-emerald)">${topPayer ? rupees(topPayer.paid_paise) : ""}</small>
        </div>
      </div>
      <div class="stat-pill-card">
        <div class="stat-pill-icon">${topCat ? (CATEGORY_ICONS[topCat.category] || "🏷️") : "🏷️"}</div>
        <div class="stat-pill-info">
          <h4>Largest Category</h4>
          <div class="stat-val">${topCat ? esc(topCat.category) : "—"}</div>
          <small style="color:var(--accent-amber)">${topCat ? rupees(topCat.total_paise) : ""}</small>
        </div>
      </div>
      <div class="stat-pill-card">
        <div class="stat-pill-icon">📊</div>
        <div class="stat-pill-info">
          <h4>Group Total</h4>
          <div class="stat-val">${rupees(totalGroupSpend)}</div>
          <small style="color:var(--accent-cyan)">${data.by_category.length} categories</small>
        </div>
      </div>
    `;

    // ── 2. Visual Progress Bars (Members) ──────────────────
    const memberBarsContainer = document.getElementById("memberSpendBars");
    if (data.by_member.length === 0) {
      memberBarsContainer.innerHTML = `<p class="empty-msg" style="padding:10px">No spend data yet.</p>`;
    } else {
      const maxSpend = Math.max(...data.by_member.map(m => m.paid_paise), 1);
      memberBarsContainer.innerHTML = data.by_member.map((m, i) => {
        const pct = Math.round((m.paid_paise / maxSpend) * 100);
        const color = VIBRANT_COLORS[i % VIBRANT_COLORS.length];
        return `
          <div class="breakdown-item">
            <div class="bi-header">
              <span>${esc(m.name)}</span>
              <strong style="color:${color}">${rupees(m.paid_paise)}</strong>
            </div>
            <div class="bi-bar-bg">
              <div class="bi-bar-fill" style="width:${pct}%; background:${color}"></div>
            </div>
          </div>
        `;
      }).join("");
    }

    // ── 3. Category Pills List ────────────────────────────
    const catPillsContainer = document.getElementById("categorySpendPills");
    if (data.by_category.length === 0) {
      catPillsContainer.innerHTML = `<p class="empty-msg" style="padding:10px">No categories recorded.</p>`;
    } else {
      catPillsContainer.innerHTML = data.by_category.map((c, i) => {
        const icon = CATEGORY_ICONS[c.category] || "📦";
        const sharePct = totalGroupSpend > 0 ? Math.round((c.total_paise / totalGroupSpend) * 100) : 0;
        return `
          <div class="cat-pill">
            <span>${icon} ${esc(c.category)}</span>
            <strong style="color:var(--accent-cyan)">${sharePct}%</strong>
            <span style="opacity:0.6">(${rupees(c.total_paise)})</span>
          </div>
        `;
      }).join("");
    }

    // ── 4. Render Chart.js Canvas Graphics ─────────────────
    if (typeof Chart !== "undefined") {
      // 4A. Bar chart: Spend by Member
      const memberLabels = data.by_member.map(d => d.name);
      const memberValues = data.by_member.map(d => d.paid_paise / 100);

      if (state.chartMember) {
        state.chartMember.destroy();
        state.chartMember = null;
      }

      const canvasMember = document.getElementById("chartByMember");
      const ctxMember = canvasMember.getContext("2d");

      state.chartMember = new Chart(ctxMember, {
        type: "bar",
        data: {
          labels: memberLabels,
          datasets: [{
            label: "Amount Paid (₹)",
            data: memberValues,
            backgroundColor: VIBRANT_COLORS.slice(0, memberLabels.length),
            borderRadius: 8,
            borderSkipped: false,
          }],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: { display: false },
            tooltip: {
              backgroundColor: "#0d1d35",
              titleColor: "#f0e2cc",
              bodyColor: "#ffffff",
              borderColor: "#dfc8a2",
              borderWidth: 1,
              padding: 12,
              callbacks: {
                label: ctx => ` Paid: ₹${ctx.parsed.y.toLocaleString("en-IN", { minimumFractionDigits: 2 })}`
              }
            }
          },
          scales: {
            x: {
              ticks: { color: "#d8cebe", font: { family: "'Plus Jakarta Sans'", weight: 600 } },
              grid:  { display: false },
            },
            y: {
              ticks: {
                color: "#d8cebe",
                callback: v => "₹" + v.toLocaleString("en-IN"),
              },
              grid: { color: "rgba(223, 200, 162, 0.08)" },
              beginAtZero: true,
            }
          }
        }
      });

      // 4B. Doughnut chart: Spend by Category
      const catLabels = data.by_category.map(d => d.category);
      const catValues = data.by_category.map(d => d.total_paise / 100);

      if (state.chartCategory) {
        state.chartCategory.destroy();
        state.chartCategory = null;
      }

      const canvasCat = document.getElementById("chartByCategory");
      const ctxCat = canvasCat.getContext("2d");

      state.chartCategory = new Chart(ctxCat, {
        type: "doughnut",
        data: {
          labels: catLabels,
          datasets: [{
            data: catValues,
            backgroundColor: VIBRANT_COLORS.slice(0, catLabels.length),
            borderColor: "#12233e",
            borderWidth: 4,
            hoverOffset: 12,
          }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: {
              position: "bottom",
              labels: {
                color: "#f0e2cc",
                padding: 14,
                font: { family: "'Plus Jakarta Sans'", size: 12, weight: 600 },
                usePointStyle: true,
              }
            },
            tooltip: {
              backgroundColor: "#0d1d35",
              titleColor: "#f0e2cc",
              bodyColor: "#dfc8a2",
              borderColor: "#dfc8a2",
              borderWidth: 1,
              padding: 12,
              callbacks: {
                label: ctx => ` ${ctx.label}: ₹${ctx.parsed.toLocaleString("en-IN", { minimumFractionDigits: 2 })}`
              }
            }
          }
        }
      });
    }

  } catch (e) {
    toast("Could not load analytics: " + e.message, "error");
  }
}

// ══════════════════════════════════════════════════════════
// 8.  CHAT PANEL
// ══════════════════════════════════════════════════════════

async function loadChat() {
  if (!state.groupId) return;

  if (state.chatPollTimer) {
    clearInterval(state.chatPollTimer);
    state.chatPollTimer = null;
  }

  // Restore saved sender name on this device
  const savedSender = localStorage.getItem("innov8_user_name");
  const senderInput = document.getElementById("chatSender");
  if (savedSender && senderInput && !senderInput.value) {
    senderInput.value = savedSender;
  }

  state.lastMessageId = 0;
  document.getElementById("chatMessages").innerHTML = "";

  try {
    const messages = await api(`/groups/${state.groupId}/messages`);
    messages.forEach(appendMessage);
    state.chatPollTimer = setInterval(pollChat, 5000);
  } catch (e) {
    toast("Chat error: " + e.message, "error");
  }
}

async function pollChat() {
  if (!state.groupId) return;
  try {
    const messages = await api(`/groups/${state.groupId}/messages?since=${state.lastMessageId}`);
    messages.forEach(appendMessage);
  } catch (e) {
    console.warn("Chat poll error:", e.message);
  }
}

function appendMessage(msg) {
  if (msg.id > state.lastMessageId) state.lastMessageId = msg.id;

  const box    = document.getElementById("chatMessages");
  const bubble = document.createElement("div");
  bubble.className = "chat-bubble";

  const localUser = (localStorage.getItem("innov8_user_name") || document.getElementById("chatSender")?.value || "").trim().toLowerCase();
  const isMe = localUser && msg.sender.trim().toLowerCase() === localUser;
  if (isMe) {
    bubble.classList.add("me");
  }

  const sender = document.createElement("div");
  sender.className = "bubble-sender";
  sender.textContent = isMe ? "You (" + msg.sender + ")" : msg.sender;

  const body   = document.createElement("div");
  body.className = "bubble-body";
  body.textContent = msg.body;

  const time   = document.createElement("div");
  time.className = "bubble-time";
  time.textContent = formatTime(msg.created_at);

  bubble.appendChild(sender);
  bubble.appendChild(body);
  bubble.appendChild(time);
  box.appendChild(bubble);

  box.scrollTop = box.scrollHeight;
}

async function sendMessage(sender, body) {
  try {
    const msg = await api(`/groups/${state.groupId}/messages`, {
      method: "POST",
      body: JSON.stringify({ sender, body }),
    });
    appendMessage(msg);
  } catch (e) {
    toast("Could not send message: " + e.message, "error");
  }
}

// ══════════════════════════════════════════════════════════
// 9.  SETTLEMENT PANEL
// ══════════════════════════════════════════════════════════

async function loadSettlements() {
  if (!state.groupId) return;

  const list = document.getElementById("settlementsList");
  list.innerHTML = `<p class="loading-msg">Computing optimal settlements…</p>`;

  try {
    const settlements = await api(`/groups/${state.groupId}/settlements`);

    if (!settlements.length) {
      list.innerHTML = `<p class="empty-msg">🎉 Everyone is completely settled up!</p>`;
      return;
    }

    list.innerHTML = settlements.map(s => {
      const isDone = s.status === "done";
      const doneClass = isDone ? " done" : "";
      const doneLabel = isDone ? "✓ Paid" : "Mark Paid";

      const qrBtn = s.qr_url
        ? `<button class="btn btn-pay btn-sm"
                   onclick="showQR('${esc(s.qr_url)}', '${esc(s.upi_link)}',
                     '${esc(s.from_name)} pays ${esc(s.to_name)} ${rupees(s.amount_paise)}')">
             📱 Pay UPI / QR
           </button>`
        : "";

      return `
        <div class="settle-card${doneClass}">
          <div class="settle-transfer-row">
            <div class="settle-members-flow">
              <span>${esc(s.from_name)}</span>
              <span class="settle-arrow">➔</span>
              <span>${esc(s.to_name)}</span>
            </div>
            <div class="settle-amount-display">${rupees(s.amount_paise)}</div>
          </div>
          <div class="settle-actions-bar">
            ${qrBtn}
            <button class="btn btn-sm ${isDone ? "btn-outline" : "btn-outline"}"
                    onclick="markSettlementDone(${s.id}, ${isDone})">
              ${doneLabel}
            </button>
          </div>
        </div>
      `;
    }).join("");

  } catch (e) {
    list.innerHTML = `<p class="loading-msg">Error: ${esc(e.message)}</p>`;
  }
}

async function recalculate() {
  const list = document.getElementById("settlementsList");
  list.innerHTML = `<p class="loading-msg">Recalculating…</p>`;

  try {
    await api(`/groups/${state.groupId}/settlements/recalculate`, { method: "POST" });
    loadSettlements();
    toast("Settlements recalculated via C++ algorithm! ⚡");
  } catch (e) {
    toast("Recalculate error: " + e.message, "error");
  }
}

async function markSettlementDone(settlementId, currentlyDone) {
  const newStatus = currentlyDone ? "pending" : "done";

  try {
    await api(`/settlements/${settlementId}`, {
      method: "PATCH",
      body: JSON.stringify({ status: newStatus }),
    });
    toast(newStatus === "done" ? "🎉 Payment recorded as Paid!" : "Marked as pending.");
    loadSettlements();
  } catch (e) {
    toast(e.message, "error");
  }
}

function showQR(qrUrl, upiLink, description) {
  document.getElementById("qrImage").src         = qrUrl;
  document.getElementById("qrDesc").textContent  = description;
  document.getElementById("qrUpiLink").href      = upiLink;
  openModal("modalQR");
}

// ══════════════════════════════════════════════════════════
// 10. EVENT LISTENERS
// ══════════════════════════════════════════════════════════

document.addEventListener("DOMContentLoaded", async () => {
  // Check URL query parameters for invite links: ?join=XYZ or ?group=XYZ or ?code=XYZ
  const urlParams = new URLSearchParams(window.location.search);
  const inviteParam = urlParams.get("join") || urlParams.get("group") || urlParams.get("code");
  const nameParam = urlParams.get("name");
  if (inviteParam) {
    await joinTripByCode(inviteParam, nameParam);
    window.history.replaceState({}, document.title, window.location.pathname);
  } else {
    await loadGroups();
  }

  document.getElementById("groupSelect").addEventListener("change", e => {
    selectGroup(e.target.value);
  });

  document.querySelectorAll(".tab-btn").forEach(btn => {
    btn.addEventListener("click", () => switchTab(btn.dataset.tab));
  });

  document.getElementById("btnNewGroup").addEventListener("click", () => {
    clearErr("errNewGroup");
    openModal("modalNewGroup");
    document.getElementById("inputGroupName").focus();
  });

  document.getElementById("btnWelcomeNew").addEventListener("click", () => {
    clearErr("errNewGroup");
    openModal("modalNewGroup");
    document.getElementById("inputGroupName").focus();
  });

  const btnJoinTrip = document.getElementById("btnJoinTrip");
  if (btnJoinTrip) {
    btnJoinTrip.addEventListener("click", () => {
      clearErr("errJoinTrip");
      openModal("modalJoinTrip");
      document.getElementById("inputJoinCode")?.focus();
    });
  }

  const btnWelcomeJoin = document.getElementById("btnWelcomeJoin");
  if (btnWelcomeJoin) {
    btnWelcomeJoin.addEventListener("click", () => {
      clearErr("errJoinTrip");
      openModal("modalJoinTrip");
      document.getElementById("inputJoinCode")?.focus();
    });
  }

  // ── Leave Trip button & confirmation modal listeners ───
  const btnLeaveTrip = document.getElementById("btnLeaveTrip");
  if (btnLeaveTrip) {
    btnLeaveTrip.addEventListener("click", () => {
      if (!state.groupId) return;
      const nameEl = document.getElementById("leaveTripName");
      if (nameEl) nameEl.textContent = `"${state.groupName || "this trip"}"`;
      openModal("modalLeaveTrip");
    });
  }

  const btnConfirmLeave = document.getElementById("btnConfirmLeaveTrip");
  if (btnConfirmLeave) {
    btnConfirmLeave.addEventListener("click", () => {
      const idToRemove = state.groupId;
      const nameToRemove = state.groupName || "Trip";
      closeModal("modalLeaveTrip");
      removeTripFromDevice(idToRemove);
      toast(`Removed "${nameToRemove}" from this device.`);
    });
  }

  const formJoinTrip = document.getElementById("formJoinTrip");
  if (formJoinTrip) {
    formJoinTrip.addEventListener("submit", e => {
      e.preventDefault();
      const code = document.getElementById("inputJoinCode").value.trim();
      joinTripByCode(code);
    });
  }

  document.getElementById("formNewGroup").addEventListener("submit", e => {
    e.preventDefault();
    const name = document.getElementById("inputGroupName").value.trim();
    if (!name) return showErr("errNewGroup", "Group name is required.");
    createGroup(name);
  });

  document.getElementById("btnAddMember").addEventListener("click", () => {
    clearErr("errAddMember");
    openModal("modalAddMember");
    document.getElementById("inputMemberName").focus();
  });

  document.getElementById("formAddMember").addEventListener("submit", e => {
    e.preventDefault();
    const name = document.getElementById("inputMemberName").value.trim();
    const upi  = document.getElementById("inputMemberUpi").value.trim();
    if (!name) return showErr("errAddMember", "Name is required.");
    addMember(name, upi);
  });

  document.getElementById("btnAddExpense").addEventListener("click", () => {
    clearErr("errAddExpense");
    populateExpenseForm();
    openModal("modalAddExpense");
  });

  document.querySelectorAll('input[name="splitType"]').forEach(radio => {
    radio.addEventListener("change", () => {
      const isCustom = radio.value === "custom";
      document.getElementById("customSplitRows").classList.toggle("hidden", !isCustom);
    });
  });

  document.getElementById("inputExpAmount").addEventListener("input", updateSplitSum);

  document.getElementById("formAddExpense").addEventListener("submit", e => {
    e.preventDefault();
    addExpense();
  });

  document.getElementById("chatForm").addEventListener("submit", e => {
    e.preventDefault();
    const sender = document.getElementById("chatSender").value.trim();
    const body   = document.getElementById("chatBody").value.trim();
    if (!sender) return toast("Enter your name first.", "error");
    if (!body)   return toast("Message cannot be empty.", "error");
    localStorage.setItem("innov8_user_name", sender);
    sendMessage(sender, body);
    document.getElementById("chatBody").value = "";
  });

  // ── Settle recalculate listener ─────────────────────────
  const btnRecalc = document.getElementById("btnRecalculate");
  if (btnRecalc) {
    btnRecalc.addEventListener("click", recalculate);
  }

  // ── Connect Devices Modal & QR Listeners ─────────────────
  const btnConnect = document.getElementById("btnConnectMobile");
  if (btnConnect) {
    btnConnect.addEventListener("click", openConnectModal);
  }

  const btnTabPub = document.getElementById("btnTabPublic");
  if (btnTabPub) {
    btnTabPub.addEventListener("click", () => showConnectTab("public"));
  }

  const btnTabLoc = document.getElementById("btnTabLocal");
  if (btnTabLoc) {
    btnTabLoc.addEventListener("click", () => showConnectTab("local"));
  }

  const btnCopyConnect = document.getElementById("btnCopyConnectUrl");
  if (btnCopyConnect) {
    btnCopyConnect.addEventListener("click", () => {
      const input = document.getElementById("connectUrlInput");
      if (input && input.value) {
        navigator.clipboard.writeText(input.value)
          .then(() => toast("Link copied to clipboard! 📋", "success"))
          .catch(() => {
            input.select();
            document.execCommand("copy");
            toast("Link copied to clipboard! 📋", "success");
          });
      }
    });
  }

  // ── Modal close listeners ───────────────────────────────
  document.querySelectorAll("[data-close]").forEach(btn => {
    btn.addEventListener("click", () => closeModal(btn.dataset.close));
  });

  document.querySelectorAll(".modal-overlay").forEach(overlay => {
    overlay.addEventListener("click", e => {
      if (e.target === overlay) closeModal(overlay.id);
    });
  });

  document.addEventListener("keydown", e => {
    if (e.key === "Escape") {
      document.querySelectorAll(".modal-overlay:not(.hidden)").forEach(m => {
        closeModal(m.id);
      });
    }
  });
});

// ══════════════════════════════════════════════════════════
// 10. CONNECT DEVICES MODAL & QR GENERATOR
// ══════════════════════════════════════════════════════════

let connectUrls = {
  public: "https://decreased-pregnant-interaction-testimonials.trycloudflare.com",
  local:  "http://192.168.236.179:5000"
};

async function openConnectModal() {
  try {
    const net = await api("/network-info");
    if (net.public_url) connectUrls.public = net.public_url;
    if (net.local_url)  connectUrls.local  = net.local_url;
  } catch (e) {
    console.warn("Could not fetch network info:", e);
  }

  // If user opened via Vercel or Cloudflare, ensure it matches current origin
  if (window.location.origin.includes(".vercel.app") || window.location.origin.includes(".trycloudflare.com")) {
    connectUrls.public = window.location.origin;
  }

  showConnectTab("public");
  openModal("modalConnectMobile");
}

function showConnectTab(tab) {
  const btnPublic = document.getElementById("btnTabPublic");
  const btnLocal  = document.getElementById("btnTabLocal");
  const input     = document.getElementById("connectUrlInput");
  const hint      = document.getElementById("connectHint");

  const baseUrl = (tab === "local") ? connectUrls.local : connectUrls.public;
  const fullInviteUrl = state.groupInviteCode
    ? `${baseUrl}/?join=${encodeURIComponent(state.groupInviteCode)}&name=${encodeURIComponent(state.groupName || "")}`
    : baseUrl;

  if (tab === "local") {
    btnLocal.classList.add("active");
    btnPublic.classList.remove("active");
    hint.textContent = "📶 For devices on the SAME Wi-Fi or your Phone's Hotspot.";
  } else {
    btnPublic.classList.add("active");
    btnLocal.classList.remove("active");
    hint.textContent = "🌍 Secret invite link! Anyone with this link or QR code can join this private trip.";
  }

  input.value = fullInviteUrl;

  // Render QR Code in modal
  const qrBox = document.getElementById("connectQRCode");
  qrBox.innerHTML = "";
  if (typeof QRCode !== "undefined") {
    new QRCode(qrBox, {
      text: fullInviteUrl,
      width: 180,
      height: 180,
      colorDark: "#091322",
      colorLight: "#ffffff",
      correctLevel: QRCode.CorrectLevel.M
    });
  }
}
