"""Country outline art for the hub (v2, 9/11). Reads the world-atlas 50m TopoJSON (Natural Earth, public domain), decodes each
country's geometry, and writes one SVG silhouette per country to site/maps/<CC>.svg, fitted to a 1000x700 box with a little padding.
Run once (python3 maps.py); re-run only if the country list changes. Needs countries.json for the ISO numeric ids."""
import json, os, math, urllib.request
ROOT = os.path.dirname(os.path.abspath(__file__)); OUT = os.path.join(ROOT, "site", "maps"); os.makedirs(OUT, exist_ok=True)
SRC = os.path.join(ROOT, "world-atlas-50m.json")
if not os.path.exists(SRC):
    urllib.request.urlretrieve("https://cdn.jsdelivr.net/npm/world-atlas@2/countries-50m.json", SRC)
topo = json.load(open(SRC)); sc = topo["transform"]["scale"]; tr = topo["transform"]["translate"]

def arc_points(i):
    """Decode one arc (delta-encoded, quantized) into lon/lat points; negative index means reversed."""
    rev = i < 0; a = topo["arcs"][~i if rev else i]; x = y = 0; pts = []
    for dx, dy in a:
        x += dx; y += dy; pts.append((x * sc[0] + tr[0], y * sc[1] + tr[1]))
    return pts[::-1] if rev else pts

def ring(arcs):
    pts = []
    for i in arcs:
        p = arc_points(i); pts += p[1:] if pts else p
    return pts

def polygons(geom):
    if geom["type"] == "Polygon": return [geom["arcs"]]
    if geom["type"] == "MultiPolygon": return geom["arcs"]
    return []

def project(lon, lat):
    """Simple equirectangular with latitude-cosine correction at the country's center; good enough for a silhouette."""
    return lon, lat

def svg_for(numeric_id):
    geoms = [g for g in topo["objects"]["countries"]["geometries"] if str(g.get("id")) == str(numeric_id).zfill(3) or str(g.get("id")) == str(int(numeric_id))]
    if not geoms: return None
    rings = []
    for g in geoms:
        for poly in polygons(g):
            for arcs in poly: rings.append(ring(arcs))
    # drop tiny islands far from the mainland for a cleaner silhouette: keep rings whose bbox area is > 0.2% of the largest
    def area(r): xs=[p[0] for p in r]; ys=[p[1] for p in r]; return (max(xs)-min(xs))*(max(ys)-min(ys))
    big = max(area(r) for r in rings); rings = [r for r in rings if area(r) >= 0.002 * big]
    # handle the antimeridian (Russia): shift negative longitudes east
    if numeric_id in ("643",):
        rings = [[(lon + 360 if lon < 0 else lon, lat) for lon, lat in r] for r in rings]
    allp = [p for r in rings for p in r]; lat0 = sum(p[1] for p in allp) / len(allp); k = math.cos(math.radians(lat0))
    pts = [[(lon * k, -lat) for lon, lat in r] for r in rings]
    xs = [p[0] for r in pts for p in r]; ys = [p[1] for r in pts for p in r]
    minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys); w, h = maxx - minx, maxy - miny
    W, H, pad = 1000.0, 700.0, 40.0; s = min((W - 2 * pad) / w, (H - 2 * pad) / h)
    ox = (W - w * s) / 2 - minx * s; oy = (H - h * s) / 2 - miny * s
    d = ""
    for r in pts:
        d += "M" + " L".join(f"{x * s + ox:.1f} {y * s + oy:.1f}" for x, y in r) + " Z "
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {int(W)} {int(H)}" preserveAspectRatio="xMidYMid meet"><path d="{d.strip()}" fill="currentColor" fill-rule="evenodd"/></svg>'

if __name__ == "__main__":
    countries = json.load(open(os.path.join(ROOT, "countries.json")))
    for cc, c in countries.items():
        s = svg_for(c["numeric"])
        if not s: print("no geometry for", cc); continue
        open(os.path.join(OUT, f"{cc}.svg"), "w").write(s); print(cc, len(s), "bytes")

def world_svg():
    """All countries as one silhouette (equirectangular), for the home hero."""
    d = ""
    for g in topo["objects"]["countries"]["geometries"]:
        for poly in polygons(g):
            for arcs in poly:
                r = ring(arcs)
                if len(r) < 12: continue                                   # skip specks
                pts = [((lon + 180) * (1000 / 360), (90 - lat) * (500 / 180)) for lon, lat in r]
                xs=[p[0] for p in pts]; ys=[p[1] for p in pts]
                if (max(xs)-min(xs))*(max(ys)-min(ys)) < 4: continue          # tiny islands
                d += "M" + " L".join(f"{x:.0f} {y:.0f}" for x, y in pts[::2]) + " Z "
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 460" preserveAspectRatio="xMidYMid meet"><path d="{d.strip()}" fill="currentColor" fill-rule="evenodd" transform="translate(0,-20)"/></svg>'
if __name__ == "__main__":
    open(os.path.join(OUT, "WORLD.svg"), "w").write(world_svg()); print("WORLD", os.path.getsize(os.path.join(OUT, "WORLD.svg")), "bytes")
