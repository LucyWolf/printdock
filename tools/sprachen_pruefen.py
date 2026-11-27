#!/usr/bin/env python3
"""Uebersetzungen pruefen: jeder Text, den printdock.py mit tr("…") anzeigt, gegen sprachen/*.json.

Fehler (Abbruch): Platzhalter wie {0} weichen ab, Datei ist kein gueltiges JSON.
Hinweis: Text fehlt in einer Sprache – dann erscheint dort Englisch bzw. Deutsch, nichts geht kaputt.
Neue Texte: in jede Datei unter sprachen/ eintragen (Schluessel = deutscher Text, genau wie im Code).
"""
import ast, glob, json, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src = open(os.path.join(ROOT, "printdock.py"), encoding="utf-8").read()
keys = []
for n in ast.walk(ast.parse(src)):
    if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "tr" and n.args \
            and isinstance(n.args[0], ast.Constant) and n.args[0].value not in keys:
        keys.append(n.args[0].value)
ph = lambda s: sorted(re.findall(r"\{[^{}]*\}", s))
fehler = 0
for path in sorted(glob.glob(os.path.join(ROOT, "sprachen", "*.json"))):
    code = os.path.basename(path)[:-5]
    try:
        data = json.load(open(path, encoding="utf-8"))
    except ValueError as e:
        print(f"FEHLER {code}: kein gültiges JSON ({e})"); fehler += 1; continue
    for k, v in data.items():
        if ph(k) != ph(v):
            print(f"FEHLER {code}: Platzhalter passen nicht: {k!r} -> {v!r}"); fehler += 1
    missing = [k for k in keys if k not in data]
    if missing:
        print(f"Hinweis {code}: {len(missing)} Text(e) fehlen, z. B. {missing[0]!r}")
print(f"{len(keys)} Texte, {len(glob.glob(os.path.join(ROOT, 'sprachen', '*.json')))} Sprachen, {fehler} Fehler")
sys.exit(1 if fehler else 0)
