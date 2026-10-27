-- These indexes already exist in the database.
-- This migration records them in Prisma's migration history
-- without trying to recreate them.

CREATE INDEX IF NOT EXISTS "village_name_trgm_idx"
ON "Village"
USING gin (name gin_trgm_ops);

CREATE INDEX IF NOT EXISTS "village_subdistrict_idx"
ON "Village" ("subDistrictId");