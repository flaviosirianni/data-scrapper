"""
Spike: fetch the search results page with real browser cookies and extract flight data.
"""
import re
import json
import requests

COOKIES = {
    "_pxhd": "4Wi7TMKMKqBW5yvg7jNdDn7bRyf03GJvq7sg7I50SxWOlKiIeiyjWJKJSEjcOers9OauQk5TonjtmAl8XhcFRw==:H7m4rtjxYKl/yL3eqa1TxQamWzme44LHN21z/ONdWwUWY/IJ5D2Riutam/WaF0YqH53Ocg0tjM-TAVfF16yzDict886WBp9/ofdXJlgYywo=",
    "traveller_context": "9dc81658-1bb8-40ab-a749-5aad1e3051ab",
    "__Secure-anon_token": "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCIsImtpZCI6ImM3ZGZlYjI2LTlmZjUtNDY4OC1iYjc3LWRiNTY2NWUyNjFkZSJ9.eyJhenAiOiIyNWM3MGZmZDAwN2JkOGQzODM3NyIsImh0dHBzOi8vc2t5c2Nhbm5lci5uZXQvbG9naW5UeXBlIjoiYW5vbnltb3VzIiwiaHR0cHM6Ly9za3lzY2FubmVyLm5ldC91dGlkIjoiOWRjODE2NTgtMWJiOC00MGFiLWE3NDktNWFhZDFlMzA1MWFiIiwiaHR0cHM6Ly9za3lzY2FubmVyLm5ldC9jc3JmIjoiNzdkNjgxMmEzNmI2ZDE0ZDFlMzI0YWZjNGY4MmIxNmUiLCJodHRwczovL3NreXNjYW5uZXIubmV0L2p0aSI6IjNhMzI2YTgzLTYyYjctNDIzYi04ZjEzLTA3YmI4YTQ5NTI2OSIsImlhdCI6MTc3NTI0NjkwNCwiZXhwIjoxODM4MzE4OTA0LCJhdWQiOiJodHRwczovL2dhdGV3YXkuc2t5c2Nhbm5lci5uZXQvaWRlbnRpdHkiLCJpc3MiOiJodHRwczovL3d3dy5za3lzY2FubmVyLm5ldC9zdHRjL2lkZW50aXR5L2p3a3MvcHJvZC8ifQ.UzMkxzn0p-zUjKPzlk2OmuMc_bXaBkM8RRYB1yujhRJpeKxdLv2VXGifqQ0t5rEbZMkbQWmXO34147s_TKnRwYNICb69mBnfnLjfngLUZK2zUn7J_mRfkDSf9-9juQWEdZQTVzKsdg1LHPxg6tGJkxzvAzley8V24NXyoYQRI4GC9ZV-aNqHMnlJdedPIBpJLK0SoTJiioBNAaamI0efLXVpwj67AcVfGbcagZvCqpPh9Py5qeB1XyNbRpOkVw43dtnFN8KLiGIgRXyeTgfR_LbuTUJIGfeUEiDWMoAF0CH34NgzcJVBN_8Wlzy7cpgc87zl3B4X2e4xZtmWuBg3PA",
    "__Secure-anon_csrf_token": "77d6812a36b6d14d1e324afc4f82b16e",
    "abgroup": "99676559",
    "__Secure-ska": "b2ec6150-1f2b-4bba-ac49-982aa16f1230",
    "device_guid": "b2ec6150-1f2b-4bba-ac49-982aa16f1230",
    "preferences": "9dc816581bb840aba7495aad1e3051ab",
    "_pxvid": "dec35fd1-2f98-11f1-bbde-31737b689b98",
    "pxcts": "dff3b42a-2f98-11f1-803f-58ebd0850e12",
    "_gcl_aw": "GCL.1775187834.Cj0KCQjwp7jOBhDGARIsABe7C4diJkuiw5IKEd7dI8u-z5305WuSyvcFFhfHJJE9fDbzrKo55TzCJ3saAuDxEALw_wcB",
    "_gcl_au": "1.1.1657747645.1770758987",
    "_ga": "GA1.1.1994680203.1775246909",
    "ssculture": "locale:::es-MX&market:::CL&currency:::ARS",
    "_px3": "3bade47d687d88954c6f765214b9a1bcc5e4108ef40f4aa0caaf986ae0c28a11:0JmoIJX/ataZZMWyB25H4APDScwNGUQSu2TKwxm+zWz7UMC0sPt9Z8tsMmgB+dKHtBUd5/WWelNPVba8GA9wYw==:1000:PioxKHc+55yP/9cxxrEMON7WK0pP4QXodgR6T2xjpeREfY4XuL0N7trSO38hZk9Ulp6pwutAIgolxQUOWnMeTnFJ6zup7Hpoc+e26F/FzHzabxARFmKhI/2CBOie91b+odb1zBRoXQ1HcmfaEbn9RD7/6e8Wp4P2roDvNjBRSsvK2AnMBA/oP3odDKAhpNgjkiGUXyuRZeWBTQ86lPIGotbc/SJaAX6abnFO1fDB37N5pMBrqtfjEXzvGpnCN24MwUFPjyCPs05ANUn2e6VuzsAO7SXg2bVtpRe4E58aCJntyzKPb+mkaMwPQx2sad8fl30IuQYA0AZFv7fShy9QuREI0nY0/zocciDdQwtu+R05uIxcs4OJeWtq7/gvaBtkyLg6k+4a55iOpklENVs+fEVey4N5DzlSJFQ0UbKllzutC/nPwWrfFRqjM3UG2cOnWsAbDDVZpBSjlriFrP8FKbhHATQPSBN93GwjaVjj0OpTfG240lWqPev/NOQVWdSq20HfwbQ16hh7CSL2DegjXTuQBQP2L1gI0CgdMTSg1TI=",
    "scanner": "currency:::ARS&oym:::2612&oday:::16&wy:::0&iym:::2701&iday:::25&legs:::BUEA|2026-12-16|BOG|BOG|2027-01-25|BUEA&tripType:::return&rtn:::true&preferDirects:::false&outboundAlts:::false&inboundAlts:::false&from:::BUEA&cabinclass:::Economy&adults:::1&adultsV2:::1&children:::0&childrenV2&infants:::0&to:::BOG&parallelSearch:::true",
    "__Secure-session_id": "eyJhbGciOiJSUzI1NiIsImtpZCI6InNlc3Npb24tc2VydmljZS1rZXktMjAyNi0wMyIsInR5cCI6IkpXVCJ9.eyJzaWQiOiIwMTlkNjM4YS01NDlkLTgwMDEtYjc2My1iNDkyODVkNzM3ZDEiLCJjcnQiOjE3NzU0OTE1MDMsImV4cCI6MTc3NTQ5MzU1NSwiaWF0IjoxNzc1NDkxNzU1fQ.xp5ppkkyuZfylgC2ahVf7xcchgZE5gYKol7EyjYlaU9fen0EHDRL73L6HxbTBJ735hUQegbc75XXaV8Hz4swdt-3zNxkRVklBQEnJ6dvBNNwpkUZ_nmx29x7k5sgdJClvNJLWFpp0scMyveHXZz-8CccIzf6r-gp1l9L6KXB7BwAJ2JJGlbZKt0Fwd4ktElGaNyk5DTMz1Z1K7mGKmzQHe0uK1YiL911cylWnPJGFuScuFHjQ5ZaGvBDt3FDQLDxwQJQPsPEVG4HTifcHadeHHL0Dvw1XgrD9Plxv7iu8qAdrIG08eOt88MukZg5Kom9FvRFuMqJNfSwzP0cnAjqnw",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-419,es;q=0.9,en;q=0.8",
    "sec-ch-ua": '"Chromium";v="146", "Not-A.Brand";v="24", "Google Chrome";v="146"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
}

