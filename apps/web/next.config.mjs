import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Pin the workspace root. Without this, Turbopack walks up looking for a
  // lockfile and can land on an unrelated parent directory.
  turbopack: { root: here },
};

export default nextConfig;
