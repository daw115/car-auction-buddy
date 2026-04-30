
create table public.clients (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  contact text,
  notes text,
  created_at timestamptz not null default now()
);

create table public.records (
  id uuid primary key default gen_random_uuid(),
  client_id uuid references public.clients(id) on delete cascade,
  title text,
  status text not null default 'draft',
  criteria jsonb not null default '{}'::jsonb,
  listings jsonb not null default '[]'::jsonb,
  ai_input jsonb,
  ai_prompt text,
  analysis jsonb,
  report_html text,
  mail_html text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index records_client_id_idx on public.records(client_id);
create index records_created_at_idx on public.records(created_at desc);

create table public.app_config (
  id int primary key default 1,
  use_mock_data boolean not null default false,
  ai_analysis_mode text not null default 'anthropic',
  filter_seller_insurance_only boolean not null default true,
  min_auction_window_hours int not null default 12,
  max_auction_window_hours int not null default 120,
  collect_all_prefiltered_results boolean not null default true,
  open_all_prefiltered_details boolean not null default true,
  updated_at timestamptz not null default now(),
  constraint app_config_singleton check (id = 1)
);
insert into public.app_config (id) values (1);

alter table public.clients enable row level security;
alter table public.records enable row level security;
alter table public.app_config enable row level security;

-- Single-operator panel: anonymous full access (per user requirement, no auth)
create policy "public read clients"  on public.clients for select using (true);
create policy "public write clients" on public.clients for insert with check (true);
create policy "public update clients" on public.clients for update using (true) with check (true);
create policy "public delete clients" on public.clients for delete using (true);

create policy "public read records"  on public.records for select using (true);
create policy "public write records" on public.records for insert with check (true);
create policy "public update records" on public.records for update using (true) with check (true);
create policy "public delete records" on public.records for delete using (true);

create policy "public read app_config"  on public.app_config for select using (true);
create policy "public update app_config" on public.app_config for update using (true) with check (true);
