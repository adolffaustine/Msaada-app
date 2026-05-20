"""Msaada — FastAPI backend serving the React chat UI."""
import os, json, time, uuid
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
# from ollama_chat import run_turn
from claude_chat import run_turn,visible_history

load_dotenv()

from liquidmatics import search, diagnose, summarize_search_results, summarize_diagnosis
from sessions import get_session, save_session
from tickets import load_tickets, save_tickets, append_ticket
from mailer import send_ticket_email
import vectorstore

PORT = int(os.environ.get("PORT", "4040"))
DATA_DIR = Path(os.environ.get("APP_DATA_DIR", "./data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
ADMIN_TOKEN = os.environ.get("APP_ADMIN_TOKEN", "")

app = FastAPI(title="Msaada")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://chatbot.liquidmatics.co.tz",
        "https://chatbot.liquidmatics.co.tz",
        "http://localhost",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _tool_handler(name: str, args: dict, card: dict) -> dict:
    """Dispatch tool calls invoked by the LLM."""
    if name == "search_customer":
        results = search(args.get("query", ""), limit=args.get("limit", 8))
        return {"results": summarize_search_results(results)}

    if name == "run_diagnosis":
        raw = diagnose(
            interface_name=args.get("interfaceName"),
            link_type=args.get("linkType"),
            ip_address=args.get("ipAddress"),
        )
        summary, chart = summarize_diagnosis(raw, capacity_mbps=args.get("capacityMbps"))
        card["chart"] = {
            "interface": args.get("interfaceName") or args.get("ipAddress"),
            "capacity_mbps": args.get("capacityMbps"),
            "sent_mbps": chart["sent_mbps"],
            "recv_mbps": chart["recv_mbps"],
        }
        return summary

    if name == "log_ticket":
        ticket = {
            "id": str(uuid.uuid4())[:8],
            "createdAt": int(time.time()),
            "customerName": args.get("customerName"),
            "cid": args.get("cid"),
            "contact": args.get("contact"),
            "interface": args.get("interface"),
            "summary": args.get("summary", ""),
            "severity": args.get("severity", "medium"),
        }
        append_ticket(ticket)
        card["ticket"] = {"id": ticket["id"], "severity": ticket["severity"]}
        try:
            send_ticket_email(ticket)
        except Exception as e:
            print("mailer error:", e)
        try:
            embedded_text = f"{ticket.get('customerName','')} {ticket.get('cid','')} {ticket.get('summary','')}"
            vectorstore.add(
                doc_id=ticket["id"],
                text=embedded_text,
                metadata={
                    "customerName": ticket.get("customerName"),
                    "cid": ticket.get("cid"),
                    "severity": ticket.get("severity"),
                    "interface": ticket.get("interface"),
                },
            )
        except Exception as e:
            print("vectorstore add error:", e)
        return {"ok": True, "ticketId": ticket["id"]}

    if name == "recall_similar_cases":
        query = args.get("query", "")
        k = args.get("limit", 3)
        hits = vectorstore.search(query, k=k)
        return {"hits": hits, "count": len(hits)}

    return {"error": f"unknown tool {name}"}


@app.post("/api/chat")
async def api_chat(req: Request):
    body = await req.json()
    sid = body.get("sessionId") or str(uuid.uuid4())
    message = (body.get("message") or "").strip()
    if not message:
        raise HTTPException(400, "empty message")

    sess = get_session(sid)
    try:
        reply, history, card = run_turn(sess["history"], message, _tool_handler)
        sess["history"] = history[-50:]
        sess["lastSeen"] = int(time.time())
        save_session(sid, sess)
        return {"sessionId": sid, "reply": reply, "card": card}
    except Exception as e:
        print("chat error:", e)
        raise HTTPException(500, str(e))


@app.get("/api/history")
async def api_history(sessionId: str):
    sess = get_session(sessionId, create_if_missing=False)
    if not sess:
        return {"messages": []}
    return {"messages": visible_history(sess.get("history", []))}


@app.post("/api/reset")
async def api_reset(req: Request):
    body = await req.json()
    sid = body.get("sessionId")
    if sid:
        save_session(sid, {"history": [], "lastSeen": int(time.time())})
    return {"ok": True}


def _check_admin(token: Optional[str]):
    if not ADMIN_TOKEN or token != ADMIN_TOKEN:
        raise HTTPException(401, "unauthorized")


@app.get("/api/admin/tickets")
async def api_admin_tickets(token: str = ""):
    _check_admin(token)
    return {"tickets": load_tickets()}


@app.get("/healthz")
async def healthz():
    return {"ok": True, "service": "msaada"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
