import type { NextConfig } from "next";

// GITHUB_PAGES=true 时产出静态导出（部署到 GitHub Pages 的 /LocalNow 子路径）。
// 不设置时为普通构建（next start / Docker 仍可用）。
const isPages = process.env.GITHUB_PAGES === "true";

const nextConfig: NextConfig = {
  images: { unoptimized: true },
  ...(isPages
    ? { output: "export", basePath: "/LocalNow", assetPrefix: "/LocalNow/", trailingSlash: true }
    : {}),
};

export default nextConfig;
