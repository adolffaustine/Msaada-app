"""Anthropic Claude chat orchestration with tool use."""
import os
import json
import asyncio
import inspect
from anthropic import AsyncAnthropic
from dotenv import load_dotenv

load_dotenv()

client = AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")

SYSTEM_PROMPT = """You are **Msaada** (Swahili for "help"), the AI NOC assistant for Liquid Technologies in Tanzania. You speak directly with customers about their internet connectivity. Calm, factual, action-oriented.

The chat UI has ALREADY greeted the customer. Do NOT repeat the greeting. Treat their first message as a site name, CID, complaint, or social greeting — interpret and act.

How a conversation should flow:

1. First message:
   - Site name or CID → call search_customer immediately.
   - Complaint with no name/CID → one-line acknowledgement, then ask for it once.
   - "hi", "hello", "hey" or similar → respond warmly in ONE sentence and ask for the name/CID in the same reply.
   - If the customer gave their own name (e.g. "hi I'm Adolf") → "Nice to meet you, <Name>! Could you please share your site name or CID?"

2. After search_customer returns:
   - One result → use it, proceed.
   - Multiple results → present numbered, bold customer names, in this exact format:
       Found N sites under "<query>" — which one is yours? You can just reply with the number.
       1. **<customerName>** — CID <cid> | <type> <capacity>Mbps | <area>
       2. ...
   - Zero results → ask for the spelling or CID once. If still nothing, offer a ticket.

3. As soon as you have an interface, call run_diagnosis with interfaceName + linkType + capacityMbps. For FTTH/GPON pass ipAddress from the search result (not interfaceName).

4. Cross-checks before judging health:
   - status_message containing "experiencing issues", "down" → fault.
   - For FTTH: SEARCH RESULT's status field is authoritative. status=down means session down — even if ping passes (IP may have been reassigned).
   - For FTTH: trust status + ping over the billing/expiry record. status=up AND ping clean = service IS working (top-up may not have synced yet — don't send the customer to billing).
   - icmp_filtered_likely=true → 100% ping loss with active traffic = customer firewall blocks ICMP. NOT a fault.
   - quality_warning → mention jitter affects real-time apps.

5. Report (use this structure, adapt the header to the finding):

   [Header — "Good news — your <type> line looks healthy.", "Your line is up but very busy.", "I can see an issue on your line.", "Your line is currently disconnected." etc.]

   - **Account:** <customerName> — CID <cid>
   - **Link type:** <Type> — <one-line plain-language characteristic>
   - **Path:** served from <switch_name> via <neighbor_switch>[; route instance <route_instance> for L3VPN] — skip if none.
   - **Media:** <media_type> on port <customer_port> — skip if null.
   - **Ping:** <packetLoss>% loss, avg <avgLatency>ms — skip for IPT; for FTTH down skip entirely; for FTTH/GPON do NOT show the IP.
   - **BGP session (IPT only):** <status_message> — peer <customer_ip>, ASN <customer_asn>
   - **Routes advertised (IPT only):** <bgp_route_count> prefixes
   - **Upload / Download:** peak X/Y Mbps (Z%) — only if has_usage_data.
   - **Service status / Expiry date** — for FTTH; if billing says expired but session is up + ping clean, note record may be stale.

   Link-type one-liners:
   - DIA → "Dedicated Internet Access, X Mbps dedicated 1:1 to your site"
   - L3VPN → "Private MPLS routed connection (not internet)"
   - IPT → "IP Transit — wholesale/BGP link"
   - Shared → "Capacity shared with other customers in the area"
   - FTTH/GPON → "Fibre-to-the-Home residential/SOHO connection"

6. Follow-up tailored to the link type when the line is healthy:
   - DIA / FTTH / GPON / L3VPN → "What exactly are you experiencing — slow speeds, disconnects, a specific app/site, or only on Wi-Fi?"
   - Shared → "Are slow periods at peak times (evenings/working hours) or all the time?"
   - IPT → "Are you seeing prefix-specific reachability issues, latency to peers, or general degradation?"

   Then give targeted advice based on their answer; never start with generic 'restart your router' before running diagnosis.

7. Escalation (log_ticket):
   - Real fault → confirm contact (number/email), call log_ticket.
   - Customer asks for human.
   - Symptom persists after a targeted fix attempt.
   Always pass the customer name, CID, interface, summary, severity. Include PPPoE username/IP from the search result in the ticket payload — but NEVER in chat replies.

CONVERSATION MEMORY — you have full access to prior turns. Never say "I have no memory" or "session starts fresh". On "recheck"/"try again", re-run diagnosis on the SAME interface from earlier. Use prior search context for log_ticket without re-asking.

PAST-CASE RECALL — once per conversation, AFTER the customer describes their symptom and BEFORE you offer generic advice, call recall_similar_cases with a query like "<symptom> <link type> <area>". If similar cases come back with score > 0.7, briefly mention what worked: "Looks like a similar case from last week was resolved by [X]. Let's try that first." If nothing relevant comes back, skip — don't mention the search to the customer. Do NOT use this on the first turn or for healthy-line check-ins.

PRIVACY rules:
- NEVER show PPPoE usernames in chat.
- NEVER show full FTTH/residential IPs (last octet only, or omit).
- Never ask for passwords or payment details.
- Never promise specific fix times.
"""

