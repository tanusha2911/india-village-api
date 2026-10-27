import os
import pandas as pd
import psycopg2
from psycopg2.extras import execute_values
from dotenv import load_dotenv

load_dotenv()

CSV_FILE = "missing_2011_states_cleaned.csv"
TARGET_STATE_CODES = [1, 4, 5, 7, 14]
BATCH_SIZE = 1000

print("----------------------------------------")
print("STARTING MISSING 2011 STATES IMPORT")
print("----------------------------------------")

if not os.path.exists(CSV_FILE):
    raise FileNotFoundError(f"Missing file: {CSV_FILE}")

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL not found in .env")

print("Reading cleaned CSV...")
df = pd.read_csv(CSV_FILE)
print(f"Records found: {len(df)}")

required = [
    "MDDS STC", "STATE NAME", "MDDS DTC", "DISTRICT NAME",
    "MDDS Sub_DT", "SUB-DISTRICT NAME", "MDDS PLCN", "Area Name"
]
missing = [c for c in required if c not in df.columns]
if missing:
    raise RuntimeError(f"Missing CSV columns: {missing}")

# Clean text and numeric fields.
for col in ["STATE NAME", "DISTRICT NAME", "SUB-DISTRICT NAME", "Area Name"]:
    df[col] = df[col].fillna("").astype(str).str.strip()

for col in ["MDDS STC", "MDDS DTC", "MDDS Sub_DT", "MDDS PLCN"]:
    df[col] = pd.to_numeric(df[col], errors="raise").astype(int)

if df[["STATE NAME", "DISTRICT NAME", "SUB-DISTRICT NAME", "Area Name"]].eq("").any().any():
    raise RuntimeError("Blank hierarchy/name value found in cleaned CSV")

if set(df["MDDS STC"].unique()) != set(TARGET_STATE_CODES):
    raise RuntimeError(
        f"Unexpected state codes: {sorted(df['MDDS STC'].unique())}"
    )

conn = psycopg2.connect(DATABASE_URL)
conn.autocommit = False

try:
    cur = conn.cursor()

    print("Removing any previous partial imports for these 2011 states...")
    cur.execute(
        '''
        DELETE FROM "Village" v
        USING "SubDistrict" sd, "District" d, "State" s
        WHERE v."subDistrictId" = sd.id
          AND sd."districtId" = d.id
          AND d."stateId" = s.id
          AND s."stateCode" = ANY(%s)
        ''',
        (TARGET_STATE_CODES,)
    )

    cur.execute(
        '''
        DELETE FROM "SubDistrict" sd
        USING "District" d, "State" s
        WHERE sd."districtId" = d.id
          AND d."stateId" = s.id
          AND s."stateCode" = ANY(%s)
        ''',
        (TARGET_STATE_CODES,)
    )

    cur.execute(
        '''
        DELETE FROM "District" d
        USING "State" s
        WHERE d."stateId" = s.id
          AND s."stateCode" = ANY(%s)
        ''',
        (TARGET_STATE_CODES,)
    )

    cur.execute(
        'DELETE FROM "State" WHERE "stateCode" = ANY(%s)',
        (TARGET_STATE_CODES,)
    )

    # States
    states = (
        df[["MDDS STC", "STATE NAME"]]
        .drop_duplicates()
        .sort_values("MDDS STC")
        .itertuples(index=False, name=None)
    )
    execute_values(
        cur,
        '''
        INSERT INTO "State" ("stateCode", name)
        VALUES %s
        ON CONFLICT ("stateCode") DO UPDATE SET name = EXCLUDED.name
        ''',
        list(states)
    )
    print("States processed: 5")

    # Districts
    districts = (
        df[["MDDS STC", "MDDS DTC", "DISTRICT NAME"]]
        .drop_duplicates()
    )
    district_values = []
    for stc, dtc, name in districts.itertuples(index=False, name=None):
        district_values.append((int(dtc), name, int(stc)))

    execute_values(
        cur,
        '''
        INSERT INTO "District" ("districtCode", name, "stateId")
        SELECT x.district_code, x.name, s.id
        FROM (VALUES %s) AS x(district_code, name, state_code)
        JOIN "State" s ON s."stateCode" = x.state_code
        ON CONFLICT ("districtCode") DO UPDATE SET
            name = EXCLUDED.name,
            "stateId" = EXCLUDED."stateId"
        ''',
        district_values
    )
    print(f"Districts processed: {len(district_values)}")

    # Sub-districts
    subdistricts = (
        df[["MDDS STC", "MDDS DTC", "MDDS Sub_DT", "SUB-DISTRICT NAME"]]
        .drop_duplicates()
    )
    sd_values = []
    for stc, dtc, sdt, name in subdistricts.itertuples(index=False, name=None):
        sd_values.append((int(sdt), name, int(dtc)))

    execute_values(
        cur,
        '''
        INSERT INTO "SubDistrict" ("subDistrictCode", name, "districtId")
        SELECT x.subdistrict_code, x.name, d.id
        FROM (VALUES %s) AS x(subdistrict_code, name, district_code)
        JOIN "District" d ON d."districtCode" = x.district_code
        ON CONFLICT ("subDistrictCode") DO UPDATE SET
            name = EXCLUDED.name,
            "districtId" = EXCLUDED."districtId"
        ''',
        sd_values
    )
    print(f"Sub-districts processed: {len(sd_values)}")

    # Villages
    village_values = [
        (int(row["MDDS PLCN"]), row["Area Name"], int(row["MDDS Sub_DT"]))
        for _, row in df.iterrows()
    ]

    print("Importing villages...")
    for start in range(0, len(village_values), BATCH_SIZE):
        batch = village_values[start:start + BATCH_SIZE]
        execute_values(
            cur,
            '''
            INSERT INTO "Village" ("placeCode", name, "subDistrictId")
            SELECT x.place_code, x.name, sd.id
            FROM (VALUES %s) AS x(place_code, name, subdistrict_code)
            JOIN "SubDistrict" sd
              ON sd."subDistrictCode" = x.subdistrict_code
            ''',
            batch
        )
        if (start + len(batch)) % 5000 == 0 or start + len(batch) == len(village_values):
            print(f"Villages imported: {start + len(batch)}/{len(village_values)}")

    conn.commit()

    print("----------------------------------------")
    print("VERIFYING IMPORT")
    print("----------------------------------------")

    cur.execute(
        '''
        SELECT
            COUNT(DISTINCT s.id),
            COUNT(DISTINCT d.id),
            COUNT(DISTINCT sd.id),
            COUNT(v.id)
        FROM "State" s
        LEFT JOIN "District" d ON d."stateId" = s.id
        LEFT JOIN "SubDistrict" sd ON sd."districtId" = d.id
        LEFT JOIN "Village" v ON v."subDistrictId" = sd.id
        WHERE s."stateCode" = ANY(%s)
        ''',
        (TARGET_STATE_CODES,)
    )
    states, districts_count, subdistricts_count, villages = cur.fetchone()

    print(f"States: {states}")
    print(f"Districts: {districts_count}")
    print(f"Sub-districts: {subdistricts_count}")
    print(f"Villages: {villages}")
    print("----------------------------------------")
    print("MISSING 2011 STATES IMPORT COMPLETED")
    print("----------------------------------------")

except Exception:
    conn.rollback()
    raise
finally:
    conn.close()
