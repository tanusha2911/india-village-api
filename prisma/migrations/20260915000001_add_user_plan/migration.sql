-- Add plan column to User
ALTER TABLE "User"
ADD COLUMN "plan" TEXT NOT NULL DEFAULT 'FREE';