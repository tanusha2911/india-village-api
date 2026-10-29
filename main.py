import os
import time
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import psycopg2
from upstash_redis import Redis
from psycopg2.pool import ThreadedConnectionPool
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Depends, Request, Header, BackgroundTasks
from starlette.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.security import APIKeyHeader
from jose import jwt
from pydantic import BaseModel, EmailStr


# ============================================================
# LOAD ENVIRONMENT VARIABLES
# ============================================================

load_dotenv()

redis = Redis(
    url=os.getenv("UPSTASH_REDIS_REST_URL"),
    token=os.getenv("UPSTASH_REDIS_REST_TOKEN")
)

DATABASE_URL = os.getenv("DATABASE_URL")

db_pool = None

RATE_LIMIT = 100

PLAN_RATE_LIMITS = {
    "FREE": 100,
    "PREMIUM": 500,
    "PRO": 2000,
    "UNLIMITED": 5000
}

PLAN_DAILY_LIMITS = {
    "FREE": 5000,
    "PREMIUM": 50000,
    "PRO": 300000,
    "UNLIMITED": 1000000
}
RATE_LIMIT_WINDOW = 60

JWT_SECRET_KEY = os.getenv(
    "JWT_SECRET_KEY",
    "change-this-secret-key"
)

API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")

if not API_KEY or not API_SECRET:
    raise RuntimeError("API_KEY and API_SECRET must be configured in .env")

ALGORITHM = "HS256"
TOKEN_EXPIRE_MINUTES = 60

api_key_header = APIKeyHeader(
    name="X-API-Key",
    scheme_name="API Key",
    auto_error=False
)

# ============================================================
# FASTAPI APP
# ============================================================

app = FastAPI(
    title="India Village API",
    description="REST API for India's village-level geographical data",
    version="1.0.0"
)

@app.on_event("startup")
def startup_db_pool():
    global db_pool

    db_pool = ThreadedConnectionPool(
        minconn=5,
        maxconn=10,
        dsn=DATABASE_URL
    )

    print("STARTUP POOL CREATED:", len(db_pool._pool))

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5174",
        "http://127.0.0.1:5174",
        "https://india-village-api-alpha.vercel.app"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================
# RATE LIMITING
# ============================================================

@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):

    if request.url.path.startswith("/api/"):

        current_time = time.time()

        # Default plan
        plan = "FREE"
        user_id = None

        # Try to identify the user's plan from JWT
        authorization = request.headers.get("Authorization")

        if authorization and authorization.startswith("Bearer "):

            token = authorization.split(" ", 1)[1]

            try:
                payload = jwt.decode(
                    token,
                    JWT_SECRET_KEY,
                    algorithms=[ALGORITHM]
                )

                user_id = payload.get("sub")

                if user_id:
                    plan = payload.get("plan", "FREE").upper()

            except Exception:
                plan = "FREE"

        # Get rate limit for user's plan
        plan_rate_limit = PLAN_RATE_LIMITS.get(
            plan,
            PLAN_RATE_LIMITS["FREE"]
        )

        # Identify the requester
        if user_id:
            rate_limit_key = f"rate_limit:user:{user_id}"
        else:
            client_ip = request.client.host
            rate_limit_key = f"rate_limit:ip:{client_ip}"

        # Redis key stores request count
        redis_count = redis.incr(rate_limit_key)

        # Set expiry only for a new rate-limit window
        if redis_count == 1:
            redis.expire(
                rate_limit_key,
                RATE_LIMIT_WINDOW
            )

        # Check rate limit
        if redis_count > plan_rate_limit:

            ttl = redis.ttl(rate_limit_key)

            return JSONResponse(
                status_code=429,
                content={
                    "success": False,
                    "error": "Rate limit exceeded",
                    "limit": plan_rate_limit,
                    "remaining": 0,
                    "reset": ttl
                }
            )

        # Store rate-limit information for endpoint responses
        request.state.rate_limit = {
            "limit": plan_rate_limit,
            "remaining": max(
                0,
                plan_rate_limit - redis_count
            ),
            "reset": redis.ttl(rate_limit_key)
        }

    return await call_next(request)

# ============================================================
# API KEY SECURITY
# ============================================================

# ============================================================
# API KEY SECURITY
# ============================================================

