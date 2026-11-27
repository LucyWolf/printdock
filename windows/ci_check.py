"""Prueft auf einem echten Windows (GitHub-Runner), was sich unter Linux nicht pruefen laesst.
Laeuft im Release-Workflow vor dem Bauen; jeder Fehler stoppt das Windows-Setup."""
import importlib.util
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
spec = importlib.util.spec_from_file_location("pd", os.path.join(os.path.dirname(__file__), "..", "printdock.py"))
pd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pd)
from PySide6 import QtWidgets, QtPdf, QtPrintSupport  # noqa: F401  – muessen in der Windows-Fassung da sein

app = QtWidgets.QApplication([])
assert pd.WINDOWS, "kein Windows?"
print("Systemsprache:", pd.system_language(), "| Ordner:", pd.INSTALL_DIR)

rc, out, err = pd.powershell("(Get-Command Add-Printer).Parameters.Keys -join ','")
print("Add-Printer kennt:", out.strip())
assert rc == 0 and "IppURL" in out, "Add-Printer -IppURL fehlt – Einrichten muesste anders laufen"

printers = pd.discover_windows()
print("Drucker:", [(p.queue, p.host, p.connection) for p in printers])
assert all("pdf" not in (p.queue or "").lower() for p in printers), "virtuelle Drucker nicht ausgefiltert"

names = [d.get("Name") for d in pd.ps_json("Get-Printer | Select-Object Name")]
print("Alle Warteschlangen:", names)
if names:
    print("Auftraege:", pd.win_jobs(names[0]))

print("mDNS:", pd.mdns_browse("_ipp._tcp.local.", 1.0))
print("Scanner:", pd.list_scanners())
print("Sprache de:", pd.language_table("de") == {}, "| tr:", pd.tr("Drucker"))
pd.notify("PrintDock", "Test")
print("ok")
