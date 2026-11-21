import type { NextConfig } from "next";

// Production: static export served by the FastAPI backend (single port, same origin).
// Development: `npm run dev` proxies /api to the backend on :8000.
const isDev = process.env.NODE_ENV !== "production";
const backend = process.env.RUBINE_BACKEND_URL ?? "http://127.0.0.1:8000";

const config: NextConfig = {
  output: isDev ? undefined : "export",
  trailingSlash: true,
  images: { unoptimized: true },
  poweredByHeader: false,
  reactStrictMode: true,
  ...(isDev
    ? { async rewrites() { return [{ source: "/api/:path*", destination: `${backend}/api/:path*` }]; } }
    : {}),
};

export default config;
