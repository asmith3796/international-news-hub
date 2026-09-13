"""US state outlines for the Ballot tab (v2.6, 9/13). Decodes the us-atlas states-10m TopoJSON (Census/Natural Earth derived, public
domain; already projected to a 960x600 Albers USA layout) into one SVG path per state, keyed by USPS code, saved as us_states.json."""
import json, os
ROOT = os.path.dirname(os.path.abspath(__file__)); SRC = os.path.join(ROOT, "us-states-10m.json"); OUT = os.path.join(ROOT, "us_states.json")
FIPS = {"01":"AL","02":"AK","04":"AZ","05":"AR","06":"CA","08":"CO","09":"CT","10":"DE","11":"DC","12":"FL","13":"GA","15":"HI","16":"ID","17":"IL","18":"IN","19":"IA","20":"KS","21":"KY","22":"LA","23":"ME","24":"MD","25":"MA","26":"MI","27":"MN","28":"MS","29":"MO","30":"MT","31":"NE","32":"NV","33":"NH","34":"NJ","35":"NM","36":"NY","37":"NC","38":"ND","39":"OH","40":"OK","41":"OR","42":"PA","44":"RI","45":"SC","46":"SD","47":"TN","48":"TX","49":"UT","50":"VT","51":"VA","53":"WA","54":"WV","55":"WI","56":"WY"}
topo = json.load(open(SRC)); sc = topo["transform"]["scale"]; tr = topo["transform"]["translate"]
def arc(i):
    rev = i < 0; a = topo["arcs"][~i if rev else i]; x = y = 0; pts = []
    for dx, dy in a: x += dx; y += dy; pts.append((x * sc[0] + tr[0], y * sc[1] + tr[1]))
    return pts[::-1] if rev else pts
def ring(arcs):
    pts = []
    for i in arcs:
        p = arc(i); pts += p[1:] if pts else p
    return pts
out = {}
for g in topo["objects"]["states"]["geometries"]:
    code = FIPS.get(str(g["id"]).zfill(2))
    if not code: continue
    polys = [g["arcs"]] if g["type"] == "Polygon" else g["arcs"]
    d = ""
    for poly in polys:
        for arcs in poly:
            r = ring(arcs); d += "M" + " L".join(f"{x:.1f} {y:.1f}" for x, y in r[::2] or r) + " Z "
    out[code] = d.strip()
json.dump(out, open(OUT, "w")); print(len(out), "states;", os.path.getsize(OUT), "bytes")