@app.middleware("http")
async def api_key_middleware(request: Request, call_next):

    public_paths = {
        "/",
        "/health",
        "/docs",
        "/openapi.json",
        "/redoc",
        "/auth/login",
        "/auth/register",
        "/api/states"
    }

    # Public endpoints don't need API key or secret
    if request.url.path in public_paths:
        return await call_next(request)

    # Allow CORS preflight requests
    if request.method == "OPTIONS":
        return await call_next(request)

    # Allow authenticated dashboard/API requests using JWT
    if request.url.path.startswith("/api/"):
        authorization = request.headers.get("Authorization")

        if authorization and authorization.startswith("Bearer "):
            return await call_next(request)
            
    # Allow public read-only geography endpoints
    path = request.url.path

    if request.method == "GET" and (
        path == "/api/states"
        or path.startswith("/api/states/")
        or path.startswith("/api/districts/")
        or path.startswith("/api/subdistricts/")
        or path == "/api/villages/search"
    ):
        return await call_next(request)
        
    # Protect API endpoints
    if request.url.path.startswith("/api/"):

        # Get API key from request
        provided_api_key = request.headers.get("X-API-Key")

        if not provided_api_key:
            return JSONResponse(
                status_code=401,
                content={
                    "success": False,
                    "error": "Missing X-API-Key"
                }
            )

        # Check whether this is a registered B2B API key
        connection = None
        cursor = None

        try:
            connection = get_connection()
            cursor = connection.cursor()

            cursor.execute(
                'SELECT id, "apiSecretHash" FROM "User" WHERE "apiKey" = %s',
                (provided_api_key,)
            )

            b2b_user = cursor.fetchone()

        except Exception as e:
            print("B2B API KEY CHECK ERROR:", e)
            b2b_user = None

        finally:
            if cursor:
                cursor.close()

            if connection:
                db_pool.putconn(connection)

        # Registered B2B API key
        if b2b_user:

            request.state.b2b_user_id = b2b_user[0]

            # Check API secret for write operations
            if request.method in {"POST", "PUT", "PATCH", "DELETE"}:

                provided_api_secret = request.headers.get("X-API-Secret")

                if not provided_api_secret:
                    return JSONResponse(
                        status_code=403,
                        content={
                            "success": False,
                            "error": "Missing X-API-Secret"
                        }
                    )

                # Verify the secret against the stored bcrypt hash
                if not bcrypt.checkpw(
                    provided_api_secret.encode("utf-8"),
                    b2b_user[1].encode("utf-8")
                ):
                    return JSONResponse(
                        status_code=403,
                        content={
                            "success": False,
                            "error": "Invalid API secret"
                        }
                    )

            return await call_next(request)

        # Existing global API key fallback
        if provided_api_key != API_KEY:
            return JSONResponse(
                status_code=401,
                content={
                    "success": False,
                    "error": "Invalid API key"
                }
            )

        # Check global API secret for write operations
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:

            provided_api_secret = request.headers.get("X-API-Secret")

            if not provided_api_secret:
                return JSONResponse(
                    status_code=403,
                    content={
                        "success": False,
                        "error": "Missing X-API-Secret"
                    }
                )

            if provided_api_secret != API_SECRET:
                return JSONResponse(
                    status_code=403,
                    content={
                        "success": False,
                        "error": "Invalid API secret"
                    }
                )

    return await call_next(request)

# ============================================================
# DATABASE CONNECTION
# ============================================================

def get_connection(label="UNKNOWN"):
    global db_pool

    connection_start = time.time()

    if db_pool is None:
        db_pool = ThreadedConnectionPool(
            minconn=5,
            maxconn=10,
            dsn=DATABASE_URL
        )

    print(
        "POOL BEFORE:",
        len(db_pool._used),
        "used /",
        len(db_pool._pool),
        "available |",
        label
    )

    connection = db_pool.getconn()
    print("POOL OBJECT ID:", id(db_pool))
    print("POOL MIN/MAX:", db_pool.minconn, db_pool.maxconn)

    connection_time = round(
        (time.time() - connection_start) * 1000
    )

    print(
        "CONNECTION TIME:",
        connection_time,
        "ms |",
        label
    )

    print(
        "POOL AFTER:",
        len(db_pool._used),
        "used /",
        len(db_pool._pool),
        "available |",
        label
    )

    return connection
# ============================================================
# JWT SECURITY
# ============================================================

security = HTTPBearer()
optional_security = HTTPBearer(auto_error=False)


