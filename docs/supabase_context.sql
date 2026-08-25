-- Rightly context backup for signed-in users.
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
