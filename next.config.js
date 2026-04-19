/** @type {import('next').NextConfig} */
const nextConfig = {
  // Static export — Tauri 2 serves from the out/ directory (frontendDist in tauri.conf.json)
  output: "export",

  // Relative asset paths — required for Tauri's custom-protocol (tauri://localhost)
  assetPrefix: "./",

  trailingSlash: true,

  // Image optimisation is unavailable in static export mode
  images: { unoptimized: true },

  // Explicit output directory (matches tauri.conf.json "frontendDist": "../out")
  distDir: "out",

  // Suppress the "x-powered-by" header (Tauri doesn't need it)
  poweredByHeader: false,
};

module.exports = nextConfig;