def create_access_token(user_id: int, email: str, plan: str, role: str):

    expire = datetime.now(timezone.utc) + timedelta(
        minutes=TOKEN_EXPIRE_MINUTES
    )

    payload = {
        "sub": str(user_id),
        "email": email,
        "plan": plan,
        "role": role,
        "exp": expire
    }

    token = jwt.encode(
        payload,
        JWT_SECRET_KEY,
        algorithm=ALGORITHM
    )

    return token


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security)
):

    token = credentials.credentials

    connection = None
    cursor = None

    try:

        payload = jwt.decode(
            token,
            JWT_SECRET_KEY,
            algorithms=[ALGORITHM]
        )

        user_id = payload.get("sub")
        plan = payload.get("plan", "FREE").upper()
        email = payload.get("email")

        if user_id is None or email is None:
            raise HTTPException(
                status_code=401,
                detail="Invalid authentication token"
            )

        connection = get_connection()
        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT "plan", "role"
            FROM "User"
            WHERE id = %s
            """,
            (int(user_id),)
        )

        user = cursor.fetchone()

        if user is None:
            raise HTTPException(
                status_code=401,
                detail="User not found"
            )

        return {
            "id": int(user_id),
            "email": email,
            "plan": user[0],
            "role": user[1]
        }

    except HTTPException:
        raise

    except Exception:

        raise HTTPException(
            status_code=401,
            detail="Invalid or expired token"
        )

    finally:

        if cursor:
            cursor.close()

        if connection:
            db_pool.putconn(connection)

def require_admin(current_user: dict = Depends(get_current_user)):

    if current_user["role"] != "ADMIN":
        raise HTTPException(
            status_code=403,
            detail="Admin access required"
        )

    return current_user

# ============================================================
# ADMIN ANALYTICS
# ============================================================

@app.get("/admin/analytics")
def get_admin_analytics(
    admin_user: dict = Depends(require_admin)
):
    connection = None
    cursor = None

    try:
        connection = get_connection()
        cursor = connection.cursor()

        # Total users
        cursor.execute("""
            SELECT COUNT(*)
            FROM "User"
        """)
        total_users = cursor.fetchone()[0]

        # Total API requests
        cursor.execute("""
            SELECT COUNT(*)
            FROM "ApiUsage"
        """)
        total_requests = cursor.fetchone()[0]

        # Average response time
        cursor.execute("""
            SELECT COALESCE(AVG("responseTime"), 0)
            FROM "ApiUsage"
        """)
        average_response_time = cursor.fetchone()[0]

        # Users by plan
        cursor.execute("""
            SELECT "plan", COUNT(*)
            FROM "User"
            GROUP BY "plan"
            ORDER BY "plan"
        """)
        plan_rows = cursor.fetchall()

        users_by_plan = [
            {
                "plan": row[0],
                "users": row[1]
            }
            for row in plan_rows
        ]

        return {
            "success": True,
            "analytics": {
                "total_users": total_users,
                "total_requests": total_requests,
                "average_response_time": round(
                    float(average_response_time), 2
                ),
                "users_by_plan": users_by_plan
            }
        }

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch admin analytics: {str(e)}"
        )

    finally:

        if cursor:
            cursor.close()

        if connection:
            db_pool.putconn(connection)

# ============================================================
# ADMIN - TOP 10 STATES BY VILLAGE COUNT
# ============================================================

@app.get("/admin/analytics/states")
def get_top_states(
    admin_user: dict = Depends(require_admin)
):
    connection = None
    cursor = None

    try:
        connection = get_connection()
        cursor = connection.cursor()

        cursor.execute("""
            SELECT
                s.name AS state,
                COUNT(v.id) AS villages
            FROM "Village" v
            JOIN "SubDistrict" sd
                ON v."subDistrictId" = sd.id
            JOIN "District" d
                ON sd."districtId" = d.id
            JOIN "State" s
                ON d."stateId" = s.id
            GROUP BY s.name
            ORDER BY villages DESC
            LIMIT 10
        """)

        rows = cursor.fetchall()

        states = [
            {
                "state": row[0],
                "villages": row[1]
            }
            for row in rows
        ]

        return {
            "success": True,
            "states": states
        }

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch state analytics: {str(e)}"
        )

    finally:

        if cursor:
            cursor.close()

        if connection:
            db_pool.putconn(connection)

# ============================================================
# ADMIN - API REQUESTS LAST 30 DAYS
# ============================================================

@app.get("/admin/analytics/requests")
def get_api_requests_last_30_days(
    admin_user: dict = Depends(require_admin)
):
    connection = None
    cursor = None

    try:
        connection = get_connection()
        cursor = connection.cursor()

        cursor.execute("""
            SELECT
                DATE("createdAt") AS request_date,
                COUNT(*) AS requests
            FROM "ApiUsage"
            WHERE "createdAt" >= CURRENT_DATE - INTERVAL '29 days'
            GROUP BY DATE("createdAt")
            ORDER BY request_date
        """)

        rows = cursor.fetchall()

        requests = [
            {
                "date": row[0].isoformat(),
                "requests": row[1]
            }
            for row in rows
        ]

        return {
            "success": True,
            "requests": requests
        }

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch API request analytics: {str(e)}"
        )

    finally:

        if cursor:
            cursor.close()

        if connection:
            db_pool.putconn(connection)

# ============================================================
# ADMIN - RESPONSE TIME TRENDS (P95 / P99)
# ============================================================

@app.get("/admin/analytics/response-time")
def get_response_time_trends(
    admin_user: dict = Depends(require_admin)
):
    connection = None
    cursor = None

    try:
        connection = get_connection()
        cursor = connection.cursor()

        cursor.execute("""
            SELECT
                DATE("createdAt") AS request_date,
                PERCENTILE_CONT(0.95)
                    WITHIN GROUP (ORDER BY "responseTime") AS p95,
                PERCENTILE_CONT(0.99)
                    WITHIN GROUP (ORDER BY "responseTime") AS p99
            FROM "ApiUsage"
            WHERE "createdAt" >= CURRENT_DATE - INTERVAL '29 days'
            GROUP BY DATE("createdAt")
            ORDER BY request_date
        """)

        rows = cursor.fetchall()

        response_times = [
            {
                "date": row[0].isoformat(),
                "p95": round(float(row[1]), 2),
                "p99": round(float(row[2]), 2)
            }
            for row in rows
        ]

        return {
            "success": True,
            "response_times": response_times
        }

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch response time analytics: {str(e)}"
        )

    finally:

        if cursor:
            cursor.close()

        if connection:
            db_pool.putconn(connection)

# ============================================================
# ADMIN - REQUESTS BY ENDPOINT
# ============================================================

@app.get("/admin/analytics/endpoints")
def get_requests_by_endpoint(
    admin_user: dict = Depends(require_admin)
):
    connection = None
    cursor = None

    try:
        connection = get_connection()
        cursor = connection.cursor()

        cursor.execute("""
            SELECT
                "endpoint",
                COUNT(*) AS requests
            FROM "ApiUsage"
            GROUP BY "endpoint"
            ORDER BY requests DESC
        """)

        rows = cursor.fetchall()

        endpoints = [
            {
                "endpoint": row[0],
                "requests": row[1]
            }
            for row in rows
        ]

        return {
            "success": True,
            "endpoints": endpoints
        }

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch endpoint analytics: {str(e)}"
        )

    finally:

        if cursor:
            cursor.close()

        if connection:
            db_pool.putconn(connection)

# ============================================================
# ADMIN - API USAGE BY HOUR
# ============================================================

@app.get("/admin/analytics/hourly")
def get_hourly_usage(
    admin_user: dict = Depends(require_admin)
):
    connection = None
    cursor = None

    try:
        connection = get_connection()
        cursor = connection.cursor()

        cursor.execute("""
            SELECT
                EXTRACT(HOUR FROM "createdAt") AS hour,
                COUNT(*) AS requests
            FROM "ApiUsage"
            GROUP BY EXTRACT(HOUR FROM "createdAt")
            ORDER BY hour
        """)

        rows = cursor.fetchall()

        hourly_usage = [
            {
                "hour": int(row[0]),
                "requests": row[1]
            }
            for row in rows
        ]

        return {
            "success": True,
            "hourly_usage": hourly_usage
        }

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch hourly usage analytics: {str(e)}"
        )

    finally:

        if cursor:
            cursor.close()

        if connection:
            db_pool.putconn(connection)

# ============================================================
# ADMIN - USER MANAGEMENT
# ============================================================

@app.get("/admin/users")
def get_admin_users(
    admin_user: dict = Depends(require_admin)
):
    connection = None
    cursor = None

    try:
        connection = get_connection()
        cursor = connection.cursor()

        cursor.execute("""
            SELECT
                id,
                name,
                email,
                plan,
                role,
                "createdAt"
            FROM "User"
            ORDER BY id DESC
        """)

        rows = cursor.fetchall()

        users = [
            {
                "id": row[0],
                "name": row[1],
                "email": row[2],
                "plan": row[3],
                "role": row[4],
                "created_at": row[5].isoformat()
            }
            for row in rows
        ]

        return {
            "success": True,
            "users": users
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch users: {str(e)}"
        )

    finally:
        if cursor:
            cursor.close()

        if connection:
            db_pool.putconn(connection)

def get_current_or_b2b_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(optional_security)
):
    # JWT user
    if credentials:
        return get_current_user(credentials)

    # B2B API-key user
    b2b_user_id = getattr(request.state, "b2b_user_id", None)

    if b2b_user_id:
        connection = None
        cursor = None

        try:
            connection = get_connection("AUTH_USER")
            cursor = connection.cursor()

            cursor.execute(
                'SELECT id, email, "plan" FROM "User" WHERE id = %s',
                (b2b_user_id,)
            )

            user = cursor.fetchone()

            if user:
                return {
                    "id": user[0],
                    "email": user[1],
                    "plan": user[2]
                }

        finally:
            if cursor:
                cursor.close()

            if connection:
                db_pool.putconn(connection)

    raise HTTPException(
        status_code=401,
        detail="Authentication required"
    )

@app.put("/admin/users/bulk-plan")
def bulk_update_user_plan(
    user_ids: list[int],
    plan: str,
    admin_user: dict = Depends(require_admin)
):
    connection = None
    cursor = None

    try:
        plan = plan.upper()

        if plan not in ["FREE", "PREMIUM"]:
            raise HTTPException(
                status_code=400,
                detail="Plan must be FREE or PREMIUM"
            )

        if not user_ids:
            raise HTTPException(
                status_code=400,
                detail="At least one user ID is required"
            )

        connection = get_connection()
        cursor = connection.cursor()

        cursor.execute(
            """
            UPDATE "User"
            SET "plan" = %s
            WHERE id = ANY(%s)
            """,
            (plan, user_ids)
        )

        updated_count = cursor.rowcount

        connection.commit()

        return {
            "success": True,
            "updated_count": updated_count,
            "plan": plan
        }

    except HTTPException:
        raise

    except Exception as e:
        if connection:
            connection.rollback()

        raise HTTPException(
            status_code=500,
            detail=f"Failed to update user plans: {str(e)}"
        )

    finally:
        if cursor:
            cursor.close()

        if connection:
            db_pool.putconn(connection)

@app.put("/admin/users/{user_id}/role")
def update_user_role(
    user_id: int,
    role: str,
    admin_user: dict = Depends(require_admin)
):
    connection = None
    cursor = None

    try:
        role = role.upper()

        if role not in ["USER", "ADMIN"]:
            raise HTTPException(
                status_code=400,
                detail="Role must be USER or ADMIN"
            )

        connection = get_connection()
        cursor = connection.cursor()

        cursor.execute(
            """
            UPDATE "User"
            SET "role" = %s
            WHERE id = %s
            """,
            (role, user_id)
        )

        if cursor.rowcount == 0:
            raise HTTPException(
                status_code=404,
                detail="User not found"
            )

        connection.commit()

        return {
            "success": True,
            "user_id": user_id,
            "role": role
        }

    except HTTPException:
        raise

    except Exception as e:
        if connection:
            connection.rollback()

        raise HTTPException(
            status_code=500,
            detail=f"Failed to update user role: {str(e)}"
        )

    finally:
        if cursor:
            cursor.close()

        if connection:
            db_pool.putconn(connection)  

@app.delete("/admin/users/{user_id}")
def delete_admin_user(
    user_id: int,
    admin_user: dict = Depends(require_admin)
):
    connection = None
    cursor = None

    try:
        # Prevent admin from deleting their own account
        if user_id == admin_user["id"]:
            raise HTTPException(
                status_code=400,
                detail="You cannot delete your own admin account"
            )

        connection = get_connection()
        cursor = connection.cursor()

        cursor.execute("""
            DELETE FROM "User"
            WHERE id = %s
        """, (user_id,))

        if cursor.rowcount == 0:
            raise HTTPException(
                status_code=404,
                detail="User not found"
            )

        connection.commit()

        return {
            "success": True,
            "message": "User deleted successfully",
            "user_id": user_id
        }

    except HTTPException:
        raise

    except Exception as e:
        if connection:
            connection.rollback()

        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete user: {str(e)}"
        )

    finally:
        if cursor:
            cursor.close()

        if connection:
            db_pool.putconn(connection)          

# ============================================================
# API USAGE TRACKING
# ============================================================

def get_daily_limit(plan: str):
    return PLAN_DAILY_LIMITS.get(
        plan.upper(),
        PLAN_DAILY_LIMITS["FREE"]
    )


def get_today_usage(user_id: int):
    connection = None
    cursor = None

    try:
        connection = get_connection("DAILY_USAGE")
        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT COUNT(*)
            FROM "ApiUsage"
            WHERE "userId" = %s
            AND "createdAt" >= CURRENT_DATE
            """,
            (user_id,)
        )

        return cursor.fetchone()[0]

    except Exception as e:
        print("DAILY USAGE CHECK ERROR:", e)
        return 0

    finally:
        if cursor:
            cursor.close()

        if connection:
            db_pool.putconn(connection)

