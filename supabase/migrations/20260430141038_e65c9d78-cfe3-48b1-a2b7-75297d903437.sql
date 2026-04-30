create table public.operation_logs (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz not null default now(),
  client_id uuid null references public.clients(id) on delete cascade,
  record_id uuid null references public.records(id) on delete cascade,
  operation text not null,
  step text null,
  level text not null default 'info',
  message text not null,
  details jsonb null,
  duration_ms integer null
);

create index operation_logs_client_idx on public.operation_logs (client_id, created_at desc);
create index operation_logs_record_idx on public.operation_logs (record_id, created_at desc);
create index operation_logs_created_idx on public.operation_logs (created_at desc);

alter table public.operation_logs enable row level security;

create policy "public read operation_logs" on public.operation_logs for select using (true);
create policy "public write operation_logs" on public.operation_logs for insert with check (true);
create policy "public delete operation_logs" on public.operation_logs for delete using (true);