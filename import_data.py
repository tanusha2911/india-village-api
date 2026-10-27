import pandas as pd
import psycopg2
import os
from dotenv import load_dotenv
from psycopg2.extras import execute_values

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

print("Connecting to Neon...")

conn = psycopg2.connect(DATABASE_URL)
cur = conn.cursor()

print("Connected successfully!")

# Load CSV
csv_file = "india_villages_master_cleaned.csv"
df = pd.read_csv(csv_file)

print(f"CSV loaded: {len(df):,} records")

# -------------------------------------------------
# GET ALL SUB-DISTRICT IDs ONCE
# -------------------------------------------------

print("Loading sub-district IDs...")

cur.execute("""
    SELECT "subDistrictCode", "id"
    FROM "SubDistrict"
""")

subdistrict_map = dict(cur.fetchall())

print(f"Sub-district IDs loaded: {len(subdistrict_map):,}")

# -------------------------------------------------
# CLEAR VILLAGES
# -------------------------------------------------

print("Clearing existing village records...")

cur.execute('TRUNCATE TABLE "Village" RESTART IDENTITY')
conn.commit()

print("Village table cleared.")

# -------------------------------------------------
# PREPARE VILLAGES
# -------------------------------------------------

villages = []

for _, row in df.iterrows():

    place_code = row["MDDS PLCN"]
    village_name = row["Area Name"]
    subdistrict_code = row["MDDS Sub_DT"]

    # Skip invalid/missing records
    if pd.isna(place_code):
        continue

    if pd.isna(village_name):
        continue

    if pd.isna(subdistrict_code):
        continue

    place_code = int(place_code)
    subdistrict_code = int(subdistrict_code)

    subdistrict_id = subdistrict_map.get(subdistrict_code)

    if subdistrict_id is None:
        continue

    villages.append(
        (
            place_code,
            str(village_name).strip(),
            subdistrict_id
        )
    )

print(f"Valid villages ready: {len(villages):,}")

# -------------------------------------------------
# BULK INSERT
# -------------------------------------------------

batch_size = 5000

for start in range(0, len(villages), batch_size):

    batch = villages[start:start + batch_size]

    execute_values(
        cur,
        """
        INSERT INTO "Village"
        ("placeCode", "name", "subDistrictId")
        VALUES %s
        """,
        batch
    )

    conn.commit()

    completed = min(start + batch_size, len(villages))

    print(
        f"Villages imported: "
        f"{completed:,} / {len(villages):,}"
    )

# -------------------------------------------------
# FINISH
# -------------------------------------------------

cur.close()
conn.close()

print()
print("======================================")
print("DATA IMPORT COMPLETED SUCCESSFULLY")
print("======================================")