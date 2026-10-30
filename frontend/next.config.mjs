// Static export only (ADR-007): no Server Actions, cookies(), headers(), rewrites, redirects,
// proxy/middleware, ISR or Request-reading route handlers. All data is fetched client-side from
// the Python API; security headers (incl. CSP) are set by nginx (infra/nginx/cloud-doctor.conf).
/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'export',
  trailingSlash: true,
  images: { unoptimized: true },
  reactStrictMode: true,
  poweredByHeader: false,
};

export default nextConfig;
