import type { NextConfig } from "next";

// The browser talks to /api/* on the same origin; Next proxies to FastAPI so the httpOnly
// session cookie is first-party.
const api = process.env.API_INTERNAL_URL ?? "http://localhost:8000";

const config: NextConfig = {
  output: "standalone",
  poweredByHeader: false,
  // gzip would buffer Server-Sent Events from the run viewer; the reverse proxy (Caddy) compresses instead
  compress: false,
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${api}/api/:path*` }];
  },
  async headers() {
    return [
      {
        source: "/(.*)",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "X-Frame-Options", value: "DENY" },
        ],
      },
    ];
  },
};

export default config;
