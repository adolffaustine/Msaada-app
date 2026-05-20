"""Liquidmatics API client — login token cache, search, diagnosis with type-aware routing."""
import os, time, threading
import httpx

BASE = os.environ.get("LIQUIDMATICS_BASE", "https://automation.liquidmatics.co.tz")
TOKEN_TTL_SECONDS = 50 * 60

_lock = threading.Lock()
_token = None
_token_expires_at = 0.0

DIAGNOSIS_ENDPOINT_BY_TYPE = {
    "DIA": "/diagnosis",
    "L3VPN": "/diagnosis/l3vpn",
    "IPT": "/diagnosis/ipt",
    "FTTH": "/diagnosis/ftth",
    "GPON": "/diagnosis/ftth",
}


def _login():
    global _token, _token_expires_at
    email = os.environ.get("LIQUIDMATICS_EMAIL")
    password = os.environ.get("LIQUIDMATICS_PASSWORD")
    if not email or not password:
        raise RuntimeError("Liquidmatics credentials not configured")
    r = httpx.post(f"{BASE}/users/login", json={"email": email, "password": password}, timeout=15)
    r.raise_for_status()
    data = r.json()
    tok = data.get("token")
    if not tok:
        raise RuntimeError("Login response missing token")
    _token = tok
    _token_expires_at = time.time() + TOKEN_TTL_SECONDS
    return tok


def _get_token():
    with _lock:
        if not _token or time.time() >= _token_expires_at:
            return _login()
        return _token


def _authed_request(method, path, body=None, timeout=240.0):
    url = f"{BASE}{path}"
    def _do(tok):
        return httpx.request(
            method, url,
            headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
            json=body, timeout=timeout,
        )
    r = _do(_get_token())
    if r.status_code == 401:
        with _lock:
            _login()
        r = _do(_get_token())
    r.raise_for_status()
    return r.json()


def search(query: str, limit: int = 10):
    if not query or not query.strip():
        return []
    r = httpx.get(
        f"{BASE}/search",
        params={"q": query.strip(), "limit": limit},
        headers={"Authorization": f"Bearer {_get_token()}"},
        timeout=20,
    )
    r.raise_for_status()
    data = r.json()
    return data.get("results", []) if isinstance(data, dict) else []


def diagnose(interface_name=None, link_type=None, ip_address=None):
    normalized = (link_type or "").upper()
    path = DIAGNOSIS_ENDPOINT_BY_TYPE.get(normalized, "/diagnosis")
    is_ftth = normalized in ("FTTH", "GPON")
    if is_ftth:
        if not ip_address:
            raise ValueError("ipAddress is required for FTTH/GPON")
        return _authed_request("POST", path, body={"ip": ip_address}, timeout=240.0)
    if not interface_name:
        raise ValueError("interfaceName is required")
    return _authed_request("POST", path, body={"interfaceName": interface_name}, timeout=240.0)


def summarize_search_results(results):
    out = []
    for r in results or []:
        d = r.get("data") or {}
        is_ftth = r.get("type") in ("FTTH", "GPON")
        up_mbps = d.get("upmbps") if d.get("upmbps") is not None else (d.get("capacity") if r.get("type") == "Shared" else None)
        down_mbps = d.get("downmbps") if d.get("downmbps") is not None else (d.get("capacity") if r.get("type") == "Shared" else None)
        out.append({
            "customerName": r.get("customerName"),
            "cid": r.get("cid"),
            "interface": r.get("interface"),
            "status": r.get("status"),
            "type": r.get("type"),
            "switchName": r.get("switchName"),
            "neighborSwitch": None if is_ftth else (r.get("nbr") or d.get("nbr")),
            "port": d.get("port"),
            "upMbps": up_mbps,
            "downMbps": down_mbps,
            "area": (d.get("client_db") or {}).get("area"),
            "routeInstance": d.get("route_instance"),
            "ip": d.get("ip"),
            "pppoeUsername": (d.get("pppoeusername") or r.get("nbr")) if is_ftth else None,
        })
    return out


