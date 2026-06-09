/**
 * PDCN CRM – Shared API Client & Utilities
 * Provides: Auth, api(), shims, helpers, toast
 */

const API_BASE = "/api/v1";

// ─── Token / Session Management ─────────────────────────────────────────
const Auth = {
  getAccess:  () => localStorage.getItem("access_token"),
  getRefresh: () => localStorage.getItem("refresh_token"),
  getToken:   () => localStorage.getItem("access_token"), // alias
  getUser: () => {
    try { return JSON.parse(localStorage.getItem("user") || "null"); } catch { return null; }
  },
  save: (data) => {
    localStorage.setItem("access_token",  data.access_token);
    localStorage.setItem("refresh_token", data.refresh_token);
    localStorage.setItem("user", JSON.stringify(data.user));
  },
  clear: () => {
    localStorage.removeItem("access_token");
    localStorage.removeItem("refresh_token");
    localStorage.removeItem("user");
  },
  isLoggedIn:    () => !!localStorage.getItem("access_token"),
  isSuperAdmin:  () => { const u = Auth.getUser(); return u && u.role === "super_admin"; },
  isTenantAdmin: () => { const u = Auth.getUser(); return u && (u.role === "tenant_admin" || u.role === "super_admin"); },
};

// ─── Global shims — legacy pages call these as plain functions ────────────
function getToken()   { return Auth.getAccess(); }
function getUser()    { return Auth.getUser(); }
function getRefresh() { return Auth.getRefresh(); }
function isLoggedIn() { return Auth.isLoggedIn(); }
function doLogout()   { logout(); }

// ─── HTTP Client ─────────────────────────────────────────────────────────
async function api(path, options) {
  options = options || {};
  const headers = Object.assign({ "Content-Type": "application/json" }, options.headers || {});
  const token = Auth.getAccess();
  if (token) headers["Authorization"] = "Bearer " + token;

  let res = await fetch(API_BASE + path, Object.assign({}, options, { headers }));

  // Auto-refresh on 401
  if (res.status === 401 && Auth.getRefresh()) {
    const refreshed = await fetch(API_BASE + "/auth/refresh", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: Auth.getRefresh() }),
    });
    if (refreshed.ok) {
      const data = await refreshed.json();
      Auth.save(data);
      headers["Authorization"] = "Bearer " + data.access_token;
      res = await fetch(API_BASE + path, Object.assign({}, options, { headers }));
    } else {
      Auth.clear();
      window.location.href = "/templates/login.html";
      return;
    }
  }

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "Request failed");
  }
  return res.json();
}

// Convenience methods
api.get    = (path)        => api(path, { method: "GET" });
api.post   = (path, body)  => api(path, { method: "POST",   body: JSON.stringify(body) });
api.patch  = (path, body)  => api(path, { method: "PATCH",  body: JSON.stringify(body) });
api.put    = (path, body)  => api(path, { method: "PUT",    body: JSON.stringify(body) });
api.delete = (path)        => api(path, { method: "DELETE" });

// ─── Auth Guards ─────────────────────────────────────────────────────────
function requireAuth() {
  if (!Auth.isLoggedIn()) {
    window.location.href = "/templates/login.html";
    return false;
  }
  return true;
}

function requireSuperAdmin() {
  if (!Auth.isSuperAdmin()) {
    window.location.href = "/templates/login.html";
    return false;
  }
  return true;
}

function logout() {
  const r = Auth.getRefresh();
  if (r) api("/auth/logout", { method: "POST", body: JSON.stringify({ refresh_token: r }) }).catch(() => {});
  Auth.clear();
  window.location.href = "/templates/login.html";
}