def check_daily_limit(user_id: int, plan: str):
    daily_limit = get_daily_limit(plan)
    today_usage = get_today_usage(user_id)

    if today_usage >= daily_limit:
        raise HTTPException(
            status_code=429,
            detail=f"Daily API request limit of {daily_limit} reached"
        )

    return {
        "daily_limit": daily_limit,
        "today_usage": today_usage,
        "remaining_requests": daily_limit - today_usage
    }


def record_api_usage(
    user_id: int,
    endpoint: str,
    method: str,
    status_code: int,
    response_time: int
):
    connection = None
    cursor = None

    try:
        connection = get_connection("RECORD_API_USAGE")
        cursor = connection.cursor()

        insert_start = time.time()
        
        cursor.execute(
            """
            INSERT INTO "ApiUsage"
            ("userId", "endpoint", "method", "statusCode", "responseTime")
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                user_id,
                endpoint,
                method,
                status_code,
                response_time
            )
        )
        insert_time = round((time.time() - insert_start) * 1000)
        print("API USAGE INSERT TIME:", insert_time, "ms")

        commit_start = time.time()

        connection.commit()

        commit_time = round((time.time() - commit_start) * 1000)
        print("API USAGE COMMIT TIME:", commit_time, "ms")
        
    except Exception as e:
        print("API USAGE TRACKING ERROR:", e)

    finally:
        if cursor:
            cursor.close()

        if connection:
            db_pool.putconn(connection)


# ============================================================
# REQUEST MODELS
# ============================================================

class RegisterRequest(BaseModel):

    name: str
    email: EmailStr
    password: str


class LoginRequest(BaseModel):

    email: EmailStr
    password: str


# ============================================================
# HOME
# ============================================================

@app.get("/")
def home():

    return {
        "message": "India Village API is running",
        "version": "1.0.0"
    }


# ============================================================
# HEALTH CHECK
# ============================================================

@app.get("/health")
def health_check():

    connection = None
    cursor = None

    try:

        connection = get_connection()
        cursor = connection.cursor()

        cursor.execute("SELECT 1")

        return {
            "status": "healthy",
            "database": "connected"
        }

    except Exception as e:

        return {
            "status": "unhealthy",
            "database": "disconnected",
            "error": str(e)
        }

    finally:

        if cursor:
            cursor.close()

        if connection:
            db_pool.putconn(connection)


# ============================================================
# REGISTER
# ============================================================

@app.post("/auth/register")
def register_user(request: RegisterRequest):

    connection = None
    cursor = None

    try:

        connection = get_connection()
        cursor = connection.cursor()

        # Check whether email already exists

        cursor.execute(
            """
            SELECT id
            FROM "User"
            WHERE email = %s
            """,
            (request.email,)
        )

        existing_user = cursor.fetchone()

        if existing_user:

            raise HTTPException(
                status_code=400,
                detail="Email already registered"
            )

        # Hash password

        password_hash = bcrypt.hashpw(
            request.password.encode("utf-8"),
            bcrypt.gensalt()
        ).decode("utf-8")

        # Insert user

        cursor.execute(
            """
            INSERT INTO "User"
            (
                name,
                email,
                "passwordHash"
            )
            VALUES (%s, %s, %s)
            RETURNING id, name, email
            """,
            (
                request.name,
                request.email,
                password_hash
            )
        )

        user = cursor.fetchone()

        connection.commit()

        return {
            "message": "User registered successfully",
            "user": {
                "id": user[0],
                "name": user[1],
                "email": user[2]
            }
        }

    except HTTPException:

        raise

    except Exception as e:

        if connection:
            connection.rollback()

        raise HTTPException(
            status_code=500,
            detail=f"Registration failed: {str(e)}"
        )

    finally:

        if cursor:
            cursor.close()

        if connection:
            db_pool.putconn(connection)

# ============================================================
# LOGIN
# ============================================================

@app.post("/auth/login")
def login_user(request: LoginRequest):

    connection = None
    cursor = None

    try:

        connection = get_connection()
        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT
                id,
                name,
                email,
                "passwordHash",
                "plan",
                "role"
            FROM "User"
            WHERE email = %s
            """,
            (request.email,)
        )

        user = cursor.fetchone()

        if not user:

            raise HTTPException(
                status_code=401,
                detail="Invalid email or password"
            )

        password_hash = user[3]

        password_valid = bcrypt.checkpw(
            request.password.encode("utf-8"),
            password_hash.encode("utf-8")
        )

        if not password_valid:

            raise HTTPException(
                status_code=401,
                detail="Invalid email or password"
            )

        access_token = create_access_token(
            user[0],
            user[2],
            user[4],
            user[5]
        )

        return {
            "message": "Login successful",
            "access_token": access_token,
            "token_type": "bearer"
        }

    except HTTPException:

        raise

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=f"Login failed: {str(e)}"
        )

    finally:

        if cursor:
            cursor.close()

        if connection:
            db_pool.putconn(connection)

