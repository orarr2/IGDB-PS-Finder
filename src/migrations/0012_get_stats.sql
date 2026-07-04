-- One-round-trip stats for the home screen's "ABOUT THE DATA" block.
-- Until now only the games total was fetched live; release years, upcoming
-- and photo-searchable were hardcoded in index.html and drifted (the page
-- showed 343 upcoming / years up to 2026 while the data said 315 / 2028).
--
-- Counts run as the calling role, so the anon read-only policies apply;
-- everything here is a few small scans over ~7k / ~19k rows - milliseconds.

create or replace function public.get_stats()
returns table(
  games bigint,
  min_year integer,
  max_year integer,
  upcoming bigint,
  photo_searchable bigint
)
language sql
stable
set search_path to 'public', 'pg_temp'
as $function$
  select
    (select count(*) from public.games),
    (select min(release_year) from public.games where release_year is not null),
    (select max(release_year) from public.games where release_year is not null),
    (select count(*) from public.games where release_date > now()),
    (select count(distinct game_id) from public.game_clip_oss);
$function$;