TOOLS = [
    {
        "name": "search_customer",
        "description": "Search for a customer/site by name or CID. Returns matches with type, capacity, area, IP for FTTH, switch info.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Customer name or CID."},
                "limit": {"type": "integer", "description": "Max results.", "default": 8},
            },
            "required": ["query"],
        },
    },
    {
        "name": "run_diagnosis",
        "description": "Run live diagnosis. Routes by linkType: DIA->/diagnosis, L3VPN->/diagnosis/l3vpn, IPT->/diagnosis/ipt, FTTH/GPON->/diagnosis/ftth (uses ipAddress not interfaceName).",
        "input_schema": {
            "type": "object",
            "properties": {
                "interfaceName": {"type": "string", "description": "Interface name (DIA/L3VPN/IPT)."},
                "linkType": {"type": "string", "description": "DIA, L3VPN, IPT, Shared, FTTH, GPON."},
                "capacityMbps": {"type": "number", "description": "Higher of up/down Mbps."},
                "ipAddress": {"type": "string", "description": "Customer public IP — required for FTTH/GPON."},
            },
        },
    },
    {
        "name": "log_ticket",
        "description": "Log a support ticket for the human network team. Also embeds the ticket for future recall.",
        "input_schema": {
            "type": "object",
            "properties": {
                "customerName": {"type": "string"},
                "cid": {"type": "string"},
                "contact": {"type": "string", "description": "Phone or email."},
                "interface": {"type": "string"},
                "summary": {"type": "string"},
                "severity": {"type": "string", "enum": ["low", "medium", "high"]},
            },
            "required": ["customerName", "summary", "severity"],
        },
    },
    {
        "name": "recall_similar_cases",
        "description": "Search past tickets for similar symptoms (vector-embedded). Use ONCE per conversation, AFTER the customer describes their symptom and BEFORE giving generic advice. Returns up to 3 ranked similar cases.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Symptom + link type, e.g. 'slow speed on Wi-Fi DIA Meticulous'."},
                "limit": {"type": "integer", "default": 3},
            },
            "required": ["query"],
        },
    },
]


def _block_to_dict(block):
    """Convert an Anthropic content block (SDK object) to a plain dict for JSON storage."""
    if isinstance(block, dict):
        return block
    if hasattr(block, "model_dump"):
        return block.model_dump()
    return dict(block)


def visible_history(history):
    """Reduce stored history to user-visible text pairs for UI replay."""
    out = []
    for msg in history or []:
        role = msg.get("role")
        content = msg.get("content")
        if role == "user" and isinstance(content, str) and content.strip():
            out.append({"role": "user", "text": content})
        elif role == "assistant" and isinstance(content, list):
            text = "".join(
                b.get("text", "")
                for b in content
                if isinstance(b, dict) and b.get("type") == "text"
            ).strip()
            if text:
                out.append({"role": "bot", "text": text})
    return out


async def run_turn(history, user_message, tool_handler, max_iters=8):
    """Run one async chat turn. Returns (reply_text, new_history, card).

    tool_handler may be sync or async — both are handled transparently.
    history is a list of {"role": "user"|"assistant", "content": str|list} messages
    stored in Anthropic's native format.
    """

    import vectorstore
    # Retrieve similar past prompts/responses for retrieval-augmented context
    similar = vectorstore.search(user_message, k=3, min_score=0.65)
    retrieval_context = ""
    if similar:
        retrieval_context = "\n\n---\nRelevant past cases (for reference only):\n"
        for hit in similar:
            meta = hit.get("metadata", {})
            src = meta.get("source", "")
            retrieval_context += f"[{src}] {hit['text']}\n"

    messages = []
    for m in history or []:
        if m.get("role") in ("user", "assistant"):
            messages.append({"role": m["role"], "content": m["content"]})
    # Inject retrieval context before the user message
    if retrieval_context:
        messages.append({"role": "user", "content": retrieval_context})
    messages.append({"role": "user", "content": user_message})

    card = {"chart": None, "ticket": None}

    for _ in range(max_iters):
        resp = await client.messages.create(
            model=MODEL,
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
            temperature=0.3,
        )

        assistant_blocks = [_block_to_dict(b) for b in resp.content]
        messages.append({"role": "assistant", "content": assistant_blocks})

        if resp.stop_reason != "tool_use":
            text = "".join(
                b.get("text", "") for b in assistant_blocks if b.get("type") == "text"
            ).strip()
            return text, messages, card

        tool_results = []
        for block in assistant_blocks:
            if block.get("type") != "tool_use":
                continue
            name = block.get("name", "")
            args = block.get("input") or {}
            try:
                if inspect.iscoroutinefunction(tool_handler):
                    result = await tool_handler(name, args, card)
                else:
                    result = await asyncio.to_thread(tool_handler, name, args, card)
            except Exception as e:
                result = {"error": str(e)}
            content_str = json.dumps(result)
            if len(content_str) > 8000:
                content_str = content_str[:8000]
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.get("id"),
                "content": content_str,
            })
        messages.append({"role": "user", "content": tool_results})

    return (
        "Sorry, I was not able to complete that. Please try again or ask for a human agent.",
        messages,
        card,
    )
