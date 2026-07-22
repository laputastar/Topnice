"""Verify user-submitted delete list against projects.json.
For each slug: present? scan AI text for smart-hardware signals.
Outputs: not-present slugs + present slugs with signal hits (strong/weak) + evidence snippet.
"""
import json, re
from pathlib import Path

ROOT = Path(r'C:\Users\LuckyF\WorkBuddy\2026-06-04-11-02-53\topnice')
RAW = ROOT / 'scripts' / 'tmp_del_raw_2026-07-22.txt'
PJ = ROOT / 'src' / 'data' / 'projects.json'

# parse slugs from raw list ("- slug | cat | name")
slugs = []
for line in RAW.read_text(encoding='utf-8').splitlines():
    m = re.match(r'^-\s+(\S+?)\s*\|', line)
    if m:
        slugs.append(m.group(1))

data = json.load(open(PJ, encoding='utf-8'))
projs = {p.get('slug'): p for p in data.get('projects', [])}

STRONG = {
    'bluetooth': r'\bbluetooth\b', 'wifi': r'\bwi-?fi\b', 'sensor': r'\bsensors?\b',
    'accelerometer': r'\baccelerometer', 'gyroscope': r'\bgyroscope',
    'microcontroller': r'\bmicrocontroller', 'mcu': r'\bmcu\b', 'chip': r'\bchip',
    'lithium': r'\blithium', 'li-ion': r'\bli-?ion\b', 'lipo': r'\bli-?po\b',
    'rechargeable': r'\brechargeable', 'battery': r'\bbatter', 'motor': r'\bmotor',
    'oled': r'\boled\b', 'e-ink': r'\be-?ink\b', 'programmable': r'\bprogrammable',
    'arduino': r'\barduino\b', 'raspberry': r'\braspberry', 'firmware': r'\bfirmware',
    'ota': r'\bota\b', 'gps': r'\bgps\b', 'nfc': r'\bnfc\b',
    'scanner': r'\bscanner', 'printer': r'\bprinter', 'computer': r'\bcomputer',
    'robot': r'\brobot', 'turbine': r'\bturbine', 'speaker': r'\bspeaker',
    'circuit': r'\bcircuit', 'pcb': r'\bpcb\b', 'usb-c': r'\busb-?c\b',
}
WEAK = {
    'app': r'\bapp\b', 'wireless': r'\bwireless', 'usb': r'\busb\b', 'led': r'\bled\b',
    'camera': r'\bcamera', 'laser': r'\blaser', 'rfid': r'\brfid\b',
    'electronic': r'\belectronic', 'solar': r'\bsolar', 'smart': r'\bsmart',
    'ai': r'\bai\b', 'charging': r'\bcharg', 'display': r'\bdisplay',
    'screen': r'\bscreen', 'ring': r'\bring\b', 'hub': r'\bhub\b',
    'module': r'\bmodule', 'connectivity': r'\bconnectiv',
}

def text_of(p):
    parts = []
    for k in ('name','blurb','ai_intro_en','hw_reason'):
        if p.get(k): parts.append(str(p[k]))
    for k in ('ai_highlights_en','ai_specs_en','ai_tags','ai_use_cases_en'):
        v = p.get(k)
        if isinstance(v, list):
            parts.extend(str(x) for x in v if x)
    return ' '.join(parts)

def scan(text):
    strong_hits, weak_hits = {}, {}
    for name, pat in STRONG.items():
        m = re.search(pat, text, re.I)
        if m:
            s = max(0, m.start()-40); e = min(len(text), m.end()+40)
            strong_hits[name] = text[s:e].replace('\n',' ')
    for name, pat in WEAK.items():
        m = re.search(pat, text, re.I)
        if m:
            s = max(0, m.start()-40); e = min(len(text), m.end()+40)
            weak_hits[name] = text[s:e].replace('\n',' ')
    return strong_hits, weak_hits

present, not_present = [], []
with_strong, with_weak_only = [], []
for s in slugs:
    if s in projs:
        present.append(s)
        sh, wh = scan(text_of(projs[s]))
        if sh:
            with_strong.append((s, projs[s].get('category',''), sh, wh))
        elif wh:
            with_weak_only.append((s, projs[s].get('category',''), wh))
    else:
        not_present.append(s)

print(f"Parsed slugs: {len(slugs)}")
print(f"Present in projects.json: {len(present)}")
print(f"NOT present (already deleted / blacklisted / typo): {len(not_present)}")
print("="*70)
print(f"\n### A) STRONG signal hits — likely DISAGREEMENTS ({len(with_strong)})")
for s, cat, sh, wh in sorted(with_strong):
    print(f"\n• {s}  [{cat}]")
    for kw, snip in sh.items():
        print(f"    STRONG[{kw}]: …{snip}…")
    if wh:
        print(f"    (also weak: {', '.join(wh.keys())})")

print("\n" + "="*70)
print(f"\n### B) WEAK-only signal hits — review ({len(with_weak_only)})")
for s, cat, wh in sorted(with_weak_only):
    print(f"• {s}  [{cat}] -> {', '.join(wh.keys())}")

print("\n" + "="*70)
print(f"\n### C) NOT PRESENT ({len(not_present)})")
for s in sorted(not_present):
    print(f"  - {s}")
