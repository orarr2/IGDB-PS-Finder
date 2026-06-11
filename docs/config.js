/*
 * Backend configuration for the PlayStation Game Recommender iPhone app.
 *
 * These are PUBLIC, client-safe values:
 *   - The URL is your Supabase project endpoint.
 *   - The key is the *publishable / anon* key. It is meant to be shipped in
 *     clients. Row-Level Security on the `games` table only permits anonymous
 *     READS, so this key cannot modify or delete any data.
 *
 * The data and recommendation logic behind these endpoints are exactly what
 * the IGDB notebook produced (3,840 PS4/PS5 games) — so results are real.
 */
window.APP_CONFIG = {
  SUPABASE_URL: "https://zttqvoqpwtxchxsglard.supabase.co",
  SUPABASE_KEY: "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Inp0dHF2b3Fwd3R4Y2h4c2dsYXJkIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODExMDk0NzQsImV4cCI6MjA5NjY4NTQ3NH0.CU2rcRgQtGcHmwY6thpf-NNKLnb-WtJzzj8WrzxO3Qo",
};
