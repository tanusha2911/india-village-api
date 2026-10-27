ALTER TABLE "User"
ADD COLUMN "apiKey" TEXT,
ADD COLUMN "apiSecretHash" TEXT;

CREATE UNIQUE INDEX "User_apiKey_key"
ON "User"("apiKey");