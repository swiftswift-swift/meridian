/* The API client. One place that knows about auth, error shape and URLs. */

const TOKEN_KEY = "meridian.token";

export const session = {
  get token() {
    return sessionStorage.getItem(TOKEN_KEY);
  },
  set token(value) {
    if (value) sessionStorage.setItem(TOKEN_KEY, value);
    else sessionStorage.removeItem(TOKEN_KEY);
  },
  user: null,
};

export async function api(path, { method = "GET", body } = {}) {
  const headers = { Accept: "application/json" };
  if (body) headers["Content-Type"] = "application/json";
  if (session.token) headers.Authorization = `Bearer ${session.token}`;

  const response = await fetch(`/api/v1${path}`, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });

  if (response.status === 204) return null;
  const text = await response.text();
  const payload = text ? JSON.parse(text) : null;

  if (!response.ok) {
    // Every error is an RFC 9457 problem document, so there is one shape to read.
    const error = new Error(payload?.detail || `Request failed (${response.status})`);
    error.status = response.status;
    error.code = payload?.code;
    throw error;
  }
  return payload;
}

export const auth = {
  async demo(role = "analyst") {
    const result = await api("/auth/demo", { method: "POST", body: { role } });
    session.token = result.access_token;
    session.user = result.user;
    return result.user;
  },
  async login(email, password) {
    const result = await api("/auth/login", { method: "POST", body: { email, password } });
    session.token = result.access_token;
    session.user = result.user;
    return result.user;
  },
  async signup(email, password, display_name) {
    const result = await api("/auth/signup", {
      method: "POST",
      body: { email, password, display_name },
    });
    session.token = result.access_token;
    session.user = result.user;
    return result.user;
  },
  async me() {
    session.user = await api("/auth/me");
    return session.user;
  },
  signOut() {
    session.token = null;
    session.user = null;
  },
  listUsers: () => api("/auth/users"),
  setRole: (id, role) => api(`/auth/users/${id}/role`, { method: "PUT", body: { role } }),
};

export const research = {
  status: () => api("/research/status"),
  ask: (question) => api("/research/ask", { method: "POST", body: { question } }),
};

export const runs = {
  list: (cursor) => api(`/runs${cursor ? `?cursor=${encodeURIComponent(cursor)}` : ""}`),
  create: (question) => api("/runs", { method: "POST", body: { question } }),
  get: (id) => api(`/runs/${id}`),
  share: (id) => api(`/runs/${id}/share`, { method: "POST" }),
  remove: (id) => api(`/runs/${id}`, { method: "DELETE" }),
};

export const data = {
  schema: () => api("/datasources/schema"),
  sample: (table) => api(`/datasources/tables/${table}/sample`),
  sqlCheck: (sql) => api("/datasources/sql-check", { method: "POST", body: { sql } }),
  documents: () => api("/datasources/documents"),
  providers: () => api("/datasources/providers"),
};

export const insights = {
  summary: () => api("/insights/summary"),
};

export const evaluation = {
  suite: () => api("/evaluation/suite"),
};
