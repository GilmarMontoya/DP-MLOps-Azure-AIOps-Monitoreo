import json, subprocess, sys, urllib.request
url = sys.argv[1]; dash = json.load(open(sys.argv[2]))["dashboard"]
tok = subprocess.run(["az","account","get-access-token","--resource","ce34e7e5-485f-4d76-964f-b3d2b16d1e4f","--query","accessToken","-o","tsv"],capture_output=True,text=True).stdout.strip()
for p in dash["panels"]:
    if p["type"] == "row": continue
    t = json.loads(json.dumps(p["targets"][0]).replace("${ds}", "azure-monitor-oob"))
    body = {"from": "now-24h", "to": "now", "queries": [t]}
    req = urllib.request.Request(url + "/api/ds/query", data=json.dumps(body).encode(), headers={"Authorization": "Bearer " + tok, "Content-Type": "application/json"})
    try:
        r = json.load(urllib.request.urlopen(req, timeout=60))["results"]["A"]
        if r.get("error"): print(f"ERROR  {p['title'][:55]:55} {r['error'][:150]}"); continue
        filas = sum(len(f["data"]["values"][0]) if f.get("data",{}).get("values") else 0 for f in r.get("frames", []))
        print(f"{'OK' if filas else 'VACIO':6} {p['title'][:55]:55} frames={len(r.get('frames',[]))} filas={filas}")
    except Exception as e:
        print(f"FALLA  {p['title'][:55]:55} {str(e)[:150]} {getattr(e,'read',lambda:b'')()[:200]}")
