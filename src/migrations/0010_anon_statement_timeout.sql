-- The app's vector RPCs run as anon (Supabase default statement_timeout: 3s).
-- Warm-cache they take ~0.2-0.7s, but the FIRST query after the free-tier
-- instance sat idle has to fault the HNSW index + TOASTed vectors back into
-- shared_buffers: measured ~4s end-to-end -> 57014 for the first user.
--
-- Align anon with the 8s Supabase already grants authenticated. RLS keeps
-- anon read-only and PostgREST caps every response at 200 rows (0001), so
-- the extra 5 seconds only buys cold-start headroom, not abuse room.
--
-- Belt-and-braces: the app also retries a failed RPC once (src/docs/app.js),
-- since the failed first attempt is itself what warms the cache.

alter role anon set statement_timeout = '8s';
notify pgrst, 'reload config';
