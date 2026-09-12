"""
Security Voice Agent — production entry point.

Two voice surfaces:
  1. /vapi/*    AI agent path (Vapi.ai + GPT-4o realtime + tools)  <-- primary
  2. /voice/*   Legacy Twilio DTMF menu (zero-config demo fallback)
JSON API + webhook ingestion for proactive alerts.
"""
import os
from datetime import datetime, timezone
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Request, Form
from fastapi.responses import Response
from twilio.twiml.voice_response import VoiceResponse, Gather

from app.alerts import AlertProvider
from app.db import init_db
from app.vapi_tools import router as vapi_router
from app.webhooks import router as webhooks_router

load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(title="Security Voice Agent", version="1.0.0", lifespan=lifespan)
app.include_router(vapi_router)
app.include_router(webhooks_router)

provider = AlertProvider(os.getenv("ALERTS_API_URL"))  # None -> mock data


@app.get("/health")
def health():
    return {"status": "ok", "time": datetime.now(timezone.utc).isoformat()}


# ---------- JSON API ----------

@app.get("/api/risk")
def risk_score():
    return provider.get_risk_summary()


@app.get("/api/alerts")
def alerts(active_only: bool = True, limit: int = 5):
    return {"alerts": provider.get_alerts(active_only=active_only, limit=limit)}


# ---------- Legacy Twilio voice (demo fallback) ----------

@app.post("/voice")
async def voice_entry(request: Request):
    summary = provider.get_risk_summary()
    resp = VoiceResponse()
    gather = Gather(num_digits=1, input="dtmf speech", action="/voice/menu",
                    method="POST", timeout=6, speech_timeout="auto")
    gather.say(f"Hello, this is your security alert line. "
               f"The current risk score is {summary['score']} out of 100, "
               f"level {summary['level']}. "
               f"Press 1 or say risk, to hear the risk summary. "
               f"Press 2 or say alerts, for the top active alerts. "
               f"Press 3 or say status, for overall system status.",
               voice="Polly.Joanna")
    resp.append(gather)
    resp.say("We did not receive a selection. Goodbye.", voice="Polly.Joanna")
    return Response(content=str(resp), media_type="text/xml")


@app.post("/voice/menu")
async def voice_menu(Digits: str = Form(default=""), SpeechResult: str = Form(default="")):
    resp = VoiceResponse()
    choice = (Digits or "").strip()
    speech = (SpeechResult or "").lower()

    if choice == "1" or "risk" in speech:
        s = provider.get_risk_summary()
        resp.say(f"Current risk score: {s['score']} out of 100. "
                 f"Risk level: {s['level']}. {s['message']}", voice="Polly.Joanna")
    elif choice == "2" or "alert" in speech:
        alerts_list = provider.get_alerts(active_only=True, limit=3)
        if not alerts_list:
            resp.say("There are no active alerts right now. All clear.", voice="Polly.Joanna")
        else:
            resp.say(f"There are {len(alerts_list)} top active alerts.", voice="Polly.Joanna")
            for a in alerts_list:
                resp.say(f"{a['severity']} severity: {a['title']}. {a['detail']}",
                         voice="Polly.Joanna")
    elif choice == "3" or "status" in speech:
        s = provider.get_risk_summary()
        resp.say(f"System status: {s['active_alerts']} active alerts, "
                 f"{s['acknowledged']} acknowledged, monitored sources: {s['sources']}.",
                 voice="Polly.Joanna")
    else:
        resp.say("Sorry, I did not understand that. Please try again.", voice="Polly.Joanna")
        resp.redirect("/voice")

    gather = Gather(num_digits=1, action="/voice/menu", method="POST", timeout=5)
    gather.say("Press any key to return to the main menu, or hang up to end the call.",
               voice="Polly.Joanna")
    resp.append(gather)
    resp.say("Goodbye.", voice="Polly.Joanna")
    return Response(content=str(resp), media_type="text/xml")
