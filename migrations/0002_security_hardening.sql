-- Security hardening: pin a fixed search_path on the API-facing functions.
--
-- The Supabase database linter flags these functions as having a "role mutable
-- search_path" (lint 0011). Without a fixed search_path, a caller can change
-- which schema an unqualified name resolves to, which is a privilege-escalation
-- vector. Pinning search_path closes that.
--
-- `public` is kept in the path on purpose so functions that rely on the pg_trgm
-- operators/functions (installed in public) keep working unchanged. `pg_temp`
-- is placed last, per Postgres guidance.
--
-- This uses ALTER FUNCTION (not CREATE OR REPLACE), so the function bodies are
-- left exactly as-is. The loop matches every overload by oid, so it works
-- regardless of each function's argument signature.
--
-- Apply with `supabase db push`, or paste into the dashboard SQL editor.

do $$
declare
  r record;
begin
  for r in
    select p.oid::regprocedure as sig
    from pg_proc p
    join pg_namespace n on n.oid = p.pronamespace
    where n.nspname = 'public'
      and p.proname in (
        'search_games',
        'get_recommendations',
        'get_visual_recommendations',
        'get_hidden_gems'
      )
  loop
    execute format('alter function %s set search_path = public, pg_temp;', r.sig);
    raise notice 'search_path pinned on %', r.sig;
  end loop;
end $$;
