#!/usr/bin/env python3
"""Round-3 re-review: for the remaining deletion candidates (after user confirmed
35 keeps), re-scan AI-extracted fields for any genuine electronic/smart-hardware
signal that may have been missed. Surfaces possible additional keepers.

No external LLM (sandbox has no creds); uses the AI-extracted fields already in
projects.json + reasoning-style signal scan with negation guarding.
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
RAW = Path(__file__).parent / "tmp_del_raw_2026-07-22.txt"
PROJECTS = ROOT / "src" / "data" / "projects.json"

# 35 user-confirmed keeps (28 strong + 6 boundary + aironox)
KEEP = {
    # 28 strong from deletion-review
    "aiscan-o1-3d-gaussian-all-in-one-3d-scanner",
    "kare-3d-desktop-metal-3d-printer",
    "lini-your-everywhere-open-source-mini-computer-0",
    "volatco",
    "memoir-a-paper-like-e-ink-digital-frame",
    "hamu-high-accuracy-measurement-unit",
    "advanced-fishing-lure",
    "autofill-resin-management-system-for-3d-printers",
    "blackbird-coffee-gear-coffee-canister-and-vacuum-pump-0",
    "blast-air",
    "campcore--light-up-every-adventure",
    "cladist-titan-15-1-torque-redefines-power-and-precision",
    "compact-size-massive-power-1367mm-pocket-friendly-design",
    "dadbodd",
    "hunt-h2-this-tiny-flashlight-has-a-battery-swap-station",
    "jetro-keep-freshness-longer",
    "kovadex-x1-your-100w-rgb-desktop-hub-with-dual-monitor-arm",
    "luminyx-nfs-1-shadow-fighting-safety-eyewear",
    "mi2-window-fan",
    "nevilo-smart-cooler-travel-anywhere-with-insulin-freedom",
    "oncobag",
    "p10-elite-pss-compatible-taekwondo-foot-protector",
    "pfm",
    "swiftbuild",
    "tankogo-the-portable-propane-free-heated-shower-tank",
    "titaner-tiverse-the-infinite-modular-titanium-belt-buckle",
    "uknight-a-pixel-lantern-speaker-for-your-desk",
    "xatrix",
    # 6 boundary
    "light-up-morale-patch-18-day-dual-color-velcro-badge",
    "verolite-the-modular-titanium-pocket-repair-system-pen",
    "drill-turbine",
    "securidoor",
    "fitn-focus-0",
    "yinyang-shades-adjustable-cyberpunk-sunglasses-0",
    # aironox confirmed keep this round
    "aironox-go-wrinkle-free-clothes-wherever-you-land",
}

# Positive electronic/smart signals
POS = [
    r"battery", r"lithium", r"rechargeable", r"li-ion", r"li-po", r"18650",
    r"21700", r"\b\d+\s?mah\b", r"power ?bank", r"10000mah",
    r"bluetooth", r"\bble\b", r"wi-?fi", r"wireless", r"\biot\b", r"\bnfc\b",
    r"\brfid\b", r"zigbee", r"\b4g\b", r"\b5g\b", r"\bgps\b",
    r"\bapp\b", r"smartphone", r"\bios\b", r"android", r"app-controlled",
    r"sensor", r"accelerometer", r"gyroscope", r"thermometer", r"humidity",
    r"chip", r"microcontroller", r"\bmcu\b", r"esp32", r"arduino",
    r"raspberry", r"\bpcb\b", r"circuit", r"firmware", r"processor",
    r"\bcpu\b", r"\bgpu\b", r"neural", r"gaussian",
    r"display", r"screen", r"\boled\b", r"\blcd\b", r"e-?ink", r"\bled\b",
    r"\brgb\b", r"touchscreen", r"digital display",
    r"motor", r"brushless", r"actuator", r"solenoid", r"servo", r"\bpump\b",
    r"compressor", r"vibration", r"vibrat",
    r"usb-?c", r"\busb\b", r"charging", r"charger", r"adapter", r"solar",
    r"photovoltaic", r"dc motor",
    r"speaker", r"microphone", r"earphone", r"headphone",
    r"peltier", r"thermoelectric", r"heating element", r"ceramic heater",
    r"\bsmart\b", r"programmable", r"firmware", r"ota\b", r"over-?the-?air",
]
NEG = [r"\bno\b", r"\bnot\b", r"without", r"zero", r"\bnone\b", r"free of",
       r"passive", r"manual", r"non-electric", r"no battery", r"no wi-?fi",
       r"no motor", r"no electronics", r"non-electric", r"hand-?crank",
       r"gravity", r"purely mechanical"]


def scan(text):
    """Return list of (signal, snippet) for positive hits not in negation context."""
    if not text:
        return []
    low = text.lower()
    hits = []
    for pat in POS:
        for m in re.finditer(pat, low):
            s, e = m.start(), m.end()
            ctx = low[max(0, s - 45): min(len(low), e + 45)]
            # negation guard
            if any(re.search(n, ctx) for n in NEG):
                continue
            snippet = text[max(0, s - 35): min(len(text), e + 35)].strip()
            hits.append((m.group(0), snippet))
    return hits


def main():
    raw = RAW.read_text(encoding="utf-8")
    del_slugs = re.findall(r"^- (.+?) \|", raw, re.MULTILINE)
    print(f"Deletion list slugs parsed: {len(del_slugs)}")

    data = json.loads(PROJECTS.read_text(encoding="utf-8"))
    by_slug = {p.get("slug"): p for p in data["projects"]}
    print(f"Projects in projects.json: {len(data['projects'])}")

    kept, notfound, candidates = [], [], []
    for s in del_slugs:
        if s in KEEP:
            kept.append(s)
        elif s not in by_slug:
            notfound.append(s)
        else:
            candidates.append(s)

    print(f"Kept (user-confirmed): {len(kept)}")
    print(f"Not in library: {len(notfound)} -> {notfound}")
    print(f"Candidates for deletion: {len(candidates)}")

    flagged = []  # (slug, name, signals, snippet, text)
    clean = []
    for s in candidates:
        p = by_slug[s]
        name = p.get("name", "")
        cat = p.get("category", "")
        text = " ".join([
            str(p.get("ai_intro_en", "") or ""),
            str(p.get("ai_highlights_en", "") or ""),
            str(p.get("ai_specs_en", "") or ""),
            str(p.get("ai_tags", "") or ""),
            name,
        ])
        hits = scan(text)
        if hits:
            # de-dup signals
            seen = []
            for sig, snip in hits:
                if sig not in [x[0] for x in seen]:
                    seen.append((sig, snip))
            flagged.append((s, name, cat, seen, text))
        else:
            clean.append(s)

    print(f"\n=== FLAGGED (possible additional keepers): {len(flagged)} ===")
    for s, name, cat, hits, _ in flagged:
        sigs = ", ".join(sorted({h[0] for h in hits}))
        print(f"\n- {s} | {cat} | {name}")
        print(f"    signals: {sigs}")
        # show one representative snippet
        snip = hits[0][1].replace("\n", " ")
        print(f"    e.g.: …{snip}…")

    print(f"\n=== CLEAN DELETE (no electronic signal): {len(clean)} ===")
    # print them grouped maybe
    for s in clean:
        print(f"   - {s}")

    # write flagged detail to file for review
    out = ROOT.parent / "rereview-flagged-2026-07-22.md"
    lines = ["# Round-3 Re-review Flagged Candidates (possible additional keepers)", ""]
    lines.append(f"Candidates scanned: {len(candidates)}")
    lines.append(f"Flagged (electronic signal present): {len(flagged)}")
    lines.append(f"Clean delete (no signal): {len(clean)}")
    lines.append("")
    lines.append("## Flagged — needs your call")
    lines.append("")
    for s, name, cat, hits, text in flagged:
        lines.append(f"### `{s}` | {cat} | {name}")
        lines.append("")
        lines.append("**Signals:** " + ", ".join(sorted({h[0] for h in hits})))
        lines.append("")
        lines.append("**AI intro:** " + str(by_slug[s].get("ai_intro_en", "") or "(empty)")[:600])
        lines.append("")
        lines.append("**Highlights:** " + str(by_slug[s].get("ai_highlights_en", "") or "(empty)")[:600])
        lines.append("")
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n📝 Flagged detail written: {out}")


if __name__ == "__main__":
    main()
