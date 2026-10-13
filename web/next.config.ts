import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async headers() {
    return [{
      source: '/visual-assets/:path*',
      // The sandbox has an opaque origin; public module imports need CORS.
      headers: [{ key: 'Access-Control-Allow-Origin', value: '*' }],
    }];
  },
};

export default nextConfig;
