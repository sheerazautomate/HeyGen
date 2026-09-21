// Public configuration only. The Pages build injects repository and pilot limits.
window.SITE_CONFIG = {
  owner: "sheerazautomate",
  repo: "HeyGen",
  pilot: {
    enabled: true,
    per_user_daily: 2,
    global_daily: 10,
    max_html_bytes: 24576,
    max_duration_seconds: 30,
    max_dimension: 1920,
    max_pixels: 2073600,
  },
};
