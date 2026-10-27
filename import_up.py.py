import os
import csv
import time
import psycopg2
from psycopg2.extras import execute_values
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

CSV_FILE = r"C:\Users\tanus\OneDrive\Desktop\india-village-api\UTTAR_PRADESH_cleaned.csv"

BATCH_SIZE = 1000


def connect():
    print("Connecting to Neon...")
    return psycopg2.connect(
        DATABASE_URL,
        connect_timeout=30,
        keepalives=1,
        keepalives_idle=30,
        keepalives_interval=10,
        keepalives_count=5,
    )


def execute_with_retry(sql, params=None, retries=5):
    for attempt in range(1, retries + 1):
        conn = None
        cur = None

        try:
            conn = connect()
            cur = conn.cursor()

            cur.execute(sql, params)
            result = cur.fetchall() if cur.description else None

            conn.commit()

            return result

        except Exception as e:
            print(f"Database error (attempt {attempt}/{retries}): {e}")

            if conn:
                try:
                    conn.rollback()
                except Exception:
                    pass

            if attempt == retries:
                raise

            time.sleep(3)

        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()


def main():

    print("----------------------------------------")
    print("STARTING UTTAR PRADESH IMPORT")
    print("----------------------------------------")

    # -------------------------------------------------
    # Read CSV
    # -------------------------------------------------

    print("Reading Uttar Pradesh CSV...")

    with open(
        CSV_FILE,
        "r",
        encoding="utf-8-sig",
        newline=""
    ) as file:

        reader = csv.DictReader(file)
        rows = list(reader)

    print(f"UP CSV records found: {len(rows)}")

    if not rows:
        print("ERROR: CSV is empty.")
        return

    # -------------------------------------------------
    # Find/create state
    # -------------------------------------------------

    state_name = "UTTAR PRADESH"
    state_code = int(rows[0]["MDDS STC"])

    result = execute_with_retry(
        '''
        SELECT id
        FROM "State"
        WHERE "stateCode" = %s
        ''',
        (state_code,)
    )

    if result:
        state_id = result[0][0]
        print("Uttar Pradesh already exists.")
    else:

        result = execute_with_retry(
            '''
            INSERT INTO "State" ("stateCode", name)
            VALUES (%s, %s)
            RETURNING id
            ''',
            (state_code, state_name)
        )

        state_id = result[0][0]
        print("Uttar Pradesh created.")

    # -------------------------------------------------
    # Remove ONLY previously imported UP villages
    # -------------------------------------------------

    print("Removing any partially imported UP villages...")

    execute_with_retry(
        '''
        DELETE FROM "Village" v
        USING "SubDistrict" sd
        JOIN "District" d
          ON sd."districtId" = d.id
        WHERE v."subDistrictId" = sd.id
          AND d."stateId" = %s
        ''',
        (state_id,)
    )

    print("Previous partial UP village data removed.")

    # -------------------------------------------------
    # Districts
    # -------------------------------------------------

    print("Processing districts...")

    district_cache = {}

    for row in rows:

        district_code = int(row["MDDS DTC"])
        district_name = row["DISTRICT NAME"].strip()

        if district_code in district_cache:
            continue

        result = execute_with_retry(
            '''
            SELECT id
            FROM "District"
            WHERE "districtCode" = %s
            ''',
            (district_code,)
        )

        if result:
            district_id = result[0][0]
        else:

            result = execute_with_retry(
                '''
                INSERT INTO "District"
                ("districtCode", name, "stateId")
                VALUES (%s, %s, %s)
                RETURNING id
                ''',
                (
                    district_code,
                    district_name,
                    state_id
                )
            )

            district_id = result[0][0]

        district_cache[district_code] = district_id

    print(f"Districts processed: {len(district_cache)}")

    # -------------------------------------------------
    # Sub-districts
    # -------------------------------------------------

    print("Processing sub-districts...")

    subdistrict_cache = {}

    for row in rows:

        district_code = int(row["MDDS DTC"])
        subdistrict_code = int(row["MDDS Sub_DT"])
        subdistrict_name = row["SUB-DISTRICT NAME"].strip()

        if subdistrict_code in subdistrict_cache:
            continue

        district_id = district_cache[district_code]

        result = execute_with_retry(
            '''
            SELECT id
            FROM "SubDistrict"
            WHERE "subDistrictCode" = %s
            ''',
            (subdistrict_code,)
        )

        if result:
            subdistrict_id = result[0][0]
        else:

            result = execute_with_retry(
                '''
                INSERT INTO "SubDistrict"
                ("subDistrictCode", name, "districtId")
                VALUES (%s, %s, %s)
                RETURNING id
                ''',
                (
                    subdistrict_code,
                    subdistrict_name,
                    district_id
                )
            )

            subdistrict_id = result[0][0]

        subdistrict_cache[subdistrict_code] = subdistrict_id

    print(f"Sub-districts processed: {len(subdistrict_cache)}")

    # -------------------------------------------------
    # Prepare village records
    # -------------------------------------------------

    village_records = []

    for row in rows:

        place_code = int(row["MDDS PLCN"])
        village_name = row["Area Name"].strip()
        subdistrict_code = int(row["MDDS Sub_DT"])

        subdistrict_id = subdistrict_cache[subdistrict_code]

        village_records.append(
            (
                place_code,
                village_name,
                subdistrict_id
            )
        )

    print(f"Village records ready: {len(village_records)}")

    # -------------------------------------------------
    # Import villages in small batches
    # -------------------------------------------------

    print("Importing villages...")

    total_imported = 0

    for start in range(0, len(village_records), BATCH_SIZE):

        batch = village_records[start:start + BATCH_SIZE]

        success = False

        for attempt in range(1, 6):

            conn = None
            cur = None

            try:

                conn = connect()
                cur = conn.cursor()

                execute_values(
                    cur,
                    '''
                    INSERT INTO "Village"
                    ("placeCode", name, "subDistrictId")
                    VALUES %s
                    ''',
                    batch,
                    page_size=1000
                )

                conn.commit()

                success = True
                break

            except Exception as e:

                print(
                    f"Batch {start // BATCH_SIZE + 1} "
                    f"failed (attempt {attempt}/5): {e}"
                )

                if conn:
                    try:
                        conn.rollback()
                    except Exception:
                        pass

                time.sleep(5)

            finally:

                if cur:
                    cur.close()

                if conn:
                    conn.close()

        if not success:
            raise RuntimeError(
                f"Failed to import batch starting at row {start}"
            )

        total_imported += len(batch)

        print(
            f"Villages imported: "
            f"{total_imported}/{len(village_records)}"
        )

    # -------------------------------------------------
    # Final verification
    # -------------------------------------------------

    print("----------------------------------------")
    print("VERIFYING UP DATA")
    print("----------------------------------------")

    result = execute_with_retry(
        '''
        SELECT
            COUNT(*)
        FROM "Village" v
        JOIN "SubDistrict" sd
          ON v."subDistrictId" = sd.id
        JOIN "District" d
          ON sd."districtId" = d.id
        JOIN "State" s
          ON d."stateId" = s.id
        WHERE s."stateCode" = %s
        ''',
        (state_code,)
    )

    final_village_count = result[0][0]

    result = execute_with_retry(
        '''
        SELECT COUNT(*)
        FROM "District"
        WHERE "stateId" = %s
        ''',
        (state_id,)
    )

    final_district_count = result[0][0]

    result = execute_with_retry(
        '''
        SELECT COUNT(*)
        FROM "SubDistrict" sd
        JOIN "District" d
          ON sd."districtId" = d.id
        WHERE d."stateId" = %s
        ''',
        (state_id,)
    )

    final_subdistrict_count = result[0][0]

    print("----------------------------------------")
    print("UP IMPORT COMPLETED SUCCESSFULLY")
    print("----------------------------------------")
    print(f"State: {state_name}")
    print(f"Districts: {final_district_count}")
    print(f"Sub-districts: {final_subdistrict_count}")
    print(f"Villages: {final_village_count}")
    print("----------------------------------------")


if __name__ == "__main__":
    main()