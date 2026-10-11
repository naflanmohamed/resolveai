from collections import Counter
from datetime import datetime, timedelta, timezone
from io import BytesIO
import re
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, func, delete
from sqlalchemy.orm import Session
from pypdf import PdfReader

from .core import Base, engine, get_db, hash_password, verify_password, create_token, current_user, admin_user, settings
from .models import User, Ticket, Document, Chunk, Audit
from .schemas import UserCreate, Login, UserOut, TicketCreate, TicketOut, Approval, StatusUpdate, DocumentCreate
from .rag import add_document
from .ml import evaluate
from .agent import analyze_ticket


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title="ResolveAI API", description="Explainable support triage + document RAG + human approval", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[origin.strip() for origin in settings().cors_origins.split(",") if origin.strip()], allow_credentials=True, allow_methods=["GET", "POST", "PATCH", "DELETE"], allow_headers=["Authorization", "Content-Type"])


def log(db: Session, actor_id: int | None, action: str, ticket_id: int | None = None, details: str = "") -> None:
    db.add(Audit(actor_id=actor_id, action=action, ticket_id=ticket_id, details=details[:500]))


def serialize_doc(doc: Document) -> dict:
    return {"id": doc.id, "title": doc.title, "source_type": doc.source_type, "created_at": doc.created_at, "chunk_count": len(doc.chunks), "preview": doc.content[:320]}


def get_ticket(db: Session, ticket_id: int) -> Ticket:
    ticket = db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")
    return ticket


def process_ticket(db: Session, ticket: Ticket, user_id: int | None = None) -> Ticket:
    result = analyze_ticket(db, ticket.subject, ticket.message, ticket.customer_name)
    ticket.category = result["category"]
    ticket.confidence = result["confidence"]
    ticket.priority = result["priority"]
    ticket.citations = result.get("citations", [])
    ticket.draft_response = result["draft"]
    ticket.approved_response = ""
    ticket.generated_with = result["generator"]
    ticket.status = "pending_review"
    log(db, user_id, "ticket.analyzed", ticket.id, f"{ticket.category} | {ticket.generated_with} | {len(ticket.citations)} references")
    db.commit()
    db.refresh(ticket)
    return ticket


@app.get("/api/health")
def health():
    return {"status": "ok", "app": "ResolveAI", "version": "1.0.0"}


@app.get("/api/auth/bootstrap")
def bootstrap(db: Session = Depends(get_db)):
    return {"needs_setup": db.scalar(select(func.count(User.id))) == 0, "registration_enabled": settings().allow_registration}


@app.post("/api/auth/register", response_model=dict, status_code=201)
def register(body: UserCreate, db: Session = Depends(get_db)):
    existing = db.scalar(select(func.count(User.id)))
    if existing > 0 and not settings().allow_registration:
        raise HTTPException(403, "Registration is closed. Ask the administrator for an account.")
    email = body.email.lower().strip()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        raise HTTPException(422, "Enter a valid email address")
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(409, "Email already registered")
    user = User(name=body.name.strip(), email=email, password_hash=hash_password(body.password), role="admin" if not existing else "agent")
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"token": create_token(user.id), "user": UserOut.model_validate(user)}


@app.post("/api/auth/login")
def login(body: Login, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == body.email.lower().strip()))
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Incorrect email or password")
    return {"token": create_token(user.id), "user": UserOut.model_validate(user)}


