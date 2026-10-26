


import json
from datetime import datetime, date
from pathlib import Path
from typing import Optional, Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

# --------------------------------------------------
# CONFIGURATION
# --------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent

# Add your JSON data files here.
# If your actual filenames have different extensions,
# update these paths accordingly.
TENDER_FILES = [
    BASE_DIR / "tenders.json",
    BASE_DIR / "tenders_1.json",
]

app = FastAPI(
    title="Government Tender Tracking API",
    description=(
        "Search, filter, summarize, and refresh "
        "government tender opportunities."
    ),
    version="2.0.0",
)
import os
from fastapi.middleware.cors import CORSMiddleware

allowed_origins = [
    origin.strip()
    for origin in os.getenv("FRONTEND_URL", "http://localhost:5173").split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://gvt-inf-f-z3l9-l5rle93yi-owaisimam3542s-projects.vercel.app",
        "http://localhost:5173",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=allowed_origins,
#     allow_credentials=False,
#     allow_methods=["GET", "POST", "OPTIONS"],
#     allow_headers=["*"],
# )
# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=[
#         "http://localhost:5173",
#         "http://127.0.0.1:5173",
#     ],
#     allow_credentials=True,
#     allow_methods=["*"],
#     allow_headers=["*"],
# )


# --------------------------------------------------
# DATE AND STATUS HELPERS
# --------------------------------------------------

def parse_deadline(value: Any) -> Optional[date]:
    """Parse common tender deadline formats."""
    if not value:
        return None

    text = str(value).strip()

    formats = [
        "%d-%m-%Y",
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
    ]

    for fmt in formats:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue

    try:
        return datetime.fromisoformat(
            text.replace("Z", "+00:00")
        ).date()
    except ValueError:
        return None


def determine_status(tender: dict) -> str:
    """Determine status from the submission deadline."""
    deadline_value = (
        tender.get("submission_deadline")
        or tender.get("deadline")
        or tender.get("end_date")
        or tender.get("bid_end_date")
    )

    deadline = parse_deadline(deadline_value)

    if deadline:
        # A tender with today's deadline remains open today.
        return "Open" if deadline >= date.today() else "Expired"

    existing = str(tender.get("status", "")).strip().casefold()

    if existing in {"open", "active", "published"}:
        return "Open"

    if existing in {"expired", "closed", "completed"}:
        return "Expired"

    return "Unknown"


# --------------------------------------------------
# DATA LOADING
# --------------------------------------------------

def read_tender_file(file_path: Path) -> list:
    """Load a JSON file containing a list of tenders."""
    if not file_path.exists():
        return []

    try:
        with file_path.open("r", encoding="utf-8") as file:
            data = json.load(file)

        # Support either a raw JSON list or {"tenders": [...]}.
        if isinstance(data, dict):
            data = data.get("tenders", [])

        if not isinstance(data, list):
            raise HTTPException(
                status_code=500,
                detail=f"{file_path.name} must contain a JSON list.",
            )

        return [
            item for item in data
            if isinstance(item, dict)
        ]

    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"{file_path.name} contains invalid JSON.",
        ) from exc

    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Could not read {file_path.name}.",
        ) from exc


def load_tenders() -> list:
    """Load, normalize, and deduplicate all configured files."""
    combined = []
    seen_ids = set()

    for file_path in TENDER_FILES:
        for original in read_tender_file(file_path):
            tender = dict(original)

            tender_id = str(
                tender.get("tender_id")
                or tender.get("id")
                or ""
            ).strip()

            if tender_id:
                if tender_id in seen_ids:
                    continue
                seen_ids.add(tender_id)

            tender["status"] = determine_status(tender)

            # Standardize important fields for the frontend.
            tender.setdefault("tender_id", tender_id or "N/A")
            tender.setdefault("title", "Untitled tender")
            tender.setdefault("organization", "Not specified")
            tender.setdefault("submission_deadline", (
                tender.get("deadline")
                or tender.get("end_date")
                or tender.get("bid_end_date")
                or "Not specified"
            ))
            tender.setdefault("start_date", "Not specified")
            tender.setdefault("source", "Local JSON")

            combined.append(tender)

    return combined


# --------------------------------------------------
# SUMMARY
# --------------------------------------------------

def build_summary(tenders: list) -> dict:
    today = date.today()

    deadlines = [
        parse_deadline(
            tender.get("submission_deadline")
            or tender.get("deadline")
            or tender.get("end_date")
        )
        for tender in tenders
    ]

    upcoming = sum(
        1 for deadline in deadlines
        if deadline is not None and deadline >= today
    )

    return {
        "total_tenders": len(tenders),
        "open_tenders": sum(
            t.get("status") == "Open" for t in tenders
        ),
        "expired_tenders": sum(
            t.get("status") == "Expired" for t in tenders
        ),
        "unknown_status_tenders": sum(
            t.get("status") == "Unknown" for t in tenders
        ),
        "upcoming_deadlines": upcoming,
        "data_files": [
            file.name for file in TENDER_FILES if file.exists()
        ],
        "generated_at": datetime.now().astimezone().isoformat(),
    }


# --------------------------------------------------
# API ROUTES
# --------------------------------------------------

@app.get("/")
def home():
    return {
        "message": "Government Tender Tracking API is running!",
        "project": "Government Tender Tracking Application",
        "version": "2.0.0",
        "status": "success",
        "docs": "/docs",
        "endpoints": [
            "/health",
            "/api/tenders",
            "/api/summary",
            "/api/refresh",
        ],
    }


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "service": "tender-tracker-backend",
    }


@app.get("/api/tenders")
def get_tenders(
    search: Optional[str] = Query(
        default=None,
        description="Search tender ID, title, or organization",
    ),
    status: Optional[str] = Query(
        default=None,
        description="Filter by Open, Expired, or Unknown",
    ),
    source: Optional[str] = Query(
        default=None,
        description="Filter by tender source",
    ),
):
    tenders = load_tenders()

    if search and search.strip():
        keyword = search.strip().casefold()

        searchable_fields = (
            "tender_id",
            "title",
            "organization",
            "location",
            "department",
            "description",
        )

        tenders = [
            tender for tender in tenders
            if any(
                keyword in str(tender.get(field, "")).casefold()
                for field in searchable_fields
            )
        ]

    if status and status.strip():
        requested_status = status.strip().casefold()

        if requested_status not in {"open", "expired", "unknown"}:
            raise HTTPException(
                status_code=400,
                detail="Invalid status. Use Open, Expired, or Unknown.",
            )

        tenders = [
            tender for tender in tenders
            if tender["status"].casefold() == requested_status
        ]

    if source and source.strip():
        requested_source = source.strip().casefold()
        tenders = [
            tender for tender in tenders
            if requested_source in str(
                tender.get("source", "")
            ).casefold()
        ]

    return {
        "count": len(tenders),
        "tenders": tenders,
    }


@app.get("/api/summary")
def get_summary():
    tenders = load_tenders()
    return build_summary(tenders)


@app.post("/api/refresh")
def refresh_tenders():
    """
    Reload the configured JSON files and return fresh results.

    This does not scrape external websites. To collect live
    tenders, connect your collector scripts to this endpoint
    in a later step.
    """
    tenders = load_tenders()

    return {
        "success": True,
        "message": "Tender data reloaded successfully.",
        "summary": build_summary(tenders),
        "count": len(tenders),
        "tenders": tenders,
    }
