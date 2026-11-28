/* SaaSWatch — fonctions communes à toutes les pages.
 * Le jeton JWT reçu à la connexion est gardé dans sessionStorage (effacé à la fermeture
 * de l'onglet) et envoyé à chaque appel de l'API dans l'en-tête Authorization.
 */
const SW = {
  token: () => sessionStorage.getItem("sw_token"),
  user: () => JSON.parse(sessionStorage.getItem("sw_user") || "null"),

  save(token, user) {
    sessionStorage.setItem("sw_token", token);
    sessionStorage.setItem("sw_user", JSON.stringify(user));
  },

  logout() {
    sessionStorage.removeItem("sw_token");
    sessionStorage.removeItem("sw_user");
    window.location.href = "/login";
  },

  /* Appel de l'API. Renvoie la réponse JSON ; redirige vers /login si le jeton est refusé. */
  async api(path, options = {}) {
    const headers = Object.assign({}, options.headers || {});
    if (SW.token()) headers["Authorization"] = "Bearer " + SW.token();
    const res = await fetch(path, Object.assign({}, options, { headers }));
    if (res.status === 401) { SW.logout(); throw new Error("non connecté"); }
    const isJson = (res.headers.get("content-type") || "").includes("application/json");
    const data = isJson ? await res.json() : await res.blob();
    if (!res.ok) {
      const err = new Error((data && data.erreur) || ("Erreur " + res.status));
      err.status = res.status; err.data = data;
      throw err;
    }
    return data;
  },

  /* À appeler en haut de chaque page protégée. */
  requireLogin() {
    if (!SW.token()) { window.location.href = "/login"; return false; }
    const u = SW.user();
    const el = document.getElementById("sw-user");
    if (el && u) el.textContent = u.username + " · " + u.role;
    document.querySelectorAll("[data-admin-only]").forEach(e => {
      if (!u || u.role !== "admin") e.classList.add("d-none");
    });
    return true;
  },

  isAdmin: () => (SW.user() || {}).role === "admin",

  fmt: (n) => (n === null || n === undefined) ? "–" : Number(n).toLocaleString("fr-FR"),

  date(iso) {
    if (!iso) return "–";
    const d = new Date(iso);
    return d.toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "medium" });
  },

  esc(t) {
    return String(t === undefined || t === null ? "" : t)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  },

  levelBadge(level) {
    const c = { DEBUG: "secondary", INFO: "info", WARNING: "warning", ERROR: "danger", CRITICAL: "dark" }[level] || "light";
    return `<span class="badge text-bg-${c}">${SW.esc(level)}</span>`;
  },

  statusBadge(code) {
    if (!code) return "–";
    const c = code >= 500 ? "danger" : code >= 400 ? "warning" : "success";
    return `<span class="badge text-bg-${c}">${code}</span>`;
  },

  alert(zone, type, html) {
    document.getElementById(zone).innerHTML =
      `<div class="alert alert-${type} alert-dismissible fade show" role="alert">${html}
       <button type="button" class="btn-close" data-bs-dismiss="alert"></button></div>`;
  },

  download(blob, name) {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = name;
    a.click();
    URL.revokeObjectURL(a.href);
  },
};