URL = "https://www.espanol.skyscanner.com/transporte/vuelos/buea/bog/261216/270125/?adultsv2=1&cabinclass=economy&childrenv2=&ref=home&rtn=1&preferdirects=false&outboundaltsenabled=false&inboundaltsenabled=false"

s = requests.Session()
s.headers.update(HEADERS)
s.cookies.update(COOKIES)

print(f"Fetching: {URL}")
r = s.get(URL, timeout=30)
print(f"Status: {r.status_code}, Size: {len(r.content)} bytes")

html = r.text

# Save full page
with open("data/skyscanner/debug_page2.html", "w", encoding="utf-8") as f:
    f.write(html)
print("Saved to data/skyscanner/debug_page2.html")

# Search for JSON blobs
print("\n--- Searching for data blobs ---")

# __NEXT_DATA__
m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
if m:
    print(f"Found __NEXT_DATA__: {len(m.group(1))} chars")
    try:
        data = json.loads(m.group(1))
        with open("data/skyscanner/debug_next_data.json", "w") as f:
            json.dump(data, f, indent=2)
        print("  Saved to debug_next_data.json")
        # Look for itineraries
        text = json.dumps(data)
        for keyword in ["itinerary", "itineraries", "price", "airline", "flight", "legs", "segments"]:
            count = text.lower().count(keyword)
            if count > 0:
                print(f"  keyword '{keyword}': {count} occurrences")
    except Exception as e:
        print(f"  Parse error: {e}")
else:
    print("No __NEXT_DATA__ found")

# __SKYSCANNER_CLIENT_CONFIG__
m = re.search(r'window\.__SKYSCANNER_CLIENT_CONFIG__\s*=\s*(\{.*?\});', html, re.DOTALL)
if m:
    print(f"\nFound __SKYSCANNER_CLIENT_CONFIG__: {len(m.group(1))} chars")
else:
    print("No __SKYSCANNER_CLIENT_CONFIG__ found")

# window["__internal"]
m = re.search(r'window\["__internal"\]\s*=\s*(\{.*?\})\s*;', html, re.DOTALL)
if m:
    print(f"\nFound window[\"__internal\"]: {len(m.group(1))} chars")
else:
    print("No window[\"__internal__\"] found")

# Any large JSON-like blob
all_scripts = re.findall(r'<script[^>]*>(.*?)</script>', html, re.DOTALL)
print(f"\nTotal <script> tags: {len(all_scripts)}")
for i, s_content in enumerate(all_scripts):
    if len(s_content) > 5000:
        print(f"  Script #{i}: {len(s_content)} chars")
        # peek at first 200 chars
        print(f"    Preview: {s_content[:200].strip()!r}")

# Check if it's a captcha page
if "px-cloud.net" in html or "Please enable JS" in html or len(html) < 20000:
    print("\n*** LIKELY CAPTCHA PAGE ***")
else:
    print(f"\nPage looks real ({len(html)} chars)")

# Look for pollingSessionId
if "pollingSessionId" in html:
    m = re.search(r'"pollingSessionId"\s*:\s*"([^"]+)"', html)
    print(f"\npollingSessionId found: {m.group(1) if m else 'yes but no value extracted'}")
else:
    print("\nNo pollingSessionId in HTML")