// ─── Toast Notifications ─────────────────────────────────────────────────
function showToast(message, type) {
  type = type || "success";
  let container = document.getElementById("toast-container");
  if (!container) {
    container = document.createElement("div");
    container.id = "toast-container";
    container.style.cssText = "position:fixed;top:20px;right:20px;z-index:9999;display:flex;flex-direction:column;gap:8px;pointer-events:none;";
    document.body.appendChild(container);
  }

  const colors = { success:"#059669", error:"#DC2626", warning:"#D97706", info:"#4338ca" };
  const bgcols = { success:"#ECFDF5", error:"#FEF2F2", warning:"#FFFBEB", info:"#EEF2FF" };
  const icons  = { success:"✓",       error:"✕",       warning:"⚠",       info:"ℹ" };
  const c  = colors[type] || colors.success;
  const bg = bgcols[type] || bgcols.success;

  const toast = document.createElement("div");
  toast.style.cssText =
    "background:" + bg + ";color:#0F172A;padding:13px 18px;border-radius:10px;" +
    "border:1px solid " + c + "33;border-left:4px solid " + c + ";" +
    "box-shadow:0 4px 20px rgba(15,23,42,.12),0 1px 4px rgba(15,23,42,.06);" +
    "display:flex;align-items:center;gap:10px;min-width:260px;max-width:380px;" +
    "font-family:'Nunito',sans-serif;font-size:13.5px;font-weight:600;pointer-events:all;" +
    "animation:_toastIn .25s cubic-bezier(.16,1,.3,1);cursor:pointer;";
  toast.innerHTML =
    "<span style='color:" + c + ";font-weight:800;font-size:16px;flex-shrink:0'>" +
    icons[type] + "</span><span>" + message + "</span>";
  toast.onclick = () => toast.remove();
  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = "0";
    toast.style.transform = "translateX(14px)";
    toast.style.transition = "all .25s";
    setTimeout(() => toast.remove(), 280);
  }, 4000);
}

// ─── Button Loading ───────────────────────────────────────────────────────
function setLoading(btn, loading) {
  if (loading) {
    btn.dataset.original = btn.innerHTML;
    btn.innerHTML = '<span class="spinner"></span> Loading...';
    btn.disabled = true;
  } else {
    btn.innerHTML = btn.dataset.original || btn.innerHTML;
    btn.disabled = false;
  }
}

// ─── Date Helpers ─────────────────────────────────────────────────────────
function formatDate(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
}

function formatDateTime(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-IN", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

// ─── Status / Role Badges ─────────────────────────────────────────────────
function statusBadge(status) {
  const map = {
    active:   ["Active",   "#059669", "#ECFDF5"],
    trial:    ["Trial",    "#4338ca", "#EEF2FF"],
    pending:  ["Pending",  "#D97706", "#FFFBEB"],
    disabled: ["Disabled", "#DC2626", "#FEF2F2"],
    deleted:  ["Deleted",  "#6b7280", "#F8FAFC"],
  };
  const [label, color, bg] = map[status] || ["Unknown", "#6b7280", "#F8FAFC"];
  return '<span style="background:' + bg + ';color:' + color + ';padding:3px 10px;border-radius:20px;font-size:12px;font-weight:700;border:1px solid ' + color + '33;">' + label + '</span>';
}

function roleBadge(role) {
  const map = {
    super_admin:      ["Super Admin",  "#D97706"],
    tenant_admin:     ["Tenant Admin", "#4338ca"],
    cn_team:          ["CN Team",      "#0891B2"],
    finance_team:     ["Finance",      "#059669"],
    cfa_team:         ["CFA Team",     "#7C3AED"],
    finance_cfa_team: ["Finance+CFA",  "#7C3AED"],
    dealer:           ["Dealer",       "#DB2777"],
  };
  const [label, color] = map[role] || ["Unknown", "#6b7280"];
  return '<span style="color:' + color + ';font-weight:700;font-size:12px;">' + label + '</span>';
}

// ─── CSS Animations injected once ─────────────────────────────────────────
(function() {
  const s = document.createElement("style");
  s.textContent =
    "@keyframes _toastIn{from{transform:translateX(100%);opacity:0}to{transform:translateX(0);opacity:1}}" +
    "@keyframes spin{to{transform:rotate(360deg)}}" +
    ".spinner{display:inline-block;width:14px;height:14px;border:2px solid rgba(255,255,255,.3);border-top-color:#fff;border-radius:50%;animation:spin .6s linear infinite;}";
  document.head.appendChild(s);
})();
