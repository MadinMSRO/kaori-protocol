-- 1. Enable UUIDs
create extension if not exists "uuid-ossp";

-- 2. THE SILVER LAYER (History & Evidence)
-- Every single verified observation goes here.
create table truth_history (
  id uuid primary key default uuid_generate_v4(),
  truth_key text not null,       -- "earth:flood:h3:8a3..." or "space:luna:healpix:..."
  domain text not null,          -- 'earth', 'ocean', 'space'
  spatial_id text not null,      -- The H3 or HEALPix index
  
  status text check (status in ('PENDING', 'VERIFIED', 'REJECTED')),
  confidence float check (confidence >= 0 and confidence <= 1),
  
  -- The Raw Evidence
  claim_data jsonb not null,     -- { "water_level": 5, "photo": "url..." }
  signature text,                -- The Cryptographic Seal
  
  created_at timestamp with time zone default now()
);

-- 3. THE GOLD LAYER (Current State)
-- The live map. Only the LATEST truth for each hex.
create table truth_states (
  truth_key text primary key,    -- Unique ID per hex
  spatial_id text not null,
  domain text not null,
  
  claim_data jsonb not null,
  updated_at timestamp with time zone default now()
);

-- Indexing for fast map loading
create index idx_spatial on truth_states(spatial_id);
create index idx_domain on truth_states(domain);