@app.get("/api/auth/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return user


@app.get("/api/admin/users", response_model=list[UserOut])
def users(db: Session = Depends(get_db), _: User = Depends(admin_user)):
    return db.scalars(select(User).order_by(User.created_at)).all()


@app.post("/api/admin/users", response_model=UserOut, status_code=201)
def add_team_member(body: UserCreate, db: Session = Depends(get_db), admin: User = Depends(admin_user)):
    email = body.email.lower().strip()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        raise HTTPException(422, "Invalid email address")
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(409, "Email already registered")
    user = User(name=body.name.strip(), email=email, password_hash=hash_password(body.password), role="agent")
    db.add(user)
    log(db, admin.id, "user.created", details=email)
    db.commit()
    db.refresh(user)
    return user


@app.get("/api/tickets", response_model=list[TicketOut])
def list_tickets(status: str = "", q: str = "", db: Session = Depends(get_db), _: User = Depends(current_user)):
    stmt = select(Ticket)
    if status:
        stmt = stmt.where(Ticket.status == status)
    if q:
        stmt = stmt.where(Ticket.subject.ilike(f"%{q[:100]}%") | Ticket.customer_name.ilike(f"%{q[:100]}%"))
    return db.scalars(stmt.order_by(Ticket.created_at.desc()).limit(500)).all()


@app.post("/api/tickets", response_model=TicketOut, status_code=201)
def create_ticket(body: TicketCreate, db: Session = Depends(get_db), user: User = Depends(current_user)):
    ticket = Ticket(**body.model_dump())
    db.add(ticket)
    db.flush()
    log(db, user.id, "ticket.created", ticket.id, ticket.subject)
    db.commit()
    return process_ticket(db, ticket, user.id)


@app.get("/api/tickets/{ticket_id}", response_model=TicketOut)
def ticket_detail(ticket_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    return get_ticket(db, ticket_id)


@app.post("/api/tickets/{ticket_id}/analyze", response_model=TicketOut)
def reanalyze(ticket_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    ticket = get_ticket(db, ticket_id)
    if ticket.status == "resolved":
        raise HTTPException(409, "Reopen a resolved ticket before reanalyzing")
    return process_ticket(db, ticket, user.id)


@app.post("/api/tickets/{ticket_id}/approve", response_model=TicketOut)
def approve(ticket_id: int, body: Approval, db: Session = Depends(get_db), user: User = Depends(current_user)):
    ticket = get_ticket(db, ticket_id)
    if ticket.status != "pending_review":
        raise HTTPException(409, "Only pending-review tickets can be approved")
    ticket.approved_response = body.response.strip()
    ticket.status = "approved"
    log(db, user.id, "ticket.approved", ticket.id, "Approved response stored; no message was sent")
    db.commit()
    db.refresh(ticket)
    return ticket


@app.post("/api/tickets/{ticket_id}/reject", response_model=TicketOut)
def reject(ticket_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    ticket = get_ticket(db, ticket_id)
    if ticket.status != "pending_review":
        raise HTTPException(409, "Only pending-review tickets can be rejected")
    ticket.status = "open"
    ticket.draft_response = ""
    ticket.citations = []
    log(db, user.id, "ticket.rejected", ticket.id, "Draft rejected")
    db.commit()
    db.refresh(ticket)
    return ticket


@app.patch("/api/tickets/{ticket_id}/status", response_model=TicketOut)
def change_status(ticket_id: int, body: StatusUpdate, db: Session = Depends(get_db), user: User = Depends(current_user)):
    ticket = get_ticket(db, ticket_id)
    if body.status == "resolved" and ticket.status != "approved":
        raise HTTPException(409, "Approve a response before resolving this ticket")
    ticket.status = body.status
    log(db, user.id, "ticket.status_changed", ticket.id, body.status)
    db.commit()
    db.refresh(ticket)
    return ticket


@app.get("/api/documents")
def documents(db: Session = Depends(get_db), _: User = Depends(current_user)):
    return [serialize_doc(x) for x in db.scalars(select(Document).order_by(Document.created_at.desc())).all()]


@app.post("/api/documents", status_code=201)
def create_document(body: DocumentCreate, db: Session = Depends(get_db), user: User = Depends(current_user)):
    doc = add_document(db, body.title, body.content)
    log(db, user.id, "document.created", details=doc.title)
    db.commit()
    return serialize_doc(doc)


@app.post("/api/documents/upload", status_code=201)
async def upload_document(file: UploadFile = File(...), db: Session = Depends(get_db), user: User = Depends(current_user)):
    name = (file.filename or "document").split("/")[-1].split("\\")[-1]
    extension = name.lower().rsplit(".", 1)[-1] if "." in name else ""
    if extension not in ("txt", "md", "pdf"):
        raise HTTPException(415, "Only .txt, .md and .pdf files are supported")
    raw = await file.read(5 * 1024 * 1024 + 1)
    if len(raw) > 5 * 1024 * 1024:
        raise HTTPException(413, "Max file size is 5 MB")
    try:
        content = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(raw)).pages[:75]) if extension == "pdf" else raw.decode("utf-8")
    except Exception as exc:
        raise HTTPException(422, "Could not read the document; provide a text-based PDF or UTF-8 file") from exc
    if len(content.strip()) < 40:
        raise HTTPException(422, "No usable text found. Scanned PDFs without text are not supported")
    if len(content) > 100_000:
        raise HTTPException(413, "Extracted text is too long (100,000 character maximum)")
    doc = add_document(db, name[:250], content, extension)
    log(db, user.id, "document.uploaded", details=name)
    db.commit()
    return serialize_doc(doc)


@app.delete("/api/documents/{doc_id}", status_code=204)
def remove_document(doc_id: int, db: Session = Depends(get_db), user: User = Depends(admin_user)):
    doc = db.get(Document, doc_id)
    if not doc:
        raise HTTPException(404, "Document not found")
    title = doc.title
    db.delete(doc)
    log(db, user.id, "document.deleted", details=title)
    db.commit()


@app.get("/api/analytics")
def analytics(db: Session = Depends(get_db), _: User = Depends(current_user)):
    tickets = db.scalars(select(Ticket)).all()
    statuses = Counter(t.status for t in tickets)
    categories = Counter(t.category for t in tickets)
    priorities = Counter(t.priority for t in tickets)
    today = datetime.now(timezone.utc).date()
    trend = []
    for offset in range(6, -1, -1):
        day = today - timedelta(days=offset)
        count = sum(1 for t in tickets if t.created_at.date() == day)
        trend.append({"date": day.isoformat(), "count": count})
    return {"total": len(tickets), "pending": statuses["pending_review"], "resolved": statuses["resolved"], "approved": statuses["approved"], "open": statuses["open"], "escalated": statuses["escalated"], "documents": db.scalar(select(func.count(Document.id))) or 0, "auto_drafted": sum(bool(t.draft_response) for t in tickets), "categories": dict(categories), "priorities": dict(priorities), "statuses": dict(statuses), "trend": trend}


@app.get("/api/ml/evaluation")
def ml_evaluation(_: User = Depends(current_user)):
    return evaluate()


@app.get("/api/audit")
def audits(db: Session = Depends(get_db), _: User = Depends(current_user)):
    items = db.scalars(select(Audit).order_by(Audit.created_at.desc()).limit(100)).all()
    return [{"id": a.id, "action": a.action, "ticket_id": a.ticket_id, "details": a.details, "actor": a.actor.name if a.actor else "System", "created_at": a.created_at} for a in items]


POLICIES = [
    ("Billing & Refund Policy", "Our monthly subscriptions renew at the beginning of each billing cycle. If a customer sees a duplicate charge, support should request the invoice ID and transaction dates to investigate; do not promise a refund before verification. Refund requests are reviewed by the billing team. Most approved refunds are processed in 5 to 10 business days depending on the bank. Customers can view invoices in Settings > Billing > Invoices. Payment methods can be updated in Settings > Billing > Payment methods."),
    ("Account Access & Security", "To reset an account password, select Forgot password on the login screen and follow the email link. Password reset links expire after 30 minutes. If the account is locked, wait 15 minutes or contact support. Never request a password or one-time code from a customer. To enable two-factor authentication, navigate to Settings > Security. Ownership transfer requires identity verification from the current account owner and review by a human support agent."),
    ("Incident & Service Availability", "If the dashboard is unavailable, first check status notifications. If there is a persistent HTTP 500 error or system outage, support should collect the approximate time, request ID, browser version, and affected feature. Do not ask customers to share passwords or secret keys. Escalate critical system outages to the engineering team. Announce an estimated time to repair only when engineering has provided a confirmed estimate."),
    ("Team & Workspace Management", "Workspace administrators can invite team members under Settings > Team > Invite member. The standard team plan supports up to 10 active members in this sample policy. Team members can be removed by an administrator. Exporting workspace data requires administrator privileges. Customers should not be promised higher limits without checking their subscription tier."),
    ("Product Features & Exports", "The sample Northstar Cloud platform supports CSV reports from Analytics > Export, scheduled weekly email summaries, and REST API integrations. PDF report export is not currently available in the sample product. Bulk document uploads are limited to 5 MB per uploaded file in this demo. Users can contact support to request a feature for roadmap consideration."),
    ("Privacy & Data Requests", "Customer data deletion requests must be verified by the privacy team before processing. Customers can request a personal data export in Settings > Privacy. Support agents must not disclose personal data to unverified users. Data access and deletion requests are escalated to a trained employee; do not claim to have completed a deletion unless it has actually been confirmed."),
]
SAMPLE_TICKETS = [
    ("Duplicate charge on monthly subscription", "Amelia Carter", "amelia@example.com", "Hi, I was charged twice for our team subscription this month. Could you check and refund the duplicate payment?"),
    ("Unable to log in after password reset", "Daniel Foster", "daniel@example.com", "I tried resetting my password but the login link expired. I'm locked out of my account."),
    ("Dashboard returning server errors", "Priya Shah", "priya@example.com", "Our analytics dashboard gives a 500 error whenever we open our latest report. This is urgent."),
    ("How to export a CSV report", "Leo Martins", "leo@example.com", "Does the product support CSV report downloads and where is the export button?"),
    ("Adding colleagues to our workspace", "Sofia Bennett", "sofia@example.com", "We need to invite three teammates to our account. How do I add new team members?"),
    ("Request copy of invoice", "Noah Wilson", "noah@example.com", "Can you share where to download our most recent invoice for accounting?"),
    ("Data privacy request", "Maya Chen", "maya@example.com", "I would like to request a copy of my account data and understand the deletion process."),
]


@app.post("/api/demo/seed")
def seed_demo(db: Session = Depends(get_db), user: User = Depends(admin_user)):
    if not settings().demo_mode:
        raise HTTPException(403, "Demo seeding is disabled")
    if db.scalar(select(func.count(Document.id))) or db.scalar(select(func.count(Ticket.id))):
        raise HTTPException(409, "Add demo content only to an empty workspace")
    for title, content in POLICIES:
        add_document(db, title, content)
    for subject, customer_name, email, message in SAMPLE_TICKETS:
        t = Ticket(subject=subject, customer_name=customer_name, customer_email=email, message=message)
        db.add(t)
        db.flush()
        process_ticket(db, t, user.id)
    log(db, user.id, "demo.seeded", details="6 policies and 7 tickets")
    db.commit()
    return {"documents": len(POLICIES), "tickets": len(SAMPLE_TICKETS)}