# ============================================================
# USER DASHBOARD
# ============================================================

@app.get("/dashboard/me")
def get_dashboard(
    current_user: dict = Depends(get_current_user)
):

    daily_limit = get_daily_limit(
        current_user["plan"]
    )

    today_usage = get_today_usage(
        current_user["id"]
    )

    return {
        "success": True,

        "user": {
            "id": current_user["id"],
            "email": current_user["email"],
            "plan": current_user["plan"],
            "role": current_user["role"]
        },

        "usage": {
            "today": today_usage,
            "daily_limit": daily_limit,
            "remaining": max(
                0,
                daily_limit - today_usage
            )
        }
    } 

@app.get("/dashboard/usage")
def get_usage_history(
    current_user: dict = Depends(get_current_user)
):
    connection = None
    cursor = None

    try:
        connection = get_connection()
        cursor = connection.cursor()

        cursor.execute("""
            SELECT
                COUNT(*),
                COALESCE(AVG("responseTime"), 0)
            FROM "ApiUsage"
            WHERE "userId" = %s
        """, (current_user["id"],))

        summary = cursor.fetchone()

        cursor.execute("""
            SELECT
                "endpoint",
                "method",
                "statusCode",
                "responseTime",
                "createdAt"
            FROM "ApiUsage"
            WHERE "userId" = %s
            ORDER BY "createdAt" DESC
            LIMIT 20
        """, (current_user["id"],))

        rows = cursor.fetchall()

        return {
            "success": True,
            "summary": {
                "total_requests": summary[0],
                "average_response_time": round(float(summary[1]), 2)
            },
            "recent_requests": [
                {
                    "endpoint": row[0],
                    "method": row[1],
                    "status_code": row[2],
                    "response_time": row[3],
                    "created_at": row[4].isoformat()
                }
                for row in rows
            ]
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch usage history: {str(e)}"
        )

    finally:
        if cursor:
            cursor.close()

        if connection:
            db_pool.putconn(connection)

