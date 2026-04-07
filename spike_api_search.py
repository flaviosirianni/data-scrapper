"""
Spike: construct initial web-unified-search token and poll for flight results.

Token structure (proto3 + zstd + base64url):
  field 1 (message):
    field 1 (varint): 1
    field 2 (message):
      field 1 (message):
        field 1 (string): sessionId  (UUID v4, client-generated)
        field 2 (varint): 2
        field 3 (string): callId     (UUID v4, new each poll, from response)
      field 2 (varint): timestamp_ms
      field 3 (varint): 1
  field 2 (string): "uss_" + ussId  (UUID v4, constant per search)
  field 3 (varint): countdown        (4 for first call)
  field 4 (string): market           ("AR")

Search params come from the `scanner` cookie, not the token.
"""
import base64
import json
import time
import uuid

import pyzstd
import requests


def encode_varint(value):
    bits = value & 0x7F
    value >>= 7
    result = bytes()
    while value:
        result += bytes([0x80 | bits])
        bits = value & 0x7F
        value >>= 7
    result += bytes([bits])
    return result


def encode_proto_field(field_num, wire_type, value):
    tag = (field_num << 3) | wire_type
    return encode_varint(tag) + value


def encode_string(s):
    encoded = s.encode("utf-8")
    return encode_varint(len(encoded)) + encoded


def encode_message(data):
    return encode_varint(len(data)) + data


def build_initial_token(session_id, call_id, uss_id, market="AR", countdown=4):
    """Build the initial web-unified-search token."""
    ts_ms = int(time.time() * 1000)

    # inner_inner = field1(sessionId) + field2(2) + field3(callId)
    inner_inner = (
        encode_proto_field(1, 2, encode_string(session_id))
        + encode_proto_field(2, 0, encode_varint(2))
        + encode_proto_field(3, 2, encode_string(call_id))
    )

    # inner = field1(inner_inner) + field2(ts_ms) + field3(1)
    inner = (
        encode_proto_field(1, 2, encode_message(inner_inner))
        + encode_proto_field(2, 0, encode_varint(ts_ms))
        + encode_proto_field(3, 0, encode_varint(1))
    )

    # outer = field1(field1(1) + field2(inner)) + field2(uss_id) + field3(countdown) + field4(market)
    session_wrapper = (
        encode_proto_field(1, 0, encode_varint(1))
        + encode_proto_field(2, 2, encode_message(inner))
    )

    proto = (
        encode_proto_field(1, 2, encode_message(session_wrapper))
        + encode_proto_field(2, 2, encode_string(f"uss_{uss_id}"))
        + encode_proto_field(3, 0, encode_varint(countdown))
        + encode_proto_field(4, 2, encode_string(market))
    )

    compressed = pyzstd.compress(proto)
    token = base64.urlsafe_b64encode(compressed).rstrip(b"=").decode()
    return token


def build_scanner_cookie(origin, destination, outbound_date, return_date):
    """Build the scanner cookie that encodes search parameters."""
    out_ym = outbound_date.replace("-", "")[2:6]   # e.g. 2612
    out_day = outbound_date.split("-")[2]           # e.g. 16
    ret_ym = return_date.replace("-", "")[2:6]      # e.g. 2701
    ret_day = return_date.split("-")[2]             # e.g. 25

    return (
        f"currency:::ARS"
        f"&from:::{origin}"
        f"&legs:::{origin}|{outbound_date}|{destination}|{destination}|{return_date}|{origin}"
        f"&tripType:::return"
        f"&rtn:::true"
        f"&preferDirects:::false"
        f"&parallelSearch:::false"
        f"&outboundAlts:::false"
        f"&inboundAlts:::false"
        f"&oym:::{out_ym}"
        f"&oday:::{out_day}"
        f"&wy:::0"
        f"&iym:::{ret_ym}"
        f"&iday:::{ret_day}"
        f"&to:::{destination}"
        f"&cabinclass:::Economy"
        f"&adults:::1"
        f"&adultsV2:::1"
        f"&children:::0"
        f"&childrenV2"
        f"&infants:::0"
    )


