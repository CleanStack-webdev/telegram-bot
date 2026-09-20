-- Run this once in Supabase: SQL Editor -> New query -> paste -> Run.

create table if not exists public.groups (
    group_id        bigint primary key,               -- Telegram chat id (e.g. -100123...)
    title           text        not null default '',
    chat_type       text        not null default 'supergroup',
    member_count    integer,                          -- count reported by Telegram at last sync
    last_synced_at  timestamptz,
    created_at      timestamptz not null default now(),
    updated_at      timestamptz not null default now()
);

create table if not exists public.members (
    id                bigint generated always as identity primary key,
    telegram_user_id  bigint      not null,           -- the real identity (never the username)
    group_id          bigint      not null references public.groups (group_id) on delete cascade,
    group_title       text,
    first_name        text        not null default '',
    last_name         text,
    username          text,                           -- optional, may change or be null
    is_active         boolean     not null default true,
    discovered_at     timestamptz not null default now(),
    last_seen_at      timestamptz not null default now(),
    updated_at        timestamptz not null default now(),
    constraint members_user_group_unique unique (telegram_user_id, group_id)
);

create index if not exists members_group_active_idx
    on public.members (group_id) where is_active;
create index if not exists members_username_idx
    on public.members (lower(username)) where username is not null;

-- keep updated_at fresh on every UPDATE
create or replace function public.set_updated_at()
returns trigger language plpgsql as $$
begin
    new.updated_at = now();
    return new;
end $$;

drop trigger if exists trg_members_updated_at on public.members;
create trigger trg_members_updated_at before update on public.members
    for each row execute function public.set_updated_at();

drop trigger if exists trg_groups_updated_at on public.groups;
create trigger trg_groups_updated_at before update on public.groups
    for each row execute function public.set_updated_at();

-- Lock the tables down: Row Level Security ON with NO policies means the public
-- (anon/authenticated) API keys can read nothing. Only the server-side service-role
-- key, which bypasses RLS, can access the data.
alter table public.groups  enable row level security;
alter table public.members enable row level security;