@app.post("/dashboard/api-credentials")
def generate_api_credentials(
    current_user: dict = Depends(get_current_user)
):
    connection = None
    cursor = None

    try:
        # Generate a unique API key
        api_key = "ivk_" + uuid.uuid4().hex

        # Generate a random API secret
        api_secret = "ivs_" + uuid.uuid4().hex + uuid.uuid4().hex

        # Hash the secret before storing it
        api_secret_hash = bcrypt.hashpw(
            api_secret.encode("utf-8"),
            bcrypt.gensalt()
        ).decode("utf-8")

        connection = get_connection()
        cursor = connection.cursor()

        cursor.execute("""
            UPDATE "User"
            SET "apiKey" = %s,
                "apiSecretHash" = %s
            WHERE id = %s
        """, (
            api_key,
            api_secret_hash,
            current_user["id"]
        ))

        connection.commit()

        return {
            "success": True,
            "message": "API credentials generated successfully",
            "api_key": api_key,
            "api_secret": api_secret
        }

    except Exception as e:
        if connection:
            connection.rollback()

        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate API credentials: {str(e)}"
        )

    finally:
        if cursor:
            cursor.close()

        if connection:
            db_pool.putconn(connection)

# ============================================================
# GET ALL STATES
# ============================================================

@app.get(
    "/api/states",
    summary="Get all Indian states and union territories",
    description="Returns the complete list of states and union territories available in the India Village API."
)
def get_states():
    start_time = time.time()
    connection = None
    cursor = None

    try:
        connection = get_connection()
        cursor = connection.cursor()

        # Check database connection
        ping_start = time.time()
        cursor.execute("SELECT 1")
        cursor.fetchone()

        print(
            "DATABASE PING TIME:",
            round((time.time() - ping_start) * 1000),
            "ms"
        )

        # Fetch states
        query_start = time.time()

        cursor.execute("""
            SELECT
                "stateCode",
                name
            FROM "State"
            ORDER BY name
        """)

        execute_time = round((time.time() - query_start) * 1000)
        print("STATES EXECUTE TIME:", execute_time, "ms")

        fetch_start = time.time()
        rows = cursor.fetchall()

        fetch_time = round((time.time() - fetch_start) * 1000)
        print("STATES FETCH TIME:", fetch_time, "ms")

        response_time = round((time.time() - start_time) * 1000)

        # Get rate-limit information from middleware
        rate_limit_info = getattr(
            connection,
            "rate_limit",
            None
        )

        # Return the response
        return {
            "success": True,
            "count": len(rows),
            "data": [
                {
                    "state_code": row[0],
                    "state_name": row[1]
                }
                for row in rows
            ],
            "meta": {
                "requestId": f"req_{uuid.uuid4().hex[:12]}",
                "responseTime": response_time,
                "rateLimit": {
                    "remaining": (
                        rate_limit_info.get("remaining")
                        if rate_limit_info
                        else None
                    ),
                    "limit": (
                        rate_limit_info.get("limit")
                        if rate_limit_info
                        else None
                    ),
                    "reset": (
                        (
                            datetime.now(timezone.utc)
                            + timedelta(
                                seconds=rate_limit_info["reset"]
                            )
                        ).isoformat()
                        if rate_limit_info
                        and rate_limit_info.get("reset") is not None
                        else None
                    )
                }
            }
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch states: {str(e)}"
        )

    finally:
        if cursor:
            cursor.close()

        if connection:
            db_pool.putconn(connection)


# ============================================================
# GET DISTRICTS BY STATE
# ============================================================

@app.get(
    "/api/states/{state_code}/districts",
    summary="Get districts by state",
    description="Returns all districts belonging to the specified Indian state or union territory."
)
def get_districts(
    state_code: int,
    request: Request,
    current_user: dict = Depends(get_current_or_b2b_user),
    x_api_key: str = Header(None)
):

    start_time = time.time()

    check_daily_limit(
        user_id=current_user["id"],
        plan=current_user["plan"]
    )

    connection = None
    cursor = None

    try:

        connection = get_connection("STATES_QUERY")
        cursor = connection.cursor()

        query_start = time.time()

        cursor.execute(
            """
            SELECT
                d."districtCode",
                d.name
            FROM "District" d
            JOIN "State" s
                ON d."stateId" = s.id
            WHERE s."stateCode" = %s
            ORDER BY d.name
            """,
            (state_code,)
        )

        execute_time = round(
            (time.time() - query_start) * 1000
        )

        fetch_start = time.time()

        rows = cursor.fetchall()

        fetch_time = round(
            (time.time() - fetch_start) * 1000
        )

        print(
            "EXECUTE TIME:",
            execute_time,
            "ms"
        )

        print(
            "FETCH TIME:",
            fetch_time,
            "ms"
        )

        query_time = execute_time + fetch_time

        print(
            "DISTRICT QUERY TIME:",
            query_time,
            "ms"
        )

        response_time = round(
            (time.time() - start_time) * 1000
        )

        rate_limit_info = getattr(
            request.state,
            "rate_limit",
            {
                "remaining": 0,
                "limit": PLAN_RATE_LIMITS.get(
                    current_user["plan"].upper(),
                    PLAN_RATE_LIMITS["FREE"]
                ),
                "reset": None
            }
        )

        b2b_user_id = getattr(
            request.state,
            "b2b_user_id",
            None
        )

        record_api_usage(
            user_id=b2b_user_id if b2b_user_id else current_user["id"],
            endpoint="/api/states/{state_code}/districts",
            method="GET",
            status_code=200,
            response_time=response_time
        )

        return {
            "success": True,

            "count": len(rows),

            "data": [
                {
                    "district_code": row[0],
                    "district_name": row[1]
                }
                for row in rows
            ],

            "meta": {
                "requestId": f"req_{uuid.uuid4().hex[:12]}",

                "responseTime": response_time,

                "rateLimit": {
                    "remaining": rate_limit_info["remaining"],

                    "limit": rate_limit_info["limit"],

                    "reset": (
                        datetime.now(timezone.utc)
                        + timedelta(
                            seconds=rate_limit_info["reset"]
                        )
                    ).isoformat()
                    if rate_limit_info["reset"] is not None
                    else None
                }
            }
        }

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch districts: {str(e)}"
        )

    finally:

        if cursor:
            cursor.close()

        if connection and db_pool:
            connection.rollback()
            db_pool.putconn(connection)

