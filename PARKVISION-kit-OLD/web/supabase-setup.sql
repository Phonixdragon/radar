-- PARKVISION cloud database setup
-- Run this in the Supabase SQL Editor for your project.
-- This stores bookings in Supabase; it does NOT store personal booking data in GitHub.

create table if not exists public.parking_spots (
  id text primary key,
  label text not null,
  enabled boolean not null default true
);

insert into public.parking_spots (id, label, enabled)
values
  ('A1', 'Bay A1 - Live entrance demo', true),
  ('A2', 'Bay A2 - Display/demo bay', true),
  ('A3', 'Bay A3 - Display/demo bay', true)
on conflict (id) do update set label = excluded.label, enabled = excluded.enabled;

create table if not exists public.parking_bookings (
  id uuid primary key default gen_random_uuid(),
  spot_id text not null references public.parking_spots(id),
  user_id uuid not null references auth.users(id) on delete cascade,
  display_name text not null,
  vehicle_number text not null,
  status text not null default 'reserved'
    check (status in ('reserved', 'checked_in', 'arrived', 'completed', 'cancelled')),
  created_at timestamptz not null default now(),
  checked_in_at timestamptz
);

-- A bay cannot have two active bookings at once.
create unique index if not exists one_active_booking_per_spot
on public.parking_bookings (spot_id)
where status in ('reserved', 'checked_in', 'arrived');

alter table public.parking_spots enable row level security;
alter table public.parking_bookings enable row level security;

grant select on public.parking_spots to anon, authenticated;
grant select on public.parking_bookings to authenticated;
grant insert, update on public.parking_bookings to authenticated;

-- Everyone may see the bay labels, but not other visitors' names or vehicle numbers.
drop policy if exists "spots are public to read" on public.parking_spots;
create policy "spots are public to read"
on public.parking_spots for select
to anon, authenticated
using (enabled = true);

-- A signed-in user can read their own bookings.
drop policy if exists "users read own bookings" on public.parking_bookings;
create policy "users read own bookings"
on public.parking_bookings for select
to authenticated
using (auth.uid() = user_id);

-- Admins can read all bookings. Admin role is stored in app_metadata.
drop policy if exists "admins read all bookings" on public.parking_bookings;
create policy "admins read all bookings"
on public.parking_bookings for select
to authenticated
using ((auth.jwt() -> 'app_metadata' ->> 'role') = 'admin');

-- Users can create reservations only for themselves and only in the reserved state.
drop policy if exists "users create own reservations" on public.parking_bookings;
create policy "users create own reservations"
on public.parking_bookings for insert
to authenticated
with check (
  auth.uid() = user_id
  and status = 'reserved'
  and exists (select 1 from public.parking_spots s where s.id = spot_id and s.enabled = true)
);

-- A user may check in or cancel their own still-reserved booking.
drop policy if exists "users update own reserved booking" on public.parking_bookings;
create policy "users update own reserved booking"
on public.parking_bookings for update
to authenticated
using (auth.uid() = user_id and status = 'reserved')
with check (
  auth.uid() = user_id
  and status in ('reserved', 'checked_in', 'cancelled')
);

-- Admins can operate the admin dashboard and gate-station status updates.
drop policy if exists "admins manage bookings" on public.parking_bookings;
create policy "admins manage bookings"
on public.parking_bookings for all
to authenticated
using ((auth.jwt() -> 'app_metadata' ->> 'role') = 'admin')
with check ((auth.jwt() -> 'app_metadata' ->> 'role') = 'admin');

-- A restricted view exposes only bay ID and booking status, not visitor details.
create or replace view public.parking_status as
select
  s.id as spot_id,
  s.label,
  coalesce(b.status, 'available') as status
from public.parking_spots s
left join public.parking_bookings b
  on b.spot_id = s.id
 and b.status in ('reserved', 'checked_in', 'arrived')
where s.enabled = true;

grant select on public.parking_status to anon, authenticated;

-- Enable database change notifications for the gate station.
do $$
begin
  if exists (select 1 from pg_publication where pubname = 'supabase_realtime')
     and not exists (
       select 1 from pg_publication_tables
       where pubname = 'supabase_realtime'
         and schemaname = 'public'
         and tablename = 'parking_bookings'
     ) then
    alter publication supabase_realtime add table public.parking_bookings;
  end if;
end $$;

-- After creating your admin account in Authentication > Users, run this separately,
-- replacing the email with your own admin account email:
-- update auth.users
-- set raw_app_meta_data = coalesce(raw_app_meta_data, '{}'::jsonb) || '{"role":"admin"}'::jsonb
-- where email = 'YOUR_ADMIN_EMAIL';
-- Then sign out and sign in again so the new role appears in the session.
