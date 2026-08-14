import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Pin the workspace root. Without this, Turbopack walks up looking for a
  // lockfile and can land on an unrelated parent directory.
  turbopack: { root: here },
  // Self-contained runtime image for Docker — bundles only the node_modules
  // subset actually reachable from the build, instead of shipping the whole
  // workspace tree into the container.
  output: "standalone",
  // Proxies browser calls to /api/* through to the api container over
  // Docker's internal network. Lets one exposed port (this one) serve both
  // the app and the API regardless of what the public hostname ends up
  // being — no CORS config, no baking a specific domain into the client
  // bundle, no second tunnel route.
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${process.env.MUSE_API_INTERNAL_URL ?? "http://localhost:8000"}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