# ============================================================
# GET SUB-DISTRICTS BY DISTRICT
# ============================================================

@app.get(
    "/api/districts/{district_code}/subdistricts",
    summary="Get sub-districts by district",
    description="Returns all sub-districts belonging to the specified district."
)
def get_subdistricts(
    district_code: int,
    request: Request,
    current_user: dict = Depends(get_current_or_b2b_user),
    x_api_key: str = Header(None)
):

    start_time = time.time()

    check_daily_limit(
        user_id=current_user["id"],
        plan=current_user["plan"]
    )

    connection = None
    cursor = None

    try:

        connection = get_connection()
        cursor = connection.cursor()

        query_start = time.time()

        cursor.execute(
            """
            SELECT
                sd."subDistrictCode",
                sd.name
            FROM "SubDistrict" sd
            WHERE sd."districtId" = (
                SELECT id
                FROM "District"
                WHERE "districtCode" = %s
            )
            ORDER BY sd.name
            """,
            (district_code,)
        )

        query_time = round((time.time() - query_start) * 1000)
        print("STATES QUERY TIME:", query_time, "ms")

        execute_time = round(
            (time.time() - query_start) * 1000
        )

        fetch_start = time.time()

        rows = cursor.fetchall()

        fetch_time = round(
            (time.time() - fetch_start) * 1000
        )

        print(
            "SUBDISTRICT FETCH TIME:",
            fetch_time,
            "ms"
        )

        query_time = execute_time + fetch_time

        print(
            "SUBDISTRICT QUERY TIME:",
            query_time,
            "ms"
        )

        response_time = round(
            (time.time() - start_time) * 1000
        )

        rate_limit_info = getattr(
            request.state,
            "rate_limit",
            {
                "remaining": 0,
                "limit": PLAN_RATE_LIMITS.get(
                    current_user["plan"].upper(),
                    PLAN_RATE_LIMITS["FREE"]
                ),
                "reset": None
            }
        )

        b2b_user_id = getattr(
            request.state,
            "b2b_user_id",
            None
        )

        record_api_usage(
            user_id=b2b_user_id if b2b_user_id else current_user["id"],
            endpoint="/api/districts/{district_code}/subdistricts",
            method="GET",
            status_code=200,
            response_time=response_time
        )

        return {
            "success": True,

            "count": len(rows),

            "data": [
                {
                    "subdistrict_code": row[0],
                    "subdistrict_name": row[1]
                }
                for row in rows
            ],

            "meta": {
                "requestId": f"req_{uuid.uuid4().hex[:12]}",

                "responseTime": response_time,

                "rateLimit": {
                    "remaining": rate_limit_info["remaining"],

                    "limit": rate_limit_info["limit"],

                    "reset": (
                        datetime.now(timezone.utc)
                        + timedelta(
                            seconds=rate_limit_info["reset"]
                        )
                    ).isoformat()
                    if rate_limit_info["reset"] is not None
                    else None
                }
            }
        }

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch sub-districts: {str(e)}"
        )

    finally:

        if cursor:
            cursor.close()

        if connection:
            connection.rollback()
            db_pool.putconn(connection)

# ============================================================
# GET VILLAGES BY SUB-DISTRICT
# ============================================================

@app.get(
    "/api/subdistricts/{subdistrict_code}/villages",
    summary="Get villages by sub-district",
    description="Returns paginated villages belonging to the specified sub-district."
)
def get_villages(
    subdistrict_code: int,
    request: Request,
    page: int = 1,
    limit: int = 50,
    current_user: dict = Depends(get_current_or_b2b_user),
    x_api_key: str = Header(None)
):

    start_time = time.time()

    check_daily_limit(
        user_id=current_user["id"],
        plan=current_user["plan"]
    )

    connection = None
    cursor = None

    try:

        if page < 1:
            raise HTTPException(
                status_code=400,
                detail="Page must be greater than or equal to 1"
            )

        if limit < 1 or limit > 100:
            raise HTTPException(
                status_code=400,
                detail="Limit must be between 1 and 100"
            )

        offset = (page - 1) * limit

        connection = get_connection()
        cursor = connection.cursor()

        query_start = time.time()

        cursor.execute(
            """
            SELECT
                v."placeCode",
                v.name
            FROM "Village" v
            WHERE v."subDistrictId" = (
                SELECT id
                FROM "SubDistrict"
                WHERE "subDistrictCode" = %s
            )
            ORDER BY v.name
            LIMIT %s
            OFFSET %s
            """,
            (
                subdistrict_code,
                limit,
                offset
            )
        )

        execute_time = round(
            (time.time() - query_start) * 1000
        )

        fetch_start = time.time()

        rows = cursor.fetchall()

        fetch_time = round(
            (time.time() - fetch_start) * 1000
        )

        print(
            "VILLAGE EXECUTE TIME:",
            execute_time,
            "ms"
        )

        print(
            "VILLAGE FETCH TIME:",
            fetch_time,
            "ms"
        )

        query_time = execute_time + fetch_time

        print(
            "VILLAGE QUERY TIME:",
            query_time,
            "ms"
        )

        response_time = round(
            (time.time() - start_time) * 1000
        )

        rate_limit_info = getattr(
            request.state,
            "rate_limit",
            {
                "remaining": 0,
                "limit": PLAN_RATE_LIMITS.get(
                    current_user["plan"].upper(),
                    PLAN_RATE_LIMITS["FREE"]
                ),
                "reset": None
            }
        )

        b2b_user_id = getattr(
            request.state,
            "b2b_user_id",
            None
        )

        record_api_usage(
            user_id=b2b_user_id if b2b_user_id else current_user["id"],
            endpoint="/api/subdistricts/{subdistrict_code}/villages",
            method="GET",
            status_code=200,
            response_time=response_time
        )

        return {
            "success": True,

            "count": len(rows),

            "page": page,

            "limit": limit,

            "data": [
                {
                    "place_code": row[0],
                    "village_name": row[1]
                }
                for row in rows
            ],

            "meta": {
                "requestId": f"req_{uuid.uuid4().hex[:12]}",

                "responseTime": response_time,

                "rateLimit": {
                    "remaining": rate_limit_info["remaining"],

                    "limit": rate_limit_info["limit"],

                    "reset": (
                        datetime.now(timezone.utc)
                        + timedelta(
                            seconds=rate_limit_info["reset"]
                        )
                    ).isoformat()
                    if rate_limit_info["reset"] is not None
                    else None
                }
            }
        }

    except HTTPException:
        raise

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch villages: {str(e)}"
        )

    finally:

        if cursor:
            cursor.close()

        if connection and db_pool:
            connection.rollback()
            db_pool.putconn(connection)

