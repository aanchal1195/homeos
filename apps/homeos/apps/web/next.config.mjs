const api = process.env.API_INTERNAL_URL || 'http://api:8000';
export default {
  async rewrites() { return [
    { source: '/api/:path*', destination: `${api}/api/:path*` },
    { source: '/legacy/:path*', destination: `${api}/:path*` },
  ]; },
};
