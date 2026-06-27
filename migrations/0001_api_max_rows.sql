-- Server-side ceiling on the number of rows any single Data API (PostgREST)
-- request may return.
--
-- Defence-in-depth alongside the per-query "limit" values used by the web
-- client (docs/app.js): even a request that forgets its limit, or one issued
-- by a future feature, can never pull the whole table as the dataset grows.
-- Keeps egress and response sizes bounded on the Free plan.
--
-- Equivalent to setting Settings -> API -> "Max rows" in the dashboard.
-- Apply with `supabase db push`, or paste into the dashboard SQL editor.

alter role authenticator set pgrst.db_max_rows = '200';

-- Tell PostgREST to pick up the new configuration without a restart.
notify pgrst, 'reload config';
