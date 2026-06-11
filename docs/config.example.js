/*
 * Sample app config. Copy to `config.js` and fill in your own Supabase values.
 *   cp config.example.js config.js
 *
 * Use the ANON / PUBLISHABLE key here — NOT the service_role key. A browser app
 * must ship this key for the app to talk to Supabase, and it is safe to do so:
 * Row-Level Security limits the anon key to read-only access. Anyone using the
 * app can see it; that is expected for a client-side Supabase app.
 *
 * NOTE for GitHub Pages: the deployed site serves whatever is committed here, so
 * config.js must contain real values for the live app to work.
 */
window.APP_CONFIG = {
  SUPABASE_URL: "https://YOUR-PROJECT-REF.supabase.co",
  SUPABASE_KEY: "YOUR-SUPABASE-ANON-PUBLISHABLE-KEY",
};