# ============================================================
# SEARCH VILLAGES WITH PAGINATION
# ============================================================

@app.get(
    "/api/villages/search",
    summary="Search villages",
    description="Searches Indian villages by name with pagination and returns their sub-district, district, and state information."
)
def search_villages(
    q: str,
    page: int = 1,
    limit: int = 10,
    request: Request = None,
    current_user: dict = Depends(get_current_or_b2b_user),
    x_api_key: str = Header(None)
):

    start_time = time.time()

    check_daily_limit(
        user_id=current_user["id"],
        plan=current_user["plan"]
    )

    # --------------------------------------------------------
    # Validate search query
    # --------------------------------------------------------

    if len(q.strip()) < 2:

        raise HTTPException(
            status_code=400,
            detail="Search query must contain at least 2 characters"
        )

    # --------------------------------------------------------
    # Validate page
    # --------------------------------------------------------

    if page < 1:

        raise HTTPException(
            status_code=400,
            detail="Page must be greater than or equal to 1"
        )

    # --------------------------------------------------------
    # Validate limit
    # --------------------------------------------------------

    if limit < 1 or limit > 50:

        raise HTTPException(
            status_code=400,
            detail="Limit must be between 1 and 50"
        )

    # Calculate offset

    offset = (page - 1) * limit

    connection = None
    cursor = None

    try:

        connection = get_connection()
        cursor = connection.cursor()

        print("SEARCH QUERY:", q)
        print("PAGE:", page)
        print("LIMIT:", limit)
        print("OFFSET:", offset)

        # ----------------------------------------------------
        # STEP 1: Get total matching villages
        # ----------------------------------------------------

        cursor.execute(
            """
            SELECT COUNT(*)
            FROM "Village" v
            WHERE v.name ILIKE %s
            """,
            (f"%{q}%",)
        )

        total = cursor.fetchone()[0]

        # ----------------------------------------------------
        # STEP 2: Get requested page of results
        # ----------------------------------------------------

        cursor.execute(
            """
            SELECT
                v."placeCode",
                v.name,
                sd.name,
                d.name,
                s.name
            FROM "Village" v

            JOIN "SubDistrict" sd
                ON v."subDistrictId" = sd.id

            JOIN "District" d
                ON sd."districtId" = d.id

            JOIN "State" s
                ON d."stateId" = s.id

            WHERE v.name ILIKE %s

            ORDER BY v.name

            LIMIT %s
            OFFSET %s
            """,
            (
                f"%{q}%",
                limit,
                offset
            )
        )

        rows = cursor.fetchall()

        response_time = round(
            (time.time() - start_time) * 1000
        )

        # ----------------------------------------------------
        # STEP 3: Get Redis rate-limit information
        # ----------------------------------------------------

        rate_limit_info = getattr(
            request.state,
            "rate_limit",
            {
                "remaining": 0,
                "limit": PLAN_RATE_LIMITS.get(
                    current_user["plan"].upper(),
                    PLAN_RATE_LIMITS["FREE"]
                ),
                "reset": None
            }
        )

        record_api_usage(
            user_id=current_user["id"],
            endpoint="/api/villages/search",
            method="GET",
            status_code=200,
            response_time=response_time
        )

        # ----------------------------------------------------
        # STEP 4: Return paginated response
        # ----------------------------------------------------

        return {
            "success": True,

            "count": len(rows),

            "data": [
                {
                    "place_code": row[0],
                    "village_name": row[1],
                    "subdistrict_name": row[2],
                    "district_name": row[3],
                    "state_name": row[4]
                }
                for row in rows
            ],

            "meta": {
                "requestId": f"req_{uuid.uuid4().hex[:12]}",

                "responseTime": response_time,

                "page": page,

                "limit": limit,

                "total": total,

                "rateLimit": {
                    "remaining": rate_limit_info["remaining"],

                    "limit": rate_limit_info["limit"],

                    "reset": (
                        datetime.now(timezone.utc)
                        + timedelta(
                            seconds=rate_limit_info["reset"]
                        )
                    ).isoformat()
                    if rate_limit_info["reset"] is not None
                    else None
                }
            }
        }

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=f"Village search failed: {str(e)}"
        )

    finally:

        if cursor:
            cursor.close()

        if connection:
            db_pool.putconn(connection)