def summarize_diagnosis(diag: dict, capacity_mbps=None):
    ping_first = None
    if isinstance(diag.get("pingResults"), list) and diag["pingResults"]:
        ping_first = dict(diag["pingResults"][0])
    elif isinstance(diag.get("pingResult"), dict):
        ping_first = dict(diag["pingResult"])
    if ping_first and "ip" not in ping_first and diag.get("ip"):
        ping_first["ip"] = diag["ip"]

    gd = diag.get("graphData") or None
    sent_raw = (gd or {}).get("sentData") or []
    recv_raw = (gd or {}).get("recvData") or []

    def to_series(samples):
        out = []
        for s in samples:
            try:
                clock = int(s.get("clock"))
                value = float(s.get("value"))
                out.append([clock * 1000, round(value / 1_000_000, 3)])
            except Exception:
                continue
        out.sort(key=lambda p: p[0])
        return out

    sent = to_series(sent_raw)
    recv = to_series(recv_raw)
    has_usage = len(sent) > 0 or len(recv) > 0

    def peak(s): return max((p[1] for p in s), default=0.0)
    def avg(s):  return round(sum(p[1] for p in s) / len(s), 3) if s else 0.0

    nb = diag.get("neighborSwitch")
    neighbor_switch = nb if isinstance(nb, str) else ((nb or {}).get("name") or (nb or {}).get("ip") if isinstance(nb, dict) else None)

    summary = {
        "status_message": diag.get("message"),
        "ping": ping_first,
        "has_usage_data": has_usage,
        "switch_name": diag.get("switchName"),
        "neighbor_switch": neighbor_switch,
        "route_instance": diag.get("routeInstance"),
        "customer_ip": diag.get("customerIp"),
        "customer_asn": diag.get("customerAsn"),
        "bgp_route_count": diag.get("bgpRouteCount") if isinstance(diag.get("bgpRouteCount"), int) else None,
        "bgp_routes": (diag.get("bgpRoutes") or [])[:5] if isinstance(diag.get("bgpRoutes"), list) else None,
        "media_type": diag.get("mediaType"),
        "customer_port": diag.get("customerPort"),
        "last_flapped": (diag.get("flappedInfo") or {}).get("lastFlapped"),
        "flap_ago": (diag.get("flappedInfo") or {}).get("durationAgo"),
        "power_info": diag.get("powerInfo") if isinstance(diag.get("powerInfo"), str) else None,
    }

    if ping_first:
        try:
            max_l = float(ping_first.get("maxLatency", 0))
            avg_l = float(ping_first.get("avgLatency", 0))
            std_l = float(ping_first.get("stddevLatency", 0))
            if max_l and avg_l and (max_l > avg_l * 4 or std_l > 10):
                summary["quality_warning"] = "High latency variance / jitter — may feel unstable for real-time apps."
        except Exception:
            pass

    fi = diag.get("flappedInfo")
    if isinstance(fi, dict) and fi.get("lastFlapped"):
        summary["flap_warning"] = f"Interface last flapped {fi.get('durationAgo','recently')} — connection may have had a brief drop."

    if has_usage:
        summary["sent_peak_mbps"] = peak(sent)
        summary["sent_avg_mbps"]  = avg(sent)
        summary["recv_peak_mbps"] = peak(recv)
        summary["recv_avg_mbps"]  = avg(recv)
        summary["capacity_mbps"]  = capacity_mbps
        summary["sample_count"]   = {"sent": len(sent), "recv": len(recv)}
        if capacity_mbps:
            summary["sent_peak_pct"] = round(100 * summary["sent_peak_mbps"] / capacity_mbps, 1)
            summary["recv_peak_pct"] = round(100 * summary["recv_peak_mbps"] / capacity_mbps, 1)
    else:
        summary["note"] = "No usage time-series — diagnosis is ping-only. Judge health from packet loss and latency."

    if ping_first and float(ping_first.get("packetLoss", 0)) >= 100 and has_usage:
        peak_any = max(peak(sent), peak(recv))
        if peak_any > 0.01:
            summary["icmp_filtered_likely"] = True
            summary["icmp_filtered_note"] = (
                f"Ping is 100% lost but the link is actively passing traffic (peak {peak_any:.2f} Mbps). "
                "The customer's firewall or router is most likely blocking inbound ICMP. The line itself is healthy."
            )

    ei = diag.get("expiryInfo")
    if isinstance(ei, dict):
        summary["service_status"] = ei.get("status")
        summary["service_expiry_date"] = ei.get("topUpExpiry")
        summary["service_days_remaining"] = ei.get("daysRemaining") if isinstance(ei.get("daysRemaining"), int) else None
        summary["service_days_since_expiry"] = ei.get("daysSinceExpiry") if isinstance(ei.get("daysSinceExpiry"), int) else None
        summary["service_expiry_message"] = ei.get("message")
        summary["service_is_free_customer"] = bool(ei.get("isFreeCustomer"))
        dr = ei.get("daysRemaining")
        if isinstance(dr, int) and dr <= 5:
            summary["expiry_warning"] = (
                "Service has expired or is expiring today — customer may lose connectivity at any moment."
                if dr <= 0 else f"Service expires in {dr} day(s) — recommend top-up to avoid disconnection."
            )

    ci = diag.get("customerInfo")
    if isinstance(ci, dict):
        summary["account_customer_id"] = ci.get("customerID")
        summary["account_customer_name"] = ci.get("customerName")
        summary["account_pppoe_username"] = ci.get("pppoeusername")

    chart = {"sent_mbps": sent, "recv_mbps": recv, "capacity_mbps": capacity_mbps}
    return summary, chart