# --- cookies from user's browser session ---
BASE_COOKIES = {
    "traveller_context": "2bcd843c-c401-4201-ace4-24fbb9351389",
    "__Secure-anon_token": "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCIsImtpZCI6ImM3ZGZlYjI2LTlmZjUtNDY4OC1iYjc3LWRiNTY2NWUyNjFkZSJ9.eyJhenAiOiIyNWM3MGZmZDAwN2JkOGQzODM3NyIsImh0dHBzOi8vc2t5c2Nhbm5lci5uZXQvbG9naW5UeXBlIjoiYW5vbnltb3VzIiwiaHR0cHM6Ly9za3lzY2FubmVyLm5ldC91dGlkIjoiMmJjZDg0M2MtYzQwMS00MjAxLWFjZTQtMjRmYmI5MzUxMzg5IiwiaHR0cHM6Ly9za3lzY2FubmVyLm5ldC9jc3JmIjoiMjI4NGJlYjkzOWY0MjhlMGJkZWI4YjY5ZjA1ZDNhODMiLCJodHRwczovL3NreXNjYW5uZXIubmV0L2p0aSI6Ijk1ZjQ1ZWQ1LTExOWItNGNlNC05Y2E2LWQ4MTMwMjk3M2E0YSIsImlhdCI6MTc3MDc1ODk4NCwiZXhwIjoxODMzODMwOTg0LCJhdWQiOiJodHRwczovL2dhdGV3YXkuc2t5c2Nhbm5lci5uZXQvaWRlbnRpdHkiLCJpc3MiOiJodHRwczovL3d3dy5za3lzY2FubmVyLm5ldC9zdHRjL2lkZW50aXR5L2p3a3MvcHJvZC8ifQ.P-O0fL3juu6ZREcgKtxV5pPHsACvfM3ML9cwBOpuN2PDkOKV2X8M4Tf8J_bPdhm6mGhJvVnAEtjU1vMcWwtJDGEDXrET3HqNqfLyZVcVo8v3bEKwB6B5FGCaSXCIQC15l_yLXuuuuGktY3XNTnBytIluGXyKfMESr-89zccet-bHC8Nlek3vkczsL-AwzHImz2QmOhctdK7zaK_oP4XRFOMMitV353w4zpxmIGYNv3kNa8TtQ0bmXwxlE5fiSeTxwzYXKJtNavjns50m1JgmKSoZM5d9YokJKTfphy4q9drUiMSf933I5AFVwoFN3TWeD_aX59GV9JqQG0330Ovq0w",
    "__Secure-anon_csrf_token": "2284beb939f428e0bdeb8b69f05d3a83",
    "__Secure-ska": "250c5ca5-05a8-4ace-bebc-91daf36e0a12",
    "device_guid": "250c5ca5-05a8-4ace-bebc-91daf36e0a12",
    "_pxvid": "9df469dc-06c7-11f1-81b8-153ad124e751",
    "preferences": "2bcd843cc4014201ace424fbb9351389",
    "_gcl_au": "1.1.1657747645.1770758987",
    "_ga": "GA1.1.1865332349.1770758988",
    "abgroup": "79012127",
    "_pxhd": "l-kyfckIIc6UicZFDgwl3VKmQd4mPEXI3XTgUrMLLf/nP6RUFkidG8VoB6Q9zTnjKyxzPk5og9SoccIp49c6wQ==:O1nh-U/pAT5lxTVf96223a/CFWUFSBk3aE0f8aoUAW8CS1GQp4fpkpEgKenRrCQLQSJ9u6fO7t5jKid6UE-jrfvIN9ig8DzQ4qryDpJpoA4=",
    "_px3": "3bade47d687d88954c6f765214b9a1bcc5e4108ef40f4aa0caaf986ae0c28a11:0JmoIJX/ataZZMWyB25H4APDScwNGUQSu2TKwxm+zWz7UMC0sPt9Z8tsMmgB+dKHtBUd5/WWelNPVba8GA9wYw==:1000:PioxKHc+55yP/9cxxrEMON7WK0pP4QXodgR6T2xjpeREfY4XuL0N7trSO38hZk9Ulp6pwutAIgolxQUOWnMeTnFJ6zup7Hpoc+e26F/FzHzabxARFmKhI/2CBOie91b+odb1zBRoXQ1HcmfaEbn9RD7/6e8Wp4P2roDvNjBRSsvK2AnMBA/oP3odDKAhpNgjkiGUXyuRZeWBTQ86lPIGotbc/SJaAX6abnFO1fDB37N5pMBrqtfjEXzvGpnCN24MwUFPjyCPs05ANUn2e6VuzsAO7SXg2bVtpRe4E58aCJntyzKPb+mkaMwPQx2sad8fl30IuQYA0AZFv7fShy9QuREI0nY0/zocciDdQwtu+R05uIxcs4OJeWtq7/gvaBtkyLg6k+4a55iOpklENVs+fEVey4N5DzlSJFQ0UbKllzutC/nPwWrfFRqjM3UG2cOnWsAbDDVZpBSjlriFrP8FKbhHATQPSBN93GwjaVjj0OpTfG240lWqPev/NOQVWdSq20HfwbQ16hh7CSL2DegjXTuQBQP2L1gI0CgdMTSg1TI=",
    "__Secure-session_id": "eyJhbGciOiJSUzI1NiIsImtpZCI6InNlc3Npb24tc2VydmljZS1rZXktMjAyNi0wMyIsInR5cCI6IkpXVCJ9.eyJzaWQiOiIwMTlkNjQ3Ny05MjY0LTgwMDEtOTZiYS1jNDNhZGQwNjUxMWUiLCJjcnQiOjE3NzU1MDcwNTEsImV4cCI6MTc3NTUwODg1MSwiaWF0IjoxNzc1NTA3MDUxfQ.v0xJogKYNoT4phgGtdeqVsXefu90D3s4nxTfmKoqKOBY8NxRT0DqAUF20t3HpEi4IS-KL7M3_H0OtMk9hg-nDe63KpuHrdD_azMqrVwxCIPl_eVNCeZRikpCMg9jGaCkOgS6HqKpISBzwvs7kHWoZj2ZiauOEVrn9S0qGegqF-vN3vyDn1r78uQ1B-btTvPmjtV83h2nUJfk6ofS-8iCFR11Exvl5qF3ArhHNCi88WwPfugEgasO0Izon-NmfgWaEsLR24piADFd6h_2RgciB6Rj_hObFN6FBIg2CUAPpZZ7xhYCc0pH_FMPAwx2vDeD4x9-X8p9-nn2ocb2Gohkdw",
    "ssculture": "locale:::es-MX&market:::AR&currency:::ARS",
}

