import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // No `eslint` key: Next 16 removed it from NextConfig and the build errors on unknown properties.
  // Lint is its own gate step.
};

export default nextConfig;
