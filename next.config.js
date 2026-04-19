const nextConfig = {
  output: "export",
  distDir: "out",
  assetPrefix: process.env.NODE_ENV === 'production' ? '' : undefined,
  trailingSlash: true,
  images: { unoptimized: true },
};
module.exports = nextConfig;