HEADERS = {
    "accept": "application/json",
    "content-type": "application/json",
    "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
    "x-skyscanner-channelid": "website",
    "x-skyscanner-currency": "ARS",
    "x-skyscanner-locale": "es-MX",
    "x-skyscanner-market": "AR",
    "x-skyscanner-traveller-context": "2bcd843c-c401-4201-ace4-24fbb9351389",
    "sec-ch-ua": '"Chromium";v="146", "Not-A.Brand";v="24", "Google Chrome";v="146"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "referer": "https://www.skyscanner.com.ar/transporte/vuelos/buea/bog/261216/270125/?adultsv2=1&cabinclass=economy",
}

# Search params
ORIGIN = "BUEA"
DESTINATION = "BOG"
OUTBOUND = "2026-12-16"
RETURN = "2027-01-25"

# Generate fresh IDs
session_id = str(uuid.uuid4())
call_id = str(uuid.uuid4())
uss_id = str(uuid.uuid4())

print(f"session_id: {session_id}")
print(f"uss_id:     uss_{uss_id}")

token = build_initial_token(session_id, call_id, uss_id, market="AR", countdown=4)
print(f"Token: {token[:60]}...")

# Build cookies
cookies = dict(BASE_COOKIES)
cookies["scanner"] = build_scanner_cookie(ORIGIN, DESTINATION, OUTBOUND, RETURN)

s = requests.Session()
s.headers.update(HEADERS)
s.cookies.update(cookies)

BASE_URL = "https://www.skyscanner.com.ar/g/radar/api/v2/web-unified-search"

print(f"\nMaking initial call...")
r = s.get(f"{BASE_URL}/{token}", timeout=30)
print(f"Status: {r.status_code}, Size: {len(r.content)}")

if r.status_code == 200:
    data = r.json()
    ctx = data.get("context", {})
    itin = data.get("itineraries", {})
    itin_ctx = itin.get("context", {})
    results = itin.get("results", [])

    print(f"Outer status: {ctx.get('status')}")
    print(f"Itineraries status: {itin_ctx.get('status')}")
    print(f"Total results: {itin_ctx.get('totalResults')}")
    print(f"Results in batch: {len(results)}")

    if results:
        print(f"\nFirst result keys: {list(results[0].keys())}")
        with open("data/skyscanner/debug_api_fresh.json", "w") as f:
            json.dump(data, f, indent=2)
        print("Saved to debug_api_fresh.json")

    # Get next token
    next_token = ctx.get("sessionId")
    if next_token:
        print(f"\nNext token: {next_token[:60]}...")
else:
    print(f"Error: {r.text[:500]}")
