import json
import urllib.parse
import urllib.request

for ticker in ["XAUUSD=X", "GC=F", "^FCHI", "^IXIC", "^FTSE", "^GSPC"]:
    url = (
        "https://query1.finance.yahoo.com/v8/finance/chart/"
        f"{urllib.parse.quote(ticker)}?interval=1d&range=5d"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.load(r)
        meta = data["chart"]["result"][0]["meta"]
        print(ticker, {
            "price": meta.get("regularMarketPrice"),
            "chartPreviousClose": meta.get("chartPreviousClose"),
            "previousClose": meta.get("previousClose"),
        })
    except Exception as e:
        print(ticker, "ERROR", repr(e))
