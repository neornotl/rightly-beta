-- Rightly context backup for users who explicitly opt in.
-- Run once in the Supabase SQL editor. The browser uses the publishable/anon
-- key; RLS ensures a user can access only their own rows.
create table if not exists public.rightly_context (
  user_id uuid not null references auth.users(id) on delete cascade,
  session_id text not null,
  turns jsonb not null default '[]'::jsonb,
  updated_at timestamptz not null default now(),
  primary key (user_id, session_id)
);

alter table public.rightly_context enable row level security;

revoke all on table public.rightly_context from anon;
grant select, insert, update, delete on table public.rightly_context to authenticated;

drop policy if exists "rightly_context_select_own" on public.rightly_context;
drop policy if exists "rightly_context_insert_own" on public.rightly_context;
drop policy if exists "rightly_context_update_own" on public.rightly_context;
drop policy if exists "rightly_context_delete_own" on public.rightly_context;

create policy "rightly_context_select_own" on public.rightly_context
  for select to authenticated
  using ((select auth.uid()) = user_id);

create policy "rightly_context_insert_own" on public.rightly_context
  for insert to authenticated
  with check ((select auth.uid()) = user_id);

create policy "rightly_context_update_own" on public.rightly_context
  for update to authenticated
  using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);

create policy "rightly_context_delete_own" on public.rightly_context
  for delete to authenticated
  using ((select auth.uid()) = user_id);

-- Retain cloud history for at most 90 days.  The function is not exposed to
-- browser roles: it is for a database-owner cron job only, while RLS still
-- protects all normal browser access above.
create or replace function public.prune_rightly_context()
returns integer
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  removed integer;
begin
  delete from public.rightly_context
  where updated_at < now() - interval '90 days';
  get diagnostics removed = row_count;
  return removed;
end;
$$;

revoke all on function public.prune_rightly_context() from public, anon, authenticated;

-- If pg_cron is already enabled for this Supabase project, schedule the
-- pruning job once per day.  The guarded block is idempotent and simply emits
-- a notice when pg_cron is unavailable or the SQL editor lacks cron rights;
-- in that case, create the equivalent daily job in the Supabase dashboard.
do $$
begin
  if exists (select 1 from pg_extension where extname = 'pg_cron') then
    if not exists (select 1 from cron.job where jobname = 'rightly-context-retention') then
      perform cron.schedule(
        'rightly-context-retention',
        '17 3 * * *',
        'select public.prune_rightly_context();'
      );
    end if;
  else
    raise notice 'pg_cron is not enabled; schedule public.prune_rightly_context() daily for 90-day retention.';
  end if;
exception
  when undefined_table or invalid_schema_name or insufficient_privilege then
    raise notice 'Could not schedule retention automatically; schedule public.prune_rightly_context() daily as database owner.';
end;
$$;
