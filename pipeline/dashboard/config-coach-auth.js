// AI-GENERATED: 2026-03-03T16:57:33Z | pipeline/dashboard/config-coach-auth.js
// Configuration for Hoopla Coach dashboard authentication and API access.
// This file is loaded by the dashboard server at startup.
// Do NOT commit secrets or credentials to this file — use environment variables.

"use strict";

/**
 * Coach API authentication and endpoint configuration.
 *
 * Environment variables take precedence over defaults.
 * In production, all values should be set via environment variables.
 * In development, defaults are provided for local convenience.
 */
const CoachAuthConfig = {
  // API base URL for the coach server
  // Override with COACH_API_URL environment variable in production
  apiBaseUrl: process.env.COACH_API_URL || "http://localhost:3456",

  // Endpoint paths (relative to apiBaseUrl)
  endpoints: {
    chat: "/api/coach",
    reset: "/api/coach/reset",
    commands: "/api/coach/commands",
    health: "/api/health",
    upload: "/api/coach/upload",
  },

  // Request timeout in milliseconds for non-streaming requests
  requestTimeoutMs: parseInt(process.env.COACH_REQUEST_TIMEOUT_MS || "30000", 10),

  // Streaming response timeout in milliseconds (time to first token)
  streamTimeoutMs: parseInt(process.env.COACH_STREAM_TIMEOUT_MS || "60000", 10),

  // Authentication mode
  // Supported values: "none" | "header" | "session"
  // - "none": No authentication required (local/dev only)
  // - "header": Static API key passed as X-Coach-API-Key header
  // - "session": Session cookie from dashboard login flow
  authMode: process.env.COACH_AUTH_MODE || "none",

  // API key for header-based auth (authMode: "header")
  // Must be set via COACH_API_KEY environment variable — never hardcoded
  apiKey: process.env.COACH_API_KEY || null,

  // CORS origin whitelist for the coach API server
  // Comma-separated list of allowed origins
  // Example: "https://dashboard.hoopla.net,https://staging-dashboard.hoopla.net"
  allowedOrigins: (process.env.COACH_ALLOWED_ORIGINS || "http://localhost:3456,http://localhost:8080")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean),

  // Maximum file upload size in bytes (for attachment support)
  maxUploadBytes: parseInt(process.env.COACH_MAX_UPLOAD_BYTES || String(10 * 1024 * 1024), 10), // 10MB default

  // Accepted MIME types for file uploads
  acceptedMimeTypes: [
    "text/plain",
    "text/markdown",
    "application/pdf",
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/webp",
  ],

  // Session configuration (authMode: "session")
  session: {
    cookieName: process.env.COACH_SESSION_COOKIE || "hoopla_coach_session",
    // Session secret — must be set via environment variable in production
    secret: process.env.COACH_SESSION_SECRET || null,
    // Session TTL in seconds
    ttlSeconds: parseInt(process.env.COACH_SESSION_TTL_S || String(8 * 60 * 60), 10), // 8 hours
    secure: process.env.NODE_ENV === "production",
    sameSite: "strict",
  },

  // Health check polling interval in milliseconds (for status indicator in UI)
  healthPollIntervalMs: parseInt(process.env.COACH_HEALTH_POLL_MS || "30000", 10),

  // Demo mode: disables auth, uses demo conversation directory
  // Set COACH_DEMO_MODE=true only for internal demos — not for production
  demoMode: process.env.COACH_DEMO_MODE === "true",
};

/**
 * Validate configuration at startup.
 * Logs warnings for missing production secrets.
 * Throws if critical configuration is missing and required.
 */
function validateCoachAuthConfig(config) {
  const warnings = [];
  const errors = [];

  if (config.authMode === "header") {
    if (!config.apiKey) {
      errors.push(
        "COACH_AUTH_MODE=header requires COACH_API_KEY to be set. " +
          "Set the environment variable before starting the dashboard server."
      );
    }
  }

  if (config.authMode === "session") {
    if (!config.session.secret) {
      errors.push(
        "COACH_AUTH_MODE=session requires COACH_SESSION_SECRET to be set. " +
          "Generate a secure random value: node -e \"console.log(require('crypto').randomBytes(32).toString('hex'))\""
      );
    }
  }

  if (config.authMode === "none" && process.env.NODE_ENV === "production") {
    warnings.push(
      "COACH_AUTH_MODE=none in production environment. " +
        "This means no authentication is enforced on the coach API. " +
        "Set COACH_AUTH_MODE=header or COACH_AUTH_MODE=session for production use."
    );
  }

  if (config.demoMode && process.env.NODE_ENV === "production") {
    warnings.push(
      "COACH_DEMO_MODE=true in production environment. " +
        "Demo mode disables authentication. Ensure this is intentional."
    );
  }

  if (warnings.length > 0) {
    warnings.forEach((w) => console.warn("[coach-auth] WARNING:", w));
  }

  if (errors.length > 0) {
    errors.forEach((e) => console.error("[coach-auth] ERROR:", e));
    throw new Error(
      `Coach auth configuration is invalid. See errors above. (${errors.length} error(s))`
    );
  }
}

/**
 * Build the Authorization header value for a request to the coach API.
 * Returns null if no auth is configured.
 *
 * @param {object} config - CoachAuthConfig
 * @returns {string|null}
 */
function buildAuthHeader(config) {
  if (config.authMode === "header" && config.apiKey) {
    return config.apiKey;
  }
  return null;
}

/**
 * Build default request headers for coach API calls.
 *
 * @param {object} config - CoachAuthConfig
 * @returns {object} Headers object
 */
function buildRequestHeaders(config) {
  const headers = {
    "Content-Type": "application/json",
    Accept: "application/x-ndjson, application/json",
  };

  const authHeader = buildAuthHeader(config);
  if (authHeader) {
    headers["X-Coach-API-Key"] = authHeader;
  }

  return headers;
}

// Validate on module load (fail fast if configuration is invalid)
try {
  validateCoachAuthConfig(CoachAuthConfig);
} catch (err) {
  console.error("[coach-auth] Configuration validation failed:", err.message);
  // In production, exit on invalid configuration.
  // In development, warn but continue.
  if (process.env.NODE_ENV === "production") {
    process.exit(1);
  }
}

module.exports = {
  CoachAuthConfig,
  validateCoachAuthConfig,
  buildAuthHeader,
  buildRequestHeaders,
};
