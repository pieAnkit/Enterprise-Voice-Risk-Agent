"""Vapi server-tool endpoint.

Vapi's assistant (running GPT-4o realtime) calls this URL when the caller
asks something requiring live data. Contract:
  Request : {"message": {"type": "tool-calls",
             "toolCallList": [{"id", "function": {"name", "arguments"}}]}, ...}
  Response: 200 {"results": [{"toolCallId": ..., "result": "<text to speak>"}]}

One round-trip per response — keep tool results short; the LLM summarizes.
"""
import json
import logging

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.rag import FindingsRAG
from app.upguard import UpGuardClient

router = APIRouter(prefix="/vapi", tags=["vapi"])
log = logging.getLogger(__name__)

upguard = UpGuardClient()
rag = FindingsRAG()

# Tool schemas — also paste into the Vapi assistant config (config/vapi_assistant.json)
TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "get_risk_summary",
            "description": "Get the organization's current cybersecurity risk "
                           "score and top risks. Use when asked about overall "
                           "risk, score, posture, or status.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_vulnerabilities",
            "description": "List open vulnerabilities, optionally filtered by "
                           "minimum severity. Use for questions about specific "
                           "threats, vendors, or weaknesses.",
            "parameters": {
                "type": "object",
                "properties": {
                    "min_severity": {
                        "type": "string",
                        "enum": ["low", "medium", "high", "critical"],
                        "description": "Minimum severity to include",
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_findings",
            "description": "Semantic search over historical security findings "
                           "and reports. Use for open-ended questions like "
                           "'what's our exposure to ransomware?' or 'summarize "
                           "last quarter's third-party risks'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string",
                                 "description": "The caller's full question"},
                },
                "required": ["question"],
            },
        },
    },
]


@router.post("/tools")
async def vapi_tools(request: Request, db: AsyncSession = Depends(get_db)):
    body = await request.json()
    message = body.get("message", {})
    call = body.get("call", {})
    tool_calls = message.get("toolCallList", []) if message.get("type") == "tool-calls" else []

    results = []
    for tc in tool_calls:
        name = tc["function"]["name"]
        args = json.loads(tc["function"].get("arguments") or "{}")
        log.info("tool=%s call=%s args=%s", name, call.get("id"), args)
        result = await _dispatch(name, args)
        results.append({"toolCallId": tc["id"], "result": result})

    from app.models import CallLog
    if call.get("id"):
        db.add(CallLog(
            vapi_call_id=call["id"],
            caller_number=call.get("customer", {}).get("number"),
            direction="inbound",
            tools_called=[{"name": tc["function"]["name"],
                           "args": tc["function"].get("arguments")}
                          for tc in tool_calls],
        ))
        await db.commit()

    return {"results": results}


async def _dispatch(name: str, args: dict) -> str:
    try:
        if name == "get_risk_summary":
            p = await upguard.get_risk_profile()
            return (f"Our current risk score is {p['score']} out of 100, grade {p['grade']}. "
                    f"Top risks: {'; '.join(p['top_risks'])}.")
        if name == "get_vulnerabilities":
            vulns = await upguard.get_vulnerabilities(args.get("min_severity", "medium"))
            if not vulns:
                return "No open vulnerabilities at or above that severity. Good news."
            return "Open vulnerabilities: " + "; ".join(
                f"{v['severity']}: {v['title']} ({v.get('vendor', 'unknown vendor')})"
                for v in vulns[:5]
            )
        if name == "query_findings":
            return rag.query(args["question"])
        return f"Unknown tool: {name}"
    except Exception as e:  # never let a tool exception kill the call
        log.exception("tool %s failed", name)
        return "I hit a problem pulling that data. Please try again in a moment."
