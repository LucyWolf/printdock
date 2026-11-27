#!/usr/bin/env python3
# PrintDock (frueher Druckzentrale) – Drucken, Scannen, Fax, Tintenstand und Wartung fuer Drucker (alle Marken).
# Eigenstaendig, ohne Herstellersoftware: CUPS und IPP (Drucken, Status, Tinte), SANE mit sane-airscan/eSCL
# (Scannen), bei HP-Geraeten deren eingebaute Weboberflaeche (Reinigung, Berichte).
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

from PySide6 import QtCore, QtGui, QtWidgets

try:
    import cups
except ImportError:
    cups = None
try:
    from PIL import Image
except ImportError:
    Image = None

APP_NAME = "PrintDock"
APP_VERSION = "1.0.53"
# Frueher „HP Druckzentrale“, dann „Druckzentrale“; migrate_old_install() zieht alte Installationen um.
UPDATE_REPO = "LucyWolf/printdock"
# Mit echten Geraeten ausprobiert (Modell, Verbindung, was geprueft wurde)
TESTED_PRINTERS = ["HP OfficeJet Pro 8620", "HP Color Laser MFP 178nwg"]
WINDOWS = sys.platform == "win32"
FROZEN = bool(getattr(sys, "frozen", False))   # als .exe gebaut (Windows-Setup)
INSTALL_DIR = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "PrintDock") if WINDOWS \
    else os.path.expanduser("~/.local/share/printdock")
DESKTOP_FILE = os.path.expanduser("~/.local/share/applications/printdock.desktop")
OLD_NAMES = ["hp-druckzentrale", "druckzentrale"]   # fruehere Ordner-, Menue- und Einstellungsnamen

# ---------- Sprachen ----------
# Die Texte im Programm sind deutsch; tr() schlaegt sie in der gewaehlten Sprache nach. Wie bei den Druckervorlagen
# wird nur die eigene Sprache geladen (sprachen/<kuerzel>.json im GitHub-Projekt) und gemerkt, dazu Englisch als
# Rueckfall fuer Texte, die noch nicht uebersetzt sind. Fehlt alles, bleibt es deutsch – nichts geht kaputt.
# Die Wahl steht in ~/.local/share/printdock/sprache (schreibt auch der Installer); ohne Eintrag gilt die Systemsprache.
LANGUAGES = {"de": "Deutsch", "en": "English", "fr": "Français", "es": "Español", "it": "Italiano",
             "pt": "Português", "nl": "Nederlands", "pl": "Polski", "tr": "Türkçe", "ru": "Русский",
             "uk": "Українська", "zh": "中文", "ja": "日本語"}
LANG_DIR = os.path.join(INSTALL_DIR, "sprachen")
LANG_FILE = os.path.join(INSTALL_DIR, "sprache")
LANG_URL = "https://raw.githubusercontent.com/{repo}/main/sprachen/{code}.json"


def system_language():
    if WINDOWS:   # Windows setzt kein LANG: Sprache der Oberflaeche beim System erfragen
        try:
            import ctypes
            import locale
            code = locale.windows_locale.get(ctypes.windll.kernel32.GetUserDefaultUILanguage(), "")[:2].lower()
            return code if code in LANGUAGES else "en"
        except Exception:
            return "en"
    for var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        code = (os.environ.get(var) or "").split(":")[0][:2].lower()
        if code in LANGUAGES:
            return code
        if code and code not in ("c", "po"):
            return "en"   # Sprache, die PrintDock nicht kennt: Englisch versteht man eher als Deutsch
    return "en"


def chosen_language():
    try:
        with open(LANG_FILE, encoding="utf-8") as f:
            code = f.read().strip()
        if code in LANGUAGES:
            return code
    except OSError:
        pass
    return system_language()


def language_table(code, refresh=False):
    """Uebersetzungen einer Sprache (deutscher Text -> Uebersetzung); einmal laden, dann gemerkt."""
    if code == "de" or code not in LANGUAGES:
        return {}
    path = os.path.join(LANG_DIR, code + ".json")
    if refresh or not os.path.exists(path):
        try:
            with urllib.request.urlopen(LANG_URL.format(repo=UPDATE_REPO, code=code), timeout=6) as r:
                data = json.loads(r.read().decode("utf-8"))
            if isinstance(data, dict):
                os.makedirs(LANG_DIR, exist_ok=True)
                tmp = f"{path}.{os.getpid()}.tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=1)
                os.replace(tmp, path)
        except (OSError, ValueError):
            pass   # kein Netz: gemerkte Fassung nehmen, sonst deutsch
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, str) and v}
    except (OSError, ValueError):
        return {}


LANG = chosen_language()
_TR = language_table(LANG)
_TR_FALLBACK = language_table("en") if LANG not in ("de", "en") else {}


def tr(text, *args):
    """Text in der gewaehlten Sprache; Platzhalter {0}, {1} … werden mit args gefuellt."""
    t = _TR.get(text) or _TR_FALLBACK.get(text) or text
    if args:
        try:
            return t.format(*args)
        except (IndexError, KeyError, ValueError):
            return text.format(*args)   # kaputte Uebersetzung: lieber deutsch als Absturz
    return t


def refresh_languages():
    """Im Hintergrund: Sprachdateien einmal am Tag neu holen, damit neue Uebersetzungen ankommen."""
    for code in {LANG} | ({"en"} if _TR_FALLBACK else set()):
        path = os.path.join(LANG_DIR, code + ".json")
        try:
            old = time.time() - os.path.getmtime(path) > 86400
        except OSError:
            old = code != "de"
        if old:
            language_table(code, refresh=True)
NEEDED_PACKAGES = ["python-pycups", "sane", "sane-airscan", "ipp-usb", "python-pillow"]


# ---------- Hilfen ----------
def run(cmd, timeout=30, cwd=None):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd,
                           **({"creationflags": 0x08000000, "encoding": "utf-8", "errors": "replace"} if WINDOWS else {}))
        return r.returncode, r.stdout, r.stderr
    except FileNotFoundError:
        return -1, "", tr("{0} nicht gefunden", cmd[0])
    except subprocess.TimeoutExpired:
        return -1, "", tr("{0}: Zeitüberschreitung", cmd[0])


def is_hp(text):
    return bool(re.search(r"\b(hp|hewlett[- ]?packard)\b", text or "", re.I)) or (text or "").startswith(("hp:", "hpfax:", "hpaio:"))


def norm(text):
    t = (text or "").lower().replace("hewlett-packard", "hp").replace("hewlett packard", "hp")
    t = re.sub(r"\s+-\s+(ipp everywhere|hpcups.*|hplip.*|driverless.*)$", "", t)   # Treiberzusatz der Warteschlange
    t = re.sub(r"^hp\s+", "", t)
    return re.sub(r"[^a-z0-9]", "", t)


class Bridge(QtCore.QObject):
    call = QtCore.Signal(object)


_bridge = None


def ui(fn):
    """Fuehrt fn im Oberflaechen-Thread aus."""
    _bridge.call.emit(fn)


def bg(fn, done=None):
    """fn im Hintergrund, Ergebnis (ok, wert) an done im Oberflaechen-Thread."""
    def work():
        try:
            res = (True, fn())
        except Exception as e:
            res = (False, e)
        if done:
            ui(lambda: done(*res))
    threading.Thread(target=work, daemon=True).start()


# ---------- Drucker ----------
class Printer:
    FIELDS = ("queue", "uris", "model", "info", "serial", "host", "fax", "server_id", "location")

    def to_dict(self):
        return {k: getattr(self, k) for k in self.FIELDS}

    @classmethod
    def from_dict(cls, d):
        p = cls()
        for k in cls.FIELDS:
            if k in d:
                setattr(p, k, d[k])
        return p

    def __init__(self):
        self.queue = None        # CUPS-Warteschlange, falls eingerichtet
        self.uris = []
        self.model = ""
        self.info = ""
        self.serial = ""
        self.host = ""          # IP-Adresse im Netz (fuer Weboberflaeche und direkte IPP-Abfrage)
        self.fax = None         # kann PC-Fax (None = noch nicht geprueft)
        self.template = None    # Druckervorlage (nicht gespeichert, liegt als Datei vor)
        self.server_id = None   # vom PrintDock-Server zugewiesen (dessen Kennung), sonst None
        self.location = ""      # Standort laut Server, z. B. „Büro 2.14“

    @property
    def uri(self):
        return self.uris[0] if self.uris else ""

    @property
    def connection(self):
        u = " ".join(self.uris)
        if self.server_id:
            return tr("Server")
        if "usb" in u or re.search(r"://(localhost|127\.0\.0\.1)", u):
            return "USB"
        return tr("Netzwerk (LAN/WLAN)")

    @property
    def title(self):
        return self.info or self.model or self.queue or self.uri

    def best_setup_uri(self):
        # Treiberlos (IPP Everywhere) zuerst, dann rohes USB
        for pref in ("ipps://", "ipp://", "dnssd://", "usb://"):
            u = next((x for x in self.uris if x.startswith(pref)), None)
            if u:
                return u
        return self.uri

    def ipp_uri(self):
        if self.queue:
            return None
        if re.fullmatch(r"[\d.]+", self.host or ""):
            return f"ipp://{self.host}:631/ipp/print"   # mDNS-Namen kann CUPS hier nicht aufloesen
        return next((u for u in self.uris if u.startswith(("ipp://", "ipps://")) and ".local" not in u), None)


# ---------- Windows ----------
# Unter Windows gibt es kein CUPS, SANE und Avahi. PrintDock spricht dort selbst mit den Geraeten: IPP fuer Status und
# Fuellstaende, eSCL zum Scannen, mDNS zum Finden. Gedruckt wird ueber die Windows-Druckerwarteschlange (Qt), eingerichtet
# mit den Windows-eigenen PowerShell-Befehlen. Nur offene Standards, keine Herstellersoftware – wie unter Linux.
def powershell(script, timeout=60):
    return run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command",
                "[Console]::OutputEncoding=[Text.Encoding]::UTF8; $ErrorActionPreference='Stop'; " + script], timeout)


def ps_json(script, timeout=60):
    rc, out, err = powershell(script + " | ConvertTo-Json -Depth 3 -Compress", timeout)
    if rc != 0:
        raise RuntimeError((err or out).strip()[:300] or "PowerShell")
    out = out.strip()
    if not out:
        return []
    data = json.loads(out)
    return data if isinstance(data, list) else [data]


def ps_quote(s):
    return "'" + str(s).replace("'", "''") + "'"


# --- IPP (RFC 8010), nur was PrintDock braucht: Attribute eines Druckers abfragen ---
def _ipp_attr(tag, name, value):
    n = name.encode("utf-8")
    v = value if isinstance(value, bytes) else str(value).encode("utf-8")
    return bytes([tag]) + len(n).to_bytes(2, "big") + n + len(v).to_bytes(2, "big") + v


def ipp_parse(data):
    """IPP-Antwort -> {Name: Wert oder Liste}. Inhalte von Sammlungen (z. B. media-col) werden uebersprungen."""
    if len(data) < 8:
        raise RuntimeError("IPP: leere Antwort")
    status = int.from_bytes(data[2:4], "big")
    if status >= 0x0400:
        raise RuntimeError(f"IPP-Status 0x{status:04x}")
    attrs, name, depth, i = {}, None, 0, 8
    while i < len(data):
        tag = data[i]
        i += 1
        if tag == 0x03:
            break
        if tag < 0x10:   # neue Attributgruppe
            name = None
            continue
        nl = int.from_bytes(data[i:i + 2], "big")
        n = data[i + 2:i + 2 + nl].decode("utf-8", "replace")
        i += 2 + nl
        vl = int.from_bytes(data[i:i + 2], "big")
        v = data[i + 2:i + 2 + vl]
        i += 2 + vl
        if tag == 0x34:
            depth += 1
            continue
        if tag == 0x37:
            depth = max(0, depth - 1)
            continue
        if depth or tag == 0x4A or tag in (0x10, 0x12, 0x13):
            continue
        if tag in (0x21, 0x23):
            val = int.from_bytes(v, "big", signed=True) if v else 0
        elif tag == 0x22:
            val = bool(v and v[0])
        elif tag in (0x35, 0x36):
            ll = int.from_bytes(v[0:2], "big")
            tl = int.from_bytes(v[2 + ll:4 + ll], "big")
            val = v[4 + ll:4 + ll + tl].decode("utf-8", "replace")
        elif tag in (0x30, 0x31, 0x32, 0x33):
            continue   # Datum, Aufloesung, Bereich: hier nicht gebraucht
        else:
            val = v.decode("utf-8", "replace")
        if n:
            name = n
            attrs[name] = val
        elif name is not None:
            old = attrs.get(name)
            attrs[name] = (old if isinstance(old, list) else [old]) + [val]
    return attrs


def ipp_get_attributes(host, requested, port=631, path="/ipp/print", timeout=8):
    body = b"\x02\x00" + (0x000B).to_bytes(2, "big") + (1).to_bytes(4, "big") + b"\x01"
    body += _ipp_attr(0x47, "attributes-charset", "utf-8") + _ipp_attr(0x48, "attributes-natural-language", "en")
    body += _ipp_attr(0x45, "printer-uri", f"ipp://{host}:{port}{path}")
    for k, a in enumerate(requested):
        body += _ipp_attr(0x44, "requested-attributes" if k == 0 else "", a)
    body += b"\x03"
    req = urllib.request.Request(f"http://{host}:{port}{path}", data=body, method="POST",
                                 headers={"Content-Type": "application/ipp", "User-Agent": f"PrintDock/{APP_VERSION}"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return ipp_parse(r.read(4 * 1024 * 1024))


def device_attrs(host, requested):
    """Attribute direkt beim Geraet: unter Linux ueber pycups, sonst (Windows) ueber den eigenen IPP-Client."""
    if cups is not None and not WINDOWS:
        return cups.Connection(host=host, port=631).getPrinterAttributes(
            uri=f"ipp://{host}:631/ipp/print", requested_attributes=requested)
    return ipp_get_attributes(host, requested)


# --- mDNS (Windows; unter Linux erledigt das Avahi) ---
def mdns_browse(service, wait=3.0):
    """[{name, ip, port, txt}] fuer einen Dienst wie „_ipp._tcp.local.“ – braucht das Python-Paket zeroconf."""
    try:
        from zeroconf import Zeroconf, ServiceBrowser
    except ImportError:
        return []
    zc = Zeroconf()
    names = set()

    class Listener:
        def add_service(self, _zc, _t, name):
            names.add(name)

        def update_service(self, _zc, _t, name):
            names.add(name)

        def remove_service(self, *_a):
            pass
    try:
        ServiceBrowser(zc, service, Listener())
        time.sleep(wait)
        out = []
        for name in sorted(names):
            info = zc.get_service_info(service, name, 2000)
            if not info:
                continue
            ipv4 = [a for a in info.parsed_addresses() if ":" not in a]
            txt = {k.decode("utf-8", "replace"): (v or b"").decode("utf-8", "replace")
                   for k, v in (info.properties or {}).items()}
            if ipv4:
                out.append({"name": name.split("._")[0], "ip": ipv4[0], "port": info.port, "txt": txt})
        return out
    finally:
        zc.close()


WIN_VIRTUAL = re.compile(r"pdf|xps|onenote|\bfax\b|send to|snagit|anydesk", re.I)
WIN_GENERIC_DRIVER = re.compile(r"ipp class driver|mopria|universal|generic", re.I)


def discover_windows():
    """Windows-Drucker (Warteschlangen) und Netzwerkdrucker im eigenen Netz (mDNS) zusammenfuehren."""
    printers = []
    try:
        ports = {d.get("Name"): d for d in ps_json("Get-PrinterPort | Select-Object Name,PrinterHostAddress")}
        for d in ps_json("Get-Printer | Select-Object Name,PortName,DriverName"):
            name, port, driver = d.get("Name") or "", d.get("PortName") or "", d.get("DriverName") or ""
            if not name or WIN_VIRTUAL.search(name) or WIN_VIRTUAL.search(driver):
                continue
            p = Printer()
            p.queue = p.info = name
            p.model = "" if WIN_GENERIC_DRIVER.search(driver) else driver
            m = re.search(r"(?:https?|ipps?)://\[?([^/\]:]+)", port)
            host = (ports.get(port) or {}).get("PrinterHostAddress") or (m.group(1) if m else "")
            if re.match(r"(usb|dot4)", port, re.I):
                p.uris = ["usb://" + name]
            elif host:
                p.host = host
                p.uris = [f"ipp://{host}:631/ipp/print"]
            else:
                p.uris = ["win://" + port]   # z. B. WSD-Anschluss: ohne Adresse kein Status
            printers.append(p)
    except Exception:
        pass
    for svc in mdns_browse("_ipp._tcp.local."):
        p = next((q for q in printers if q.host == svc["ip"]), None)
        if p is None:
            p = Printer()
            p.host = svc["ip"]
            p.info = svc["name"]
            p.uris = [f"ipp://{svc['ip']}:{svc['port'] or 631}/{svc['txt'].get('rp') or 'ipp/print'}"]
            printers.append(p)
        p.model = p.model or svc["txt"].get("ty", "")
    for p in printers:   # Modell beim Geraet erfragen, wenn Windows nur einen allgemeinen Treiber kennt
        if p.host and not p.model:
            try:
                p.model = str(ipp_get_attributes(p.host, ["printer-make-and-model"], timeout=3)
                              .get("printer-make-and-model") or "")
            except Exception:
                pass
    return printers


def win_add_printer(name, uri):
    url = re.sub(r"^ipp://", "http://", re.sub(r"^ipps://", "https://", uri))
    rc, out, err = powershell(f"Add-Printer -Name {ps_quote(name)} -IppURL {ps_quote(url)}", 180)
    if rc != 0:
        raise RuntimeError(tr("Windows konnte den Drucker nicht hinzufügen: {0}", (err or out).strip()[:200]))


def parse_page_ranges(text):
    """„1-3,5“ -> {0,1,2,4}; leer -> None (alle Seiten)."""
    pages = set()
    for part in (text or "").replace(" ", "").split(","):
        m = re.fullmatch(r"(\d+)(?:-(\d+))?", part)
        if m:
            a, b = int(m.group(1)), int(m.group(2) or m.group(1))
            pages.update(range(min(a, b) - 1, max(a, b)))
    return pages or None


def pdf_images(path, dpi=200, pages=None):
    """PDF-Seiten als QImage (Qt rendert selbst – unter Windows gibt es kein pdftoppm)."""
    from PySide6 import QtPdf
    doc = QtPdf.QPdfDocument()
    doc.load(path)
    if doc.status() != QtPdf.QPdfDocument.Status.Ready:
        raise RuntimeError(tr("PDF nicht lesbar: {0} ({1})", os.path.basename(path), doc.error()))
    out = []
    for i in range(doc.pageCount()):
        if pages is not None and i not in pages:
            continue
        pt = doc.pagePointSize(i)
        out.append(doc.render(i, QtCore.QSize(int(pt.width() / 72 * dpi), int(pt.height() / 72 * dpi))))
    doc.close()
    return out


def win_print_files(queue, files, opts):
    """Drucken ueber die Windows-Warteschlange: PDF-Seiten und Bilder malt Qt auf den Drucker."""
    from PySide6 import QtPrintSupport
    pr = QtPrintSupport.QPrinter(QtPrintSupport.QPrinterInfo.printerInfo(queue),
                                 QtPrintSupport.QPrinter.PrinterMode.HighResolution)
    pr.setDocName(os.path.basename(files[0]))
    pr.setCopyCount(max(1, int(opts.get("copies", 1) or 1)))
    sides = opts.get("sides", "")
    pr.setDuplex(QtPrintSupport.QPrinter.DuplexMode.DuplexLongSide if "long" in sides else
                 QtPrintSupport.QPrinter.DuplexMode.DuplexShortSide if "short" in sides else
                 QtPrintSupport.QPrinter.DuplexMode.DuplexNone)
    pr.setColorMode(QtPrintSupport.QPrinter.ColorMode.GrayScale if opts.get("print-color-mode") == "monochrome"
                    else QtPrintSupport.QPrinter.ColorMode.Color)
    m = re.search(r"_([\d.]+)x([\d.]+)(mm|in)$", opts.get("media", ""))
    if m:
        f = 25.4 if m.group(3) == "in" else 1
        pr.setPageSize(QtGui.QPageSize(QtCore.QSizeF(float(m.group(1)) * f, float(m.group(2)) * f),
                                       QtGui.QPageSize.Unit.Millimeter))
    pages = parse_page_ranges(opts.get("page-ranges"))
    fit = opts.get("fit-to-page") == "true"
    texts = [f for f in files if f.lower().endswith(".txt")]
    painter = QtGui.QPainter()
    first = True
    dpi = min(300, pr.resolution())
    for f in files:
        if f in texts:
            continue
        imgs = pdf_images(f, dpi, pages) if f.lower().endswith(".pdf") else [QtGui.QImage(f)]
        for img in imgs:
            if img.isNull():
                continue
            if first:
                if not painter.begin(pr):
                    raise RuntimeError(tr("Drucker „{0}“ lässt sich nicht öffnen.", queue))
                first = False
            else:
                pr.newPage()
            area = painter.viewport()
            size = img.size()
            if fit or size.width() > area.width() or size.height() > area.height() or f.lower().endswith(".pdf"):
                size.scale(area.size(), QtCore.Qt.AspectRatioMode.KeepAspectRatio)
            painter.drawImage(QtCore.QRect(area.x(), area.y(), size.width(), size.height()), img)
    if not first:
        painter.end()
    for f in texts:   # Textdateien druckt Qt als eigenes Dokument
        with open(f, encoding="utf-8", errors="replace") as fh:
            doc = QtGui.QTextDocument(fh.read())
        doc.print_(pr)
    return os.path.basename(files[0])


def win_jobs(queue):
    out = {}
    for j in ps_json(f"Get-PrintJob -PrinterName {ps_quote(queue)} | Select-Object Id,DocumentName,JobStatus"):
        status = str(j.get("JobStatus") or "")
        out[int(j.get("Id") or 0)] = {"job-name": j.get("DocumentName") or "",
                                      "job-state": 5 if "Printing" in status else 4 if "Paused" in status else 3}
    return out


# --- eSCL (Scannen direkt beim Geraet, ohne SANE) ---
ESCL_NS = 'xmlns:scan="http://schemas.hp.com/imaging/escl/2011/05/03" xmlns:pwg="http://www.pwg.org/schemas/2010/12/sm"'


def escl_open(url, data=None, method="GET", timeout=30):
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "text/xml"} if data is not None else {})
    return urllib.request.urlopen(req, timeout=timeout, context=_ssl_ctx() if url.startswith("https") else None)


def escl_base(ip, rs="eSCL"):
    """Erreichbare eSCL-Adresse eines Geraets (https zuerst) oder None."""
    for scheme in ("https", "http"):
        base = f"{scheme}://{ip}/{rs.strip('/')}"
        try:
            with escl_open(base + "/ScannerCapabilities", timeout=5) as r:
                if b"ScannerCapabilities" in r.read(200000):
                    return base
        except Exception:
            continue
    return None


def list_scanners_windows():
    found, seen = [], set()
    hosts = [(s["ip"], s["txt"].get("rs") or "eSCL", s["txt"].get("ty") or s["name"])
             for s in mdns_browse("_uscan._tcp.local.") + mdns_browse("_uscans._tcp.local.")]
    hosts += [(s["ip"], "eSCL", s["txt"].get("ty") or s["name"]) for s in mdns_browse("_ipp._tcp.local.")]
    for ip, rs, name in hosts:
        if ip in seen:
            continue
        seen.add(ip)
        base = escl_base(ip, rs)
        if base:
            found.append(("escl:" + base, f"{name} (ip={ip})"))
    return found


def escl_options(base):
    with escl_open(base + "/ScannerCapabilities", timeout=10) as r:
        xml = r.read().decode("utf-8", "replace")
    modes = {"RGB24": "Color", "Grayscale8": "Gray", "BlackAndWhite1": "Lineart"}
    mode_list = [modes[m] for m in modes if f">{m}<" in xml]
    res = sorted({int(x) for x in re.findall(r"<scan:XResolution>(\d+)", xml)})
    srcs = (["Flatbed"] if "<scan:Platen>" in xml else []) + (["ADF"] if "<scan:Adf>" in xml else []) + \
        (["ADF Duplex"] if "AdfDuplexInputCaps" in xml else [])
    return {"mode": (mode_list or ["Color"], "Color"),
            "resolution": ([str(x) for x in res] or ["300"], "300" if 300 in res else str(res[0]) if res else "300"),
            "source": (srcs or ["Flatbed"], (srcs or ["Flatbed"])[0])}


def escl_scan(base, mode, res, source, area=None, crop=False):
    feeder = bool(source) and bool(re.search(r"adf|feeder", source, re.I))
    duplex = feeder and "duplex" in source.lower()
    if area:
        w, h = round(area[0] / 25.4 * 300), round(area[1] / 25.4 * 300)
    else:
        w, h = 2480, 3508   # A4; der Scanner beschneidet selbst auf seine groesste Flaeche
        try:
            with escl_open(base + "/ScannerCapabilities", timeout=10) as r:
                xml = r.read().decode("utf-8", "replace")
            blk = re.search(r"<scan:Platen>(.*?)</scan:Platen>", xml, re.S) if not feeder else None
            if blk:
                mw, mh = re.search(r"<scan:MaxWidth>(\d+)", blk.group(1)), re.search(r"<scan:MaxHeight>(\d+)", blk.group(1))
                if mw and mh:
                    w, h = int(mw.group(1)), int(mh.group(1))
        except Exception:
            pass
    color = {"Color": "RGB24", "Gray": "Grayscale8", "Lineart": "BlackAndWhite1"}.get(mode or "Color", "RGB24")
    dpi = int(res or 300)
    xml = (f'<?xml version="1.0" encoding="UTF-8"?><scan:ScanSettings {ESCL_NS}><pwg:Version>2.0</pwg:Version>'
           f'<pwg:ScanRegions><pwg:ScanRegion><pwg:ContentRegionUnits>escl:ThreeHundredthsOfInches</pwg:ContentRegionUnits>'
           f'<pwg:XOffset>0</pwg:XOffset><pwg:YOffset>0</pwg:YOffset><pwg:Width>{w}</pwg:Width><pwg:Height>{h}</pwg:Height>'
           f'</pwg:ScanRegion></pwg:ScanRegions><pwg:InputSource>{"Feeder" if feeder else "Platen"}</pwg:InputSource>'
           f'<scan:ColorMode>{color}</scan:ColorMode><scan:XResolution>{dpi}</scan:XResolution>'
           f'<scan:YResolution>{dpi}</scan:YResolution><pwg:DocumentFormat>image/jpeg</pwg:DocumentFormat>'
           f'<scan:DocumentFormatExt>image/jpeg</scan:DocumentFormatExt>'
           f'{"<scan:Duplex>true</scan:Duplex>" if duplex else ""}</scan:ScanSettings>')
    with escl_open(base + "/ScanJobs", data=xml.encode("utf-8"), method="POST", timeout=30) as r:
        loc = r.headers.get("Location") or ""
    if not loc:
        raise RuntimeError(tr("Scan fehlgeschlagen"))
    job = urllib.parse.urljoin(base + "/", loc).rstrip("/")
    tmp = tempfile.mkdtemp(prefix="dz-scan-")
    files, busy = [], 0
    while True:
        try:
            with escl_open(job + "/NextDocument", timeout=180) as r:
                data = r.read()
        except urllib.error.HTTPError as e:
            if e.code == 503 and busy < 60:   # Geraet ist noch beschaeftigt
                busy += 1
                time.sleep(1)
                continue
            if e.code == 404 and files:   # keine weiteren Seiten
                break
            raise RuntimeError(tr("Scan fehlgeschlagen: {0}", f"HTTP {e.code}"))
        f = os.path.join(tmp, f"seite{len(files) + 1:03d}.jpg")
        with open(f, "wb") as fh:
            fh.write(data)
        files.append(f)
        if not feeder:
            break
    if crop and Image is not None:
        for f in files:
            autocrop(f)
    return files


_TRAY = None


def tray_notify(title, text):
    """Windows: Mitteilung ueber das Infobereich-Symbol (notify-send gibt es dort nicht)."""
    global _TRAY
    app = QtWidgets.QApplication.instance()
    if app is None:
        return
    if _TRAY is None:
        _TRAY = QtWidgets.QSystemTrayIcon(dot_icon(ACCENT), app)
        _TRAY.setToolTip(APP_NAME)
        _TRAY.show()
    _TRAY.showMessage(title, text, QtWidgets.QSystemTrayIcon.MessageIcon.Information, 8000)


def restart_self():
    """PrintDock neu starten (Sprache gewechselt, Update installiert)."""
    if WINDOWS:
        args = [sys.executable] + ([] if FROZEN else [os.path.abspath(sys.argv[0])]) + sys.argv[1:]
        subprocess.Popen(args, creationflags=0x00000008 | 0x00000200)   # DETACHED_PROCESS | NEW_PROCESS_GROUP
        QtWidgets.QApplication.quit()
        return
    os.execv(sys.executable, [sys.executable, os.path.realpath(__file__)] + sys.argv[1:])


def uri_ids(uri):
    serial = re.search(r"serial=([^&]+)", uri)
    uuid = re.search(r"uuid=([^&]+)", uri)
    host = re.search(r"(?:ip=|://)([^/:?&]+)", uri)
    return (serial.group(1) if serial else ""), (uuid.group(1) if uuid else ""), (host.group(1) if host else "")


def mdns_ipv4():
    """Dienstname -> IPv4 fuer alle IPP-Drucker im Netz (Avahi)."""
    rc, out, _ = run(["avahi-browse", "-rpt", "_ipp._tcp"], 12)
    ips = {}
    for line in out.splitlines():
        f = line.split(";")
        if len(f) > 8 and f[0] == "=" and f[2] == "IPv4":
            name = re.sub(r"\\(\d{3})", lambda m: chr(int(m.group(1))), f[3])
            ips[name] = f[7]
    return ips


def service_name(uri):
    m = re.match(r"(?:dnssd|ipps?)://([^/]+?)\._ipps?\._tcp", uri)
    return urllib.parse.unquote(m.group(1)) if m else None


def discover():
    """Alle Drucker: eingerichtete Warteschlangen und von CUPS gefundene Geraete (USB, Netzwerk)."""
    if WINDOWS:
        return discover_windows()
    if cups is None:
        raise RuntimeError(tr("python-pycups fehlt"))
    conn = cups.Connection()
    printers = []

    def find(uri, model):
        serial, uuid, host = uri_ids(uri)
        name = service_name(uri)
        for p in printers:
            if uuid and any(uuid in u for u in p.uris):
                return p
            if name and any(service_name(u) == name for u in p.uris):
                return p
            if serial and serial == p.serial:
                return p
            if host and host == p.host and host not in ("localhost", "127.0.0.1") and not uri.startswith("usb"):
                return p
            if uri in p.uris:
                return p
            # gleiches Modell im Netz (dnssd und hp:/net beschreiben dasselbe Geraet)
            if model and norm(model) == norm(p.model) and "usb" not in uri and "usb" not in p.uri:
                return p
        return None

    def add(uri, model, info, queue=None):
        if uri.startswith(("hp:", "hpfax:", "hpaio:")):
            return   # Adressen der HP-Software, ohne sie nicht nutzbar
        p = find(uri, model)
        if p is None:
            p = Printer()
            printers.append(p)
        if uri not in p.uris:
            p.uris.append(uri)
        serial, uuid, host = uri_ids(uri)
        p.serial = p.serial or serial
        if host and not uri.startswith("usb") and host not in ("localhost", "127.0.0.1"):
            p.host = p.host or host
        p.model = p.model or model
        p.info = p.info or info
        if queue and not p.queue:
            p.queue = queue

    queues = conn.getPrinters()
    for name, q in queues.items():
        uri, model = q.get("device-uri", ""), q.get("printer-make-and-model", "")
        if uri.startswith(("file:", "cups-pdf:")):
            continue   # PDF-Drucker und Dateiausgabe sind keine Geraete
        add(uri, model, q.get("printer-info", ""), queue=name)
    try:
        found = conn.getDevices(timeout=8)
    except cups.IPPError:
        found = {}
    for uri, d in found.items():
        model = d.get("device-make-and-model", "")
        if model.strip().lower() == "unknown":
            model = ""
        if ":/" not in uri:
            continue   # nur Backend-Platzhalter wie "hp", "hpfax" oder "socket", kein Geraet
        if uri.startswith(("file:", "cups-pdf:")):
            continue
        add(uri, model, d.get("device-info", ""))
    # Netzwerkdrucker: IP ueber mDNS
    if any("usb" not in p.uri for p in printers):
        ips = mdns_ipv4()
        for p in printers:
            if p.connection == "USB":
                continue
            ip = next((ips[n] for n in (service_name(u) for u in p.uris) if n in ips), None) \
                or next((m.group(1) for m in (re.search(r"ip=([\d.]+)", u) for u in p.uris) if m), None)
            if ip:
                p.host = ip
            elif p.host and not re.fullmatch(r"[\w.-]+", p.host):
                p.host = ""   # kein brauchbarer Hostname (z.B. mDNS-Dienstname)
    return printers


STATUS_ATTRS = ["printer-state", "printer-state-reasons", "printer-state-message", "marker-names", "marker-levels",
                "marker-colors", "marker-types", "sides-supported", "print-color-mode-supported", "media-supported",
                "print-quality-supported", "printer-make-and-model"]


def query_status(p):
    """Status und Tinte ueber IPP: beim Geraet selbst, sonst ueber die CUPS-Warteschlange."""
    res = {"state": "", "reasons": [], "message": "", "markers": [], "supported": {}}
    attrs = queue_attrs = None
    # Netzwerkdrucker (IP oder Name wie HP….local); ein ausgeschalteter laesst sich nicht verbinden
    net = bool(p.host) and p.host not in ("localhost", "127.0.0.1") and p.connection != "USB"
    if cups is not None and p.queue:
        try:
            queue_attrs = cups.Connection().getPrinterAttributes(p.queue, requested_attributes=STATUS_ATTRS)
        except (cups.IPPError, RuntimeError):
            queue_attrs = None
    if net:
        # Zustand beim Geraet selbst erfragen: CUPS meldet „Bereit“, auch wenn der Drucker aus ist
        import socket
        try:
            socket.create_connection((p.host, 631), timeout=2).close()
            attrs = device_attrs(p.host, STATUS_ATTRS)
        except Exception:   # Verbindung abgelehnt, Zeitueberschreitung oder IPP-Fehler
            res.update(state=tr("Nicht erreichbar"), reasons=["offline"])
            if queue_attrs:
                for key in ("sides-supported", "print-color-mode-supported", "media-supported", "print-quality-supported"):
                    res["supported"][key] = _list(queue_attrs.get(key))
            return res
    else:
        attrs = queue_attrs
    if attrs:
        state = {3: tr("Bereit"), 4: tr("Druckt"), 5: tr("Angehalten")}.get(attrs.get("printer-state"), "")
        res["state"] = state
        res["message"] = attrs.get("printer-state-message", "")
        res["reasons"] = [r for r in _list(attrs.get("printer-state-reasons")) if r != "none"]
        names, levels = _list(attrs.get("marker-names")), _list(attrs.get("marker-levels"))
        colors = _list(attrs.get("marker-colors"))
        for i, name in enumerate(names):
            res["markers"].append({"name": name, "level": levels[i] if i < len(levels) else -1,
                                   "color": colors[i] if i < len(colors) else ""})
        # Druckoptionen aus der Warteschlange (dort stehen die, mit denen CUPS druckt)
        for key in ("sides-supported", "print-color-mode-supported", "media-supported", "print-quality-supported"):
            res["supported"][key] = _list((queue_attrs or attrs).get(key))
    # CUPS kennt die Tinte einer Warteschlange oft erst nach dem ersten Auftrag: dann den Drucker direkt fragen
    if not res["markers"] and (cups is not None or WINDOWS) and re.fullmatch(r"[\d.]+", p.host or ""):
        try:
            direct = device_attrs(p.host, ["marker-names", "marker-levels", "marker-colors", "printer-state-reasons"])
            res["reasons"] += [r for r in _list(direct.get("printer-state-reasons"))
                               if r != "none" and r not in res["reasons"]]
            names, levels = _list(direct.get("marker-names")), _list(direct.get("marker-levels"))
            colors = _list(direct.get("marker-colors"))
            for i, name in enumerate(names):
                res["markers"].append({"name": name, "level": levels[i] if i < len(levels) else -1,
                                       "color": colors[i] if i < len(colors) else ""})
        except Exception:
            pass
    return res


def _list(v):
    if v is None:
        return []
    return list(v) if isinstance(v, (list, tuple)) else [v]


REASONS_DE = {
    "media-empty": tr("Papier leer"), "media-jam": tr("Papierstau"), "media-needed": tr("Papier einlegen"),
    "door-open": tr("Klappe offen"), "cover-open": tr("Deckel offen"), "marker-supply-low": tr("Tinte fast leer"),
    "marker-supply-empty": tr("Tinte leer"), "toner-low": tr("Toner fast leer"), "toner-empty": tr("Toner leer"),
    "offline": tr("Drucker ist ausgeschaltet oder nicht im Netz"), "paused": tr("Angehalten"), "connecting-to-device": tr("Verbindet…"),
    "input-tray-missing": tr("Papierfach fehlt"), "output-area-full": tr("Ausgabefach voll"),
    # weitere Standardmeldungen (IPP/PWG), die Drucker melden koennen
    "media-low": tr("Papier fast leer"), "interlock-open": tr("Klappe offen"), "output-tray-missing": tr("Ausgabefach fehlt"),
    "output-area-almost-full": tr("Ausgabefach fast voll"), "marker-waste-almost-full": tr("Resttintenbehälter fast voll"),
    "marker-waste-full": tr("Resttintenbehälter voll"), "opc-near-eol": tr("Bildtrommel bald verbraucht"),
    "opc-life-over": tr("Bildtrommel verbraucht"), "developer-low": tr("Entwickler fast leer"),
    "developer-empty": tr("Entwickler leer"), "fuser-over-temp": tr("Fixiereinheit zu heiß"),
    "fuser-under-temp": tr("Fixiereinheit heizt auf"), "spool-area-full": tr("Druckspeicher voll"),
    "shutdown": tr("Drucker fährt herunter"), "timed-out": tr("Drucker antwortet nicht"),
    "stopped-partly": tr("Teilweise angehalten"), "stopping": tr("Hält an"), "moving-to-paused": tr("Wird angehalten"),
    "media-path-cannot-duplex-media-selected": tr("Dieses Papier kann nicht beidseitig bedruckt werden"),
    "toner-almost-empty": tr("Toner fast leer"), "ink-low": tr("Tinte fast leer"), "ink-empty": tr("Tinte leer"),
}
# Diese Meldungen sind so wichtig, dass PrintDock beim ersten Auftreten zusaetzlich eine Desktop-Mitteilung zeigt
REASONS_URGENT = {"media-jam", "media-empty", "media-needed", "door-open", "cover-open", "interlock-open",
                  "input-tray-missing", "output-area-full", "marker-supply-empty", "toner-empty", "ink-empty",
                  "marker-waste-full", "opc-life-over"}


def reason_base(r):
    return re.sub(r"-(report|warning|error)$", "", r)


def notify(title, text):
    """Desktop-Mitteilung (KDE, GNOME …); fehlt notify-send, bleibt es bei der Anzeige im Fenster."""
    if WINDOWS:
        try:
            tray_notify(title, text)
        except Exception:
            pass
        return
    if shutil.which("notify-send"):
        try:
            subprocess.Popen(["notify-send", "-a", APP_NAME, "-i", "printer", title, text],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            pass


def reason_text(r):
    base = reason_base(r)
    return REASONS_DE.get(base, base)


INK_DE = {"black": tr("Schwarz"), "cyan": tr("Cyan"), "magenta": tr("Magenta"), "yellow": tr("Gelb"), "photo black": tr("Fotoschwarz"),
          "tri-color": tr("Dreifarbig"), "color": tr("Farbe"), "gray": tr("Grau"), "light cyan": tr("Hellcyan"), "light magenta": tr("Hellmagenta")}


def ink_name(name):
    base = re.sub(r"\s*(ink|toner|cartridge|patrone)s?\s*$", "", (name or "").strip(), flags=re.I).lower()
    return INK_DE.get(base, name or "Tinte")


def marker_color(m):
    c = m.get("color") or ""
    hexes = re.findall(r"#[0-9A-Fa-f]{6}", c)
    if hexes:
        return hexes
    n = (m.get("name") or "").lower()
    for keys, col in ((("black", "schwarz", "photo black"), ["#222222"]), (("cyan",), ["#00AEEF"]),
                      (("magenta",), ["#EC008C"]), (("yellow", "gelb"), ["#FFD400"]),
                      (("tri", "color", "farb"), ["#00AEEF", "#EC008C", "#FFD400"])):
        if any(k in n for k in keys):
            return col
    return ["#888888"]


# ---------- Druckervorlagen ----------
# Je Modell eine kleine Vorlage im GitHub-Projekt (vorlagen/<modell>.json). PrintDock laedt nur die Vorlage des
# Druckers, der gerade eingebunden wird, und merkt sie sich; gibt es keine, gilt STANDARD_TEMPLATE.
# Treiberpakete installiert PrintDock erst, wenn ein Drucker sie wirklich braucht (aeltere Geraete ohne IPP).
TEMPLATE_URL = "https://raw.githubusercontent.com/{repo}/main/vorlagen/{slug}.json"
TEMPLATE_DIR = os.path.join(INSTALL_DIR, "vorlagen")
STANDARD_TEMPLATE = {
    "name": tr("Standard"),
    # nur fuer Drucker ohne treiberloses Drucken; freie Treiber fuer sehr viele aeltere Geraete
    "treiber": {"arch": ["gutenprint", "foomatic-db-engine", "foomatic-db", "foomatic-db-ppds"],
                "deb": ["printer-driver-gutenprint", "foomatic-db-compressed-ppds"],
                "rpm": ["gutenprint-cups", "foomatic-db", "foomatic-db-ppds"],
                "suse": ["gutenprint", "OpenPrintingPPDs"]},
    "treiber_suche": None,   # Suchbegriff fuer den Treiber; None = Modellname
    "papier": "iso_a4_210x297mm",
    "beidseitig": True,
    "fax": None,             # True/False legt fest, None = beim Drucker nachsehen
    "wartung": None,         # Liste erlaubter Wartungsauftraege, None = alles, was der Drucker anbietet
    "hinweise": [],
    "bild": None,            # Adresse eines Geraetebilds (https), wird nur geladen, nie mit der App verteilt
    "farbe": None,           # False = druckt nur schwarzweiss, None = beim Drucker nachsehen
    "scanner": None,         # "keiner", "glas", "einzug", "einzug-beidseitig"; None = beim Scanner nachsehen
}


def template_slug(p):
    return re.sub(r"[^a-z0-9]+", "-", real_name(p).lower()).strip("-") or "drucker"


def read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def own_template_path(p):
    """Selbst beschriebener Drucker (Uebergang, bis es eine offizielle Vorlage gibt) – nur auf diesem PC."""
    return os.path.join(TEMPLATE_DIR, template_slug(p) + ".eigen.json")


def get_template(p):
    """Offizielle Vorlage (gemerkt, ohne Netz); sonst die selbst beschriebene; sonst Standard."""
    data = read_json(os.path.join(TEMPLATE_DIR, template_slug(p) + ".json"))
    own = not data and os.path.exists(own_template_path(p))
    if own:
        data = read_json(own_template_path(p))
    # Hinweise gibt es je Sprache (hinweise_en, hinweise_fr …); die deutschen stehen unter „hinweise“
    tmpl = dict(STANDARD_TEMPLATE, **{k: v for k, v in data.items() if k in STANDARD_TEMPLATE or k.startswith("hinweise_")})
    tmpl["eigene"] = own
    return tmpl


def template_hints(tmpl):
    """Hinweise der Vorlage in der gewaehlten Sprache, sonst Englisch, sonst deutsch."""
    if LANG != "de":
        for key in (f"hinweise_{LANG}", "hinweise_en"):
            if tmpl.get(key):
                return tmpl[key]
    return tmpl.get("hinweise") or []


def fetch_template(p):
    """Passende Vorlage herunterladen und merken (auch „keine vorhanden“); einmal am Tag neu nachsehen,
    damit Ergaenzungen an der Vorlage auch bei schon eingebundenen Druckern ankommen."""
    path = os.path.join(TEMPLATE_DIR, template_slug(p) + ".json")
    had_official = bool(read_json(path))
    try:
        fresh = time.time() - os.path.getmtime(path) < 86400
    except OSError:
        fresh = False
    if not fresh:
        url = TEMPLATE_URL.format(repo=UPDATE_REPO, slug=template_slug(p))
        try:
            with urllib.request.urlopen(url, timeout=10) as r:
                data = json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            data = {} if e.code == 404 else None   # 404: fuer dieses Modell gibt es keine Vorlage
        except (OSError, ValueError):
            data = None                            # kein Netz: beim naechsten Mal nochmal versuchen
        if data is not None:
            os.makedirs(TEMPLATE_DIR, exist_ok=True)
            # erst in eine eigene Datei, dann austauschen: Uebersicht und Einrichten holen die Vorlage
            # gleichzeitig, und eine halb geschriebene Datei gaelte sonst kurz als „keine Vorlage“
            tmp = f"{path}.{threading.get_ident()}.tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=1)
            os.replace(tmp, path)
            if data and not had_official and os.path.exists(path):
                # Es gibt jetzt eine offizielle Vorlage: sie loest die selbst beschriebene ab
                p.newly_supported = True
                try:
                    os.remove(own_template_path(p))
                except OSError:
                    pass
    return get_template(p)


def is_atomic():
    return os.path.exists("/run/ostree-booted") and bool(shutil.which("rpm-ostree"))


def package_tool():
    """(Kennung, Installationsbefehl, Pruefbefehl) der Paketverwaltung dieses Systems."""
    if is_atomic():
        # Bazzite, Silverblue, Kinoite …: /usr ist schreibgeschuetzt, dnf geht dort nicht.
        # rpm-ostree legt die Pakete obendrauf; wirksam erst nach einem Neustart.
        return "rpm", ["rpm-ostree", "install", "-y", "--idempotent", "--allow-inactive"], ["rpm", "-q"]
    for exe, key, install, have in (
            ("pacman", "arch", ["pacman", "-S", "--needed", "--noconfirm"], ["pacman", "-Q"]),
            ("apt-get", "deb", ["env", "DEBIAN_FRONTEND=noninteractive", "apt-get", "install", "-y"], ["dpkg", "-s"]),
            ("dnf", "rpm", ["dnf", "install", "-y"], ["rpm", "-q"]),
            ("zypper", "suse", ["zypper", "--non-interactive", "install"], ["rpm", "-q"])):
        if shutil.which(exe):
            return key, install, have
    return None, None, None


def ensure_packages(by_distro):
    """Fehlende Pakete aus {"arch": [...], "deb": [...], ...} mit einer Passwortabfrage nachinstallieren."""
    if WINDOWS:
        return   # Windows bringt fuer Netzwerkdrucker den IPP-Treiber selbst mit
    key, install, have = package_tool()
    if not key:
        return
    missing = [x for x in (by_distro or {}).get(key, []) if run(have + [x], 30)[0] != 0]
    if missing:
        rc, out, err = run(["pkexec"] + install + missing, 1800)
        if rc != 0:
            raise RuntimeError(tr("Treiber nicht installiert: ") + " ".join(missing))
        if key == "rpm" and is_atomic():
            raise RuntimeError(tr("Treiber installiert ({0}). Auf diesem System werden sie erst nach einem Neustart "
                                  "aktiv – danach den Drucker bitte noch einmal einrichten.", " ".join(missing)))


# ---------- Einrichten ----------
# ---------- PrintDock-Server ----------
# Firmen und Aemter verwalten ihre Drucker zentral (github.com/LucyWolf/printdock-server). Die App meldet sich dort
# an und bekommt die zugewiesenen Drucker; gedruckt wird direkt zum Geraet. Schnittstelle: docs/api.md im Server-Projekt.
# Gemerkt werden nur Adresse, Benutzername und das Anmelde-Token – nie das Passwort.
SERVER_FILE = os.path.join(INSTALL_DIR, "server")   # Adresse, vom Installer geschrieben


class ServerAuthError(RuntimeError):
    """Anmeldung abgelaufen oder ungueltig."""


def server_settings():
    return QtCore.QSettings("printdock", "printdock")


def server_url():
    url = (server_settings().value("server/url", "") or "").strip()
    if not url:
        try:
            with open(SERVER_FILE, encoding="utf-8") as f:
                url = f.read().strip()
        except OSError:
            url = ""
    return url.rstrip("/")


def server_insecure(url):
    """http:// ausserhalb des eigenen Rechners: Passwort und Token gingen unverschluesselt durchs Netz."""
    return url.startswith("http://") and not re.match(r"http://(localhost|127\.0\.0\.1)(:|/|$)", url)


def server_request(method, path, data=None, token=None, url=None):
    url = (url or server_url()).rstrip("/")
    if not url:
        raise RuntimeError(tr("Kein Server eingetragen."))
    if not url.startswith(("https://", "http://")):
        url = "https://" + url
    req = urllib.request.Request(url + path, method=method,
                                 data=json.dumps(data).encode("utf-8") if data is not None else None,
                                 headers={"Content-Type": "application/json", "Accept": "application/json",
                                          "User-Agent": f"PrintDock/{APP_VERSION}"})
    token = token if token is not None else server_settings().value("server/token", "")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            body = r.read(2 * 1024 * 1024)
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise ServerAuthError(tr("Anmeldung abgelaufen oder falsch – bitte neu anmelden."))
        if e.code == 403:
            raise RuntimeError(tr("Keine Berechtigung."))
        raise RuntimeError(tr("Server meldet einen Fehler (HTTP {0}).", e.code))
    except (urllib.error.URLError, OSError) as e:
        raise RuntimeError(tr("Server nicht erreichbar: {0}", getattr(e, "reason", e)))
    try:
        return json.loads(body.decode("utf-8")) if body else {}
    except ValueError:
        raise RuntimeError(tr("Unerwartete Antwort vom Server."))


def server_login(url, user, password):
    """Anmelden; gibt (token, name, rolle) zurueck. Das Passwort wird nirgends gespeichert."""
    url = url.strip().rstrip("/")
    if url and not url.startswith(("https://", "http://")):
        url = "https://" + url
    res = server_request("POST", "/api/v1/login", {"username": user, "password": password}, token="", url=url)
    token = res.get("token") if isinstance(res, dict) else None
    if not token:
        raise RuntimeError(tr("Unerwartete Antwort vom Server."))
    u = res.get("user") or {}
    return url, token, u.get("name") or user, u.get("role") or "user"


def server_printers():
    """Zugewiesene Drucker vom Server als Printer-Objekte (noch ohne lokale Warteschlange)."""
    res = server_request("GET", "/api/v1/printers")
    out = []
    for d in res if isinstance(res, list) else []:
        if not isinstance(d, dict) or not d.get("id") or not (d.get("uri") or d.get("host")):
            continue
        p = Printer()
        p.server_id = str(d["id"])
        p.model = str(d.get("model") or "")
        p.info = str(d.get("name") or "")
        p.location = str(d.get("location") or "")
        p.host = str(d.get("host") or "")
        uri = str(d.get("uri") or "")
        if not uri.startswith(("ipp://", "ipps://")):
            uri = f"ipp://{p.host}:631/ipp/print"   # nur treiberlose Netzwerkdrucker kommen vom Server
        p.uris = [uri]
        out.append(p)
    return out


def merge_server_printers(found, assigned):
    """Server-Drucker in die Suchergebnisse einordnen: schon bekannte (gleiche Adresse) markieren, fehlende anhaengen."""
    def hosts(p):
        hs = {p.host} if p.host else set()
        for u in p.uris:
            m = re.match(r"\w+://([^/:]+)", u)
            if m:
                hs.add(m.group(1))
        return hs
    for sp in assigned:
        match = next((p for p in found if hosts(p) & hosts(sp)), None)
        if match:
            match.server_id, match.location = sp.server_id, sp.location
            match.info = match.info or sp.info
            match.model = match.model or sp.model
        else:
            found.append(sp)
    return found


def setup_printers_batch(printers):
    """Mehrere Netzwerkdrucker mit einer einzigen Passwortabfrage einrichten (treiberlos)."""
    cmds, names = [], []
    for p in printers:
        uri = p.best_setup_uri()
        if not uri or not uri.startswith(("ipp://", "ipps://")):
            continue
        name = re.sub(r"[^A-Za-z0-9_-]+", "_", p.info or p.model or "Drucker").strip("_")[:60] or "Drucker"
        while name in names:
            name += "_2"
        names.append(name)
        cmds.append("lpadmin -p " + shlex.quote(name) + " -E -v " + shlex.quote(uri) + " -m everywhere")
    if not cmds:
        return 0
    if WINDOWS:
        for p, name in zip([p for p in printers if (p.best_setup_uri() or "").startswith(("ipp://", "ipps://"))], names):
            win_add_printer(name, p.best_setup_uri())
        return len(names)
    rc, out, err = run(["pkexec", "/bin/sh", "-c", " && ".join(cmds)], 300)
    if rc != 0:
        raise RuntimeError((err or out or "lpadmin").strip())
    return len(cmds)


# ---------- Drucker melden ----------
# Fuer Drucker ohne Vorlage: wer es ist (Hersteller, Modell, Produktnummer), nicht was er kann – das laesst sich mit
# dem Modell nachschlagen. Gemeldet wird als GitHub-Issue; Seriennummer, Adresse und Namen bleiben immer draussen.
REPORT_LABEL = "neuer-drucker"


def strip_serial(device_id):
    """IEEE-1284-Kennung ohne Seriennummer (SN:, SERN:, SERIALNUMBER:)."""
    return ";".join(x for x in (device_id or "").split(";")
                    if x.strip() and not re.match(r"\s*(SN|SERN|SERIALNUMBER)\s*:", x, re.I))


def printer_report(p):
    """Steckbrief eines Druckers als Markdown (title, body). Fragt das Geraet selbst; laeuft im Hintergrund."""
    info = {"model": re.sub(r"\s+-\s+.*$", "", p.model or ""), "device_id": "", "firmware": "", "product": ""}
    if p.host:
        try:
            a = device_attrs(p.host, ["printer-make-and-model", "printer-device-id", "printer-firmware-string-version"])
            info["model"] = str(a.get("printer-make-and-model") or info["model"])
            info["device_id"] = strip_serial(str(a.get("printer-device-id") or ""))
            fw = a.get("printer-firmware-string-version")
            info["firmware"] = ", ".join(map(str, fw)) if isinstance(fw, list) else str(fw or "")
        except Exception:
            pass
        for scheme in ("https", "http"):   # HP: Produktnummer (z. B. A7F65A) aus der eingebauten Schnittstelle
            try:
                with urllib.request.urlopen(f"{scheme}://{p.host}/DevMgmt/ProductConfigDyn.xml", timeout=5,
                                            context=_ssl_ctx() if scheme == "https" else None) as r:
                    xml = r.read(300000).decode("utf-8", "replace")
                m = re.search(r"<[\w:]*ProductNumber>([^<]+)<", xml)
                if m:
                    info["product"] = m.group(1).strip()
                    break
            except Exception:
                continue
    if not info["device_id"]:   # USB unter Linux: Hersteller und Modell stehen in der Adresse
        usb = next((u for u in p.uris if u.startswith("usb://")), "")
        m = re.match(r"usb://([^/?]+)/([^?]+)", usb)
        if m:
            info["device_id"] = f"MFG:{urllib.parse.unquote(m.group(1))};MDL:{urllib.parse.unquote(m.group(2))}"
    name = info["model"] or real_name(p)
    lines = [
        "### Drucker / Printer",
        f"- Modell (vom Gerät gemeldet) / model: `{name}`",
        f"- Gerätekennung / IEEE 1284 ID: `{info['device_id'] or '–'}`",
        f"- Produktnummer / product number: `{info['product'] or '–'}`",
        f"- Firmware: `{info['firmware'] or '–'}`",
        f"- Verbindung / connection: {p.connection}",
        f"- Vorlage gesucht unter / template file: `vorlagen/{template_slug(p)}.json`",
        "",
        "### Umgebung / environment",
        f"- PrintDock {APP_VERSION}, {'Windows' if WINDOWS else 'Linux'}, Sprache {LANG}",
    ]
    return f"Neuer Drucker: {name}", "\n".join(lines)


def report_url(title, body, comment=""):
    if comment.strip():
        body += "\n\n### Anmerkung / note\n" + comment.strip()
    q = urllib.parse.urlencode({"title": title, "body": body, "labels": REPORT_LABEL})
    return f"https://github.com/{UPDATE_REPO}/issues/new?{q}"


def setup_printer(p):
    uri = p.best_setup_uri()
    name = re.sub(r"[^A-Za-z0-9_-]+", "_", p.model or p.info or "Drucker").strip("_")[:60] or tr("Drucker")
    if WINDOWS:
        if not p.host:
            raise RuntimeError(tr("USB-Drucker richtet Windows selbst ein – einfach anstecken."))
        win_add_printer(name, f"ipp://{p.host}:631/ipp/print")
        return tr("Eingerichtet als „{0}“.", name)
    cmd = ["pkexec", "lpadmin", "-p", name, "-E", "-v", uri, "-m", "everywhere"]
    if not uri.startswith(("ipp://", "ipps://", "dnssd://")):
        # Ohne IPP (aeltere USB- oder Netzwerkdrucker): erst jetzt die Treiber laut Vorlage installieren,
        # dann den passenden aus den installierten suchen. CUPS markiert den empfohlenen.
        tmpl = fetch_template(p)
        ensure_packages(tmpl.get("treiber"))
        rc, out, _ = run(["lpinfo", "--make-and-model", tmpl.get("treiber_suche") or p.model or p.info, "-m"], 30)
        lines = [l for l in out.splitlines() if l.strip()]
        best = next((l for l in lines if "recommended" in l.lower()), None) or \
            next((l for l in lines if "gutenprint" in l.lower()), None) or (lines[0] if lines else None)
        if not best:
            raise RuntimeError(tr("Kein passender Treiber installiert. Neuere Drucker gehen treiberlos über "
                               "Netzwerk oder „ipp-usb“; für ältere hilft der Treiber des Herstellers."))
        cmd[-1] = best.split()[0]
    rc, out, err = run(cmd, 120)
    if rc != 0:
        raise RuntimeError((err or out or tr("lpadmin fehlgeschlagen")).strip())
    return tr("Eingerichtet als „{0}“.", name)


# ---------- Fax: MH-Kodierung (ITU-T T.4, eindimensional) ----------
# Aufbau wie ihn HP-Drucker beim PC-Fax erwarten: je Zeile ein EOL (000000000001), danach die Laufcodes
# (beginnend mit Weiss), Zeile auf ganze Bytes mit Nullen aufgefuellt; am Seitenende 6 EOLs. MSB zuerst.
_MH_WHITE_TERM = ("00110101 000111 0111 1000 1011 1100 1110 1111 10011 10100 00111 01000 001000 000011 110100 "
                  "110101 101010 101011 0100111 0001100 0001000 0010111 0000011 0000100 0101000 0101011 0010011 "
                  "0100100 0011000 00000010 00000011 00011010 00011011 00010010 00010011 00010100 00010101 "
                  "00010110 00010111 00101000 00101001 00101010 00101011 00101100 00101101 00000100 00000101 "
                  "00001010 00001011 01010010 01010011 01010100 01010101 00100100 00100101 01011000 01011001 "
                  "01011010 01011011 01001010 01001011 00110010 00110011 00110100").split()
_MH_BLACK_TERM = ("0000110111 010 11 10 011 0011 0010 00011 000101 000100 0000100 0000101 0000111 00000100 "
                  "00000111 000011000 0000010111 0000011000 0000001000 00001100111 00001101000 00001101100 "
                  "00000110111 00000101000 00000010111 00000011000 000011001010 000011001011 000011001100 "
                  "000011001101 000001101000 000001101001 000001101010 000001101011 000011010010 000011010011 "
                  "000011010100 000011010101 000011010110 000011010111 000001101100 000001101101 000011011010 "
                  "000011011011 000001010100 000001010101 000001010110 000001010111 000001100100 000001100101 "
                  "000001010010 000001010011 000000100100 000000110111 000000111000 000000100111 000000101000 "
                  "000001011000 000001011001 000000101011 000000101100 000001011010 000001100110 "
                  "000001100111").split()
_MH_WHITE_MAKEUP = ("11011 10010 010111 0110111 00110110 00110111 01100100 01100101 01101000 01100111 011001100 "
                    "011001101 011010010 011010011 011010100 011010101 011010110 011010111 011011000 011011001 "
                    "011011010 011011011 010011000 010011001 010011010 011000 010011011").split()
_MH_BLACK_MAKEUP = ("0000001111 000011001000 000011001001 000001011011 000000110011 000000110100 000000110101 "
                    "0000001101100 0000001101101 0000001001010 0000001001011 0000001001100 0000001001101 "
                    "0000001110010 0000001110011 0000001110100 0000001110101 0000001110110 0000001110111 "
                    "0000001010010 0000001010011 0000001010100 0000001010101 0000001011010 0000001011011 "
                    "0000001100100 0000001100101").split()
_MH_EOL = "000000000001"
FAX_WIDTH = 1728          # Bildpunkte je Faxzeile (Standard)
FAX_HEIGHT = 2200         # Zeilen je Seite, wie der Drucker sie im Seitenauftrag erwartet


def _mh_run(length, black):
    term, makeup = (_MH_BLACK_TERM, _MH_BLACK_MAKEUP) if black else (_MH_WHITE_TERM, _MH_WHITE_MAKEUP)
    out = []
    if length >= 64:
        out.append(makeup[length // 64 - 1])
        length %= 64
    out.append(term[length])
    return "".join(out)


_BYTE_BITS = [format(i, "08b") for i in range(256)]


def mh_encode(img):
    """Bild (Modus „1“, Breite FAX_WIDTH) -> MH-Bytes einer Seite."""
    import re as _re
    w, h = img.size
    raw = img.tobytes()   # Modus „1“: 1 = weiss, 0 = schwarz, MSB zuerst, Zeilen auf Bytes aufgefuellt
    stride = (w + 7) // 8
    out = bytearray()
    for y in range(h):
        row = "".join(_BYTE_BITS[b] for b in raw[y * stride:(y + 1) * stride])[:w]
        bits = [_MH_EOL]
        black = False
        if row.startswith("0"):
            bits.append(_mh_run(0, False))   # jede Zeile beginnt mit einem (hier leeren) Weisslauf
            black = True
        for m in _re.finditer(r"1+|0+", row):
            bits.append(_mh_run(len(m.group()), m.group()[0] == "0"))
            black = not black
        s = "".join(bits)
        s += "0" * (-len(s) % 8)
        out += int(s, 2).to_bytes(len(s) // 8, "big")
    s = _MH_EOL * 6
    s += "0" * (-len(s) % 8)
    out += int(s, 2).to_bytes(len(s) // 8, "big")
    return bytes(out)


# ---------- Fax ueber die Geraeteschnittstelle des Druckers (HP „FaxPCSend“, reines HTTP, Port 8080) ----------
# Ablauf wie bei HPs eigener Software: Auftrag anlegen -> je Seite Einstellungen schicken -> warten, bis der
# Drucker verbunden ist -> Seitenbild (MH) schicken. Ohne Herstellersoftware, die Daten erzeugt die App selbst.
FAX_NS = 'xmlns="http://www.hp.com/schemas/imaging/con/ledm/printtofaxdyn/2008/11/24" ' \
         'xmlns:dd="http://www.hp.com/schemas/imaging/con/dictionaries/1.0/"'
FAX_JOB_XML = ('<?xml version="1.0" encoding="UTF-8"?><FaxPCSendDyn ' + FAX_NS + '><FaxPCSendConfig>'
               '<FaxTxPhoneNumber>%s</FaxTxPhoneNumber><NumPages>%d</NumPages><TTI_Control>TTI_Off</TTI_Control>'
               '</FaxPCSendConfig></FaxPCSendDyn>')
FAX_PAGE_XML = ('<?xml version="1.0" encoding="UTF-8" ?><FaxPCSendDyn ' + FAX_NS + '><PageConfig>'
                '<PageNum>%d</PageNum><Width>1728</Width><Height>2200</Height><ImageType>BW</ImageType>'
                '<Compression>mh</Compression><HorizontalDPI>200</HorizontalDPI><VerticalDPI>200</VerticalDPI>'
                '</PageConfig></FaxPCSendDyn>')
FAX_CANCEL_XML = ('<?xml version="1.0" encoding="UTF-8"?><Job xmlns="http://www.hp.com/schemas/imaging/con/ledm/'
                  'jobs/2009/04/30"><JobUrl>%s</JobUrl><JobState>Canceled</JobState></Job>')
FAX_STATES = {"Dialing": tr("wählt"), "Connecting": tr("verbindet"), "Transmitting": tr("sendet"), "Idle": tr("bereit")}


def fax_http(ip, method, path, body=b"", ctype="text/xml; charset=utf-8", timeout=30):
    import http.client
    c = http.client.HTTPConnection(ip, 8080, timeout=timeout)
    try:
        c.request(method, path, body=body, headers={"Content-Type": ctype} if body else {})
        r = c.getresponse()
        return r.status, dict(r.getheaders()), r.read()
    finally:
        c.close()


def fax_capable(ip):
    """Bietet der Drucker PC-Fax an? (steht in seinem Verzeichnis der Geraeteschnittstelle)"""
    try:
        st, _, body = fax_http(ip, "GET", "/DevMgmt/DiscoveryTree.xml", timeout=6)
        return st == 200 and b"FaxPCSendManifest" in body
    except Exception:
        return False


def _xml_field(xml, name):
    m = re.search(rb"<(?:\w+:)?" + name.encode() + rb">([^<]*)<", xml)
    return m.group(1).decode().strip() if m else ""


def fax_pages(files):
    """Dokumente (PDF, Bilder) -> Faxseiten: schwarzweiss, 1728 Punkte breit, 200 dpi, hoechstens 2200 Zeilen."""
    pages = []
    for f in files:
        if f.lower().endswith(".pdf") and (WINDOWS or not shutil.which("pdftoppm")):
            srcs = []
            for q in pdf_images(f, 200):   # Qt rendert das PDF selbst
                buf = QtCore.QBuffer()
                buf.open(QtCore.QIODevice.OpenModeFlag.WriteOnly)
                q.save(buf, "PNG")
                import io
                srcs.append(Image.open(io.BytesIO(bytes(buf.data()))))
        elif f.lower().endswith(".pdf"):
            tmp = tempfile.mkdtemp(prefix="dz-faxpdf-")
            rc, out, err = run(["pdftoppm", "-r", "200", "-gray", "-png", f, os.path.join(tmp, "s")], 300)
            if rc != 0:
                raise RuntimeError(tr("PDF nicht lesbar: {0} ({1})", os.path.basename(f), (err or out).strip()[:120]))
            srcs = [Image.open(os.path.join(tmp, x)) for x in sorted(os.listdir(tmp))]
        else:
            srcs = [Image.open(f)]
        for im in srcs:
            im = im.convert("L")
            scale = min(FAX_WIDTH / im.width, FAX_HEIGHT / im.height)
            im = im.resize((max(1, int(im.width * scale)), max(1, int(im.height * scale))), Image.LANCZOS)
            page = Image.new("L", (FAX_WIDTH, FAX_HEIGHT), 255)
            page.paste(im, ((FAX_WIDTH - im.width) // 2, 0))
            pages.append(page.point(lambda v: 255 if v >= 128 else 0).convert("1", dither=Image.Dither.NONE))
    if not pages:
        raise RuntimeError(tr("Keine Seiten zum Faxen."))
    return pages


def fax_send(ip, number, files, progress, cancel):
    """Sendet ein Fax. progress(text) meldet den Stand, cancel ist ein threading.Event."""
    progress(tr("Seiten werden vorbereitet …"))
    pages = [mh_encode(pg) for pg in fax_pages(files)]
    st, hdr, body = fax_http(ip, "POST", "/FaxPCSend/Job", (FAX_JOB_XML % (number, len(pages))).encode())
    if st != 201:
        raise RuntimeError(tr("Drucker nimmt keinen Faxauftrag an (HTTP {0}).", st))
    m = re.search(rb"/Jobs/JobList/\d+", " ".join(hdr.values()).encode() + b" " + body)
    if not m:
        raise RuntimeError(tr("Drucker hat keine Auftragsnummer geliefert."))
    job = m.group().decode()

    def status():
        return fax_http(ip, "GET", job, timeout=10)[2]
    try:
        for n, data in enumerate(pages, 1):
            if cancel.is_set():
                raise InterruptedError
            res = _xml_field(status(), "ResourceURI")
            st, _, _ = fax_http(ip, "POST", res, (FAX_PAGE_XML % n).encode())
            if st != 202:
                raise RuntimeError(tr("Seite {0}: Einstellungen abgelehnt (HTTP {1}).", n, st))
            deadline = time.time() + 180
            while True:   # erst wenn der Drucker sendet, nimmt er das Seitenbild
                if cancel.is_set():
                    raise InterruptedError
                x = status()
                mach, err = _xml_field(x, "FaxTxMachineStatus"), _xml_field(x, "FaxTxErrorStatus")
                if err in ("NoAnswer", "CommunicationError", "PcDisconnect", "Stop", "Busy", "NoDialTone"):
                    raise RuntimeError({"NoAnswer": tr("Gegenstelle antwortet nicht."), "Busy": tr("Besetzt."),
                                        "NoDialTone": tr("Kein Wählton – Telefonleitung am Drucker angeschlossen?")}
                                       .get(err, tr("Fax abgebrochen ({0}).", err)))
                if mach == "Transmitting":
                    break
                progress(tr("Drucker {0} …", FAX_STATES.get(mach, mach.lower() or 'bereitet vor')))
                if time.time() > deadline:
                    raise RuntimeError(tr("Drucker meldet keine Verbindung (Zeitüberschreitung)."))
                time.sleep(1)
            progress(tr("Sende Seite {0} von {1} …", n, len(pages)))
            res = _xml_field(status(), "ResourceURI")
            st, _, _ = fax_http(ip, "POST", res, data, "application/octet-stream", timeout=120)
            if st != 202:
                raise RuntimeError(tr("Seite {0} abgelehnt (HTTP {1}).", n, st))
        deadline = time.time() + 600
        while time.time() < deadline:   # warten, bis der Drucker fertig gesendet hat
            x = status()
            state, err = _xml_field(x, "JobState"), _xml_field(x, "FaxTxErrorStatus")
            if state in ("Completed",):
                return tr("Fax an {0} gesendet ({1} Seite(n)).", number, len(pages))
            if state in ("Canceled", "Aborted") or err not in ("", "None", "NoError"):
                raise RuntimeError(tr("Fax nicht vollständig gesendet ({0}).", err or state))
            progress(tr("Drucker sendet … ({0})", FAX_STATES.get(_xml_field(x, 'FaxTxMachineStatus'), 'läuft')))
            time.sleep(2)
        return tr("Fax an {0} übergeben – der Drucker sendet noch (siehe Faxprotokoll am Drucker).", number)
    except InterruptedError:
        fax_http(ip, "PUT", job, (FAX_CANCEL_XML % job).encode())
        raise RuntimeError(tr("Fax abgebrochen."))


# ---------- Wartung ----------
def _ssl_ctx():
    import ssl
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE   # Drucker haben selbst ausgestellte Zertifikate
    return ctx


def ledm_jobs(ip):
    """HP-Geraeteschnittstelle (LEDM): welche Wartungs- und Berichtsseiten der Drucker selbst drucken kann."""
    for url in (f"https://{ip}/DevMgmt/InternalPrintCap.xml", f"http://{ip}/DevMgmt/InternalPrintCap.xml"):
        try:
            with urllib.request.urlopen(url, timeout=6, context=_ssl_ctx() if url.startswith("https") else None) as r:
                return re.findall(r"<ipdyn:JobType>([A-Za-z0-9]+)</ipdyn:JobType>", r.read().decode("utf-8", "replace"))
        except Exception:
            continue
    return []


# Aufbau der Anfrage an die Geraeteschnittstelle (LEDM) der HP-Drucker
LEDM_JOB_XML = ('<?xml version="1.0" encoding="UTF-8"?>\n'
                '<ipcap:InternalPrintCap xmlns:ipcap="http://www.hp.com/schemas/imaging/con/ledm/internalprintcap/2008/03/21" '
                'xmlns:ipdyn="http://www.hp.com/schemas/imaging/con/ledm/internalprintdyn/2008/03/21" '
                'xmlns:dd="http://www.hp.com/schemas/imaging/con/dictionaries/1.0/" '
                'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">\n'
                '<ipdyn:JobType>%s</ipdyn:JobType>\n</ipcap:InternalPrintCap>')


def ledm_run(ip, job):
    last = None
    for url in (f"https://{ip}/DevMgmt/InternalPrintDyn.xml", f"http://{ip}/DevMgmt/InternalPrintDyn.xml"):
        req = urllib.request.Request(url, data=(LEDM_JOB_XML % job).encode(), method="POST",
                                     headers={"Content-Type": "text/xml"})
        try:
            with urllib.request.urlopen(req, timeout=15, context=_ssl_ctx() if url.startswith("https") else None):
                return
        except urllib.error.HTTPError as e:
            last = tr("Drucker lehnt ab (HTTP {0})", e.code)
            break
        except Exception as e:
            last = str(e)
    raise RuntimeError(last or tr("Drucker nicht erreichbar"))


LEDM_LABELS = {
    "cleaningPage": ("quality", tr("Druckkopf reinigen – Stufe 1"), tr("Bei Streifen oder blassen Farben. Druckt eine Seite.")),
    "cleaningPageLevel1": ("quality", tr("Druckkopf reinigen – Stufe 2"), tr("Gründlicher, braucht mehr Tinte.")),
    "cleaningPageLevel2": ("quality", tr("Druckkopf reinigen – Stufe 2"), tr("Gründlicher, braucht mehr Tinte.")),
    "cleaningPageLevel3": ("quality", tr("Druckkopf reinigen – Stufe 3"), tr("Nur wenn Stufe 2 nicht reicht – viel Tinte.")),
    "cleaningVerificationPage": ("quality", tr("Reinigungs-Prüfseite"), tr("Zeigt, ob alle Düsen wieder drucken.")),
    "pqDiagnosticsPage": ("quality", tr("Druckqualitäts-Diagnose"), tr("Testseite zum Beurteilen von Farben und Streifen.")),
    "lineFeedCalibrationPage": ("quality", tr("Zeilenvorschub kalibrieren"), tr("Gegen helle oder dunkle Querstreifen.")),
    "configurationPage": ("report", tr("Druckerstatusbericht"), tr("Modell, Firmware, Füllstände, Einstellungen.")),
    "usagePage": ("report", tr("Nutzungsseite"), tr("Gedruckte Seiten und Verbrauch.")),
    "diagnosticsPage": ("report", tr("Diagnoseseite"), tr("Technische Angaben für die Fehlersuche.")),
    "networkDiagnosticPage": ("report", tr("Netzwerk-Testbericht"), tr("Prüft LAN/WLAN-Verbindung.")),
    "networkSummary": ("report", tr("Netzwerkkonfiguration"), tr("IP-Adresse und Netzwerkeinstellungen.")),
    "wirelessNetworkPage": ("report", tr("WLAN-Testbericht"), tr("Signal und WLAN-Einstellungen.")),
}

CLEAN_LEVELS = ["cleaningPage", "cleaningPageLevel1", "cleaningPageLevel2", "cleaningPageLevel3"]

CUPS_COMMANDS = {"Clean": (tr("Druckkopf reinigen"), tr("Reinigung über den Druckertreiber.")),
                 "PrintSelfTestPage": (tr("Selbsttestseite"), tr("Der Drucker druckt seine eigene Testseite.")),
                 "AutoConfigure": (tr("Optionen neu erkennen"), tr("Fragt installierte Fächer usw. beim Drucker ab."))}


def cups_commands(queue):
    try:
        a = cups.Connection().getPrinterAttributes(queue, requested_attributes=["printer-commands"])
    except Exception:
        return []
    cmds = []
    for c in _list(a.get("printer-commands")):
        cmds += [x.strip() for x in str(c).split(",") if x.strip() and x.strip() != "none"]
    return cmds


def cups_command(queue, cmd):
    """Wartungsbefehl ueber CUPS (Datei mit #CUPS-COMMAND erkennt CUPS selbst)."""
    path = os.path.join(tempfile.mkdtemp(prefix="dz-cmd-"), "befehl")
    with open(path, "w") as f:
        f.write(f"#CUPS-COMMAND\n{cmd}{' all' if cmd == 'Clean' else ''}\n")
    return cups.Connection().printFile(queue, path, cmd, {})


def remove_queue(name):
    if WINDOWS:
        rc, out, err = powershell(f"Remove-Printer -Name {ps_quote(name)}", 60)
        if rc != 0:
            raise RuntimeError((err or out).strip()[:200])
        return
    rc, out, err = run(["pkexec", "lpadmin", "-x", name], 60)
    if rc != 0:
        raise RuntimeError((err or out or tr("lpadmin fehlgeschlagen")).strip())


# ---------- Scannen ----------
def list_scanners():
    if WINDOWS:
        return list_scanners_windows()
    rc, out, err = run(["scanimage", "-L"], 60)
    if rc == -1:
        raise RuntimeError(err)
    found = []
    for m in re.finditer(r"device `([^']+)' is a (.+)", out):
        dev, desc = m.group(1), m.group(2).strip()
        if dev.startswith(("v4l:", "gphoto2:")):
            continue   # Webcams und Kameras sind keine Scanner
        found.append((dev, desc))
    # airscan (eSCL) zuerst: funktioniert bei Netzwerk und IPP-over-USB treiberlos. Dasselbe Geraet ueber
    # Treiber-Weg nur behalten, wenn es keinen airscan-Weg dafuer gibt.
    found.sort(key=lambda d: (not d[0].startswith("airscan"), d[1]))
    seen, unique = set(), []
    for dev, desc in found:
        words = re.findall(r"\d{3,}", desc + " " + dev)   # Modellnummer, z.B. 8620
        key = words[0] if words else dev
        if key in seen:
            continue
        seen.add(key)
        unique.append((dev, desc))
    return unique


COMMON_DPI = [75, 100, 150, 200, 300, 600, 1200]


def scanner_options(dev):
    if dev.startswith("escl:"):
        return escl_options(dev[5:])
    rc, out, err = run(["scanimage", "-d", dev, "-A"], 60)
    opts = {}
    for line in out.splitlines():
        m = re.match(r"\s+--(mode|resolution|source)\s+(.+?)\s*\[(.*?)\]\s*$", line)
        if not m:
            continue
        name, vals, cur = m.groups()
        vals = re.sub(r"dpi.*$", "", vals).strip()
        if ".." in vals:
            lo, hi = (int(float(x)) for x in re.findall(r"[\d.]+", vals)[:2])
            choices = [str(d) for d in COMMON_DPI if lo <= d <= hi]
        else:
            choices = [v.strip() for v in vals.split("|") if v.strip()]
        opts[name] = (choices, re.sub(r"dpi$", "", cur))
    return opts


MEDIA_NAMES = {"letter": "Letter", "legal": "Legal", "executive": "Executive", "govt-letter": "Government Letter",
               "invoice": "Statement", "hagaki": "Postkarte (Hagaki)", "oufuku": "Antwortpostkarte", "index-4x6": "Foto 10×15",
               "index-5x8": "Karteikarte 13×20", "index-3x5": "Karteikarte 8×13", "5x7": "Foto 13×18",
               "photo-l": "Foto 9×13", "small-photo": "Foto 10×15", "hp-greeting-card": "Grußkarte",
               "monarch": "Umschlag Monarch", "number-10": "Umschlag US Nr. 10", "dl": "Umschlag DL", "c5": "Umschlag C5",
               "c6": "Umschlag C6", "a2": "Umschlag A2", "chou3": "Umschlag Chou 3", "chou4": "Umschlag Chou 4",
               "foolscap": "Foolscap", "oficio": "Oficio", "16k": "16K"}


def pretty_media(name):
    """PWG-Name (z. B. na_executive_7.25x10.5in) -> „Executive (184 × 267 mm)“; Sortierschluessel dazu."""
    mb = re.match(r"(?:[a-z]+_)?(.+?)\.borderless(?:_.*)?$", name, re.I)
    if mb:
        base = mb.group(1)
        known = {"A4": ("A4", 210, 297), "A5": ("A5", 148, 210), "A6": ("A6", 105, 148), "B5": ("B5", 182, 257),
                 "Letter": ("Letter", 216, 279), "4x6": ("Foto 10×15", 102, 152), "100x150mm": ("Foto 10×15", 100, 150),
                 "5x7": ("Foto 13×18", 127, 178), "3.5x5": ("Foto 9×13", 89, 127), "8x10": ("Foto 20×25", 203, 254),
                 "Postcard": ("Postkarte", 100, 148)}
        base = next((k for k in known if k.lower() == base.lower()), base)
        if base in known:
            nice = known[base][0]
            return tr("{0} randlos", tr(nice)), (5, nice)
        return tr("{0} randlos", base), (6, base)
    m = re.match(r"([a-z]+)_(.+)_([\d.]+)x([\d.]+)(mm|in)$", name)
    if not m:
        return name, (9, name)
    region, label = m.group(1), m.group(2)
    nice = MEDIA_NAMES.get(label) or (label.upper() if region == "iso" or re.fullmatch(r"[ab]\d+", label) else
                                      label.replace("-", " ").title())
    if region == "jis":
        nice += " (JIS)"
    group = 0 if name == "iso_a4_210x297mm" else 1 if region == "iso" and not nice.startswith("Umschlag") else \
        2 if nice.startswith("Foto") else 4 if nice.startswith("Umschlag") else 3
    return tr(nice), (group, nice)   # Gruppen nach dem deutschen Namen, angezeigt uebersetzt


SCAN_AREAS = [(tr("Gesamter Scanbereich"), None), ("A4", (210, 297)), ("A5", (148, 210)), ("Letter", (215.9, 279.4)), ("Legal", (215.9, 355.6)),
              (tr("Foto 10×15"), (101.6, 152.4)), (tr("Foto 13×18"), (127, 178))]


def autocrop(path):
    """Kanten erkennen: weissen/hellen Rand um das Dokument abschneiden."""
    im = Image.open(path)
    gray = im.convert("L")
    mask = gray.point(lambda v: 255 if v < 235 else 0)
    box = mask.getbbox()
    if not box:
        return
    pad = 8
    box = (max(0, box[0] - pad), max(0, box[1] - pad), min(im.width, box[2] + pad), min(im.height, box[3] + pad))
    if (box[2] - box[0]) * (box[3] - box[1]) < 0.97 * im.width * im.height:
        im.crop(box).save(path)


def scan(dev, mode, res, source, area=None, crop=False):
    if dev.startswith("escl:"):
        return escl_scan(dev[5:], mode, res, source, area, crop)
    tmp = tempfile.mkdtemp(prefix="dz-scan-")
    args = ["scanimage", "-d", dev, "--format=png"]
    if area:
        args += ["-l", "0", "-t", "0", "-x", str(area[0]), "-y", str(area[1])]
    if mode:
        args += ["--mode", mode]
    if res:
        args += ["--resolution", res]
    if source:
        args += ["--source", source]
    feeder = bool(source) and re.search(r"adf|feeder|einzug|duplex", source, re.I)
    if feeder:
        args.append(f"--batch={tmp}/seite%03d.png")
    else:
        args += ["-o", f"{tmp}/seite001.png"]
    rc, out, err = run(args, 600, cwd=tmp)
    files = sorted(os.path.join(tmp, f) for f in os.listdir(tmp) if f.endswith(".png"))
    if not files:
        raise RuntimeError((err or out or tr("Scan fehlgeschlagen")).strip().splitlines()[-1])
    if crop and Image is not None:
        for f in files:
            autocrop(f)
    return files


# Zustaende des Vorlageneinzugs laut eSCL (ScannerStatus/AdfState); fehlt ein Eintrag, ist es kein Problem
ADF_PROBLEMS = {
    "ScannerAdfJam": tr("Papierstau im Vorlageneinzug – Klappe oben öffnen und das Blatt in Laufrichtung herausziehen."),
    "ScannerAdfHatchOpen": tr("Die Klappe des Vorlageneinzugs ist offen."),
    "ScannerAdfMispick": tr("Der Einzug hat kein Blatt gegriffen – Stapel neu einlegen."),
    "ScannerAdfMultipickDetected": tr("Mehrere Blätter auf einmal eingezogen – Stapel auffächern und neu einlegen."),
    "ScannerAdfDuplexPageTooShort": tr("Blatt zu kurz zum Wenden – „Beidseitig von Hand“ benutzen."),
    "ScannerAdfDuplexPageTooLong": tr("Blatt zu lang zum Wenden – „Beidseitig von Hand“ benutzen."),
    "ScannerAdfInputTrayFailed": tr("Der Vorlageneinzug meldet einen Defekt."),
    "ScannerAdfInputTrayOverloaded": tr("Zu viele Blätter im Vorlageneinzug."),
}


def adf_state(ip):
    """eSCL-Zustand des Vorlageneinzugs (z. B. „ScannerAdfLoaded“, „ScannerAdfJam“), None wenn unbekannt."""
    import ssl
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    for url in (f"https://{ip}/eSCL/ScannerStatus", f"http://{ip}/eSCL/ScannerStatus"):
        try:
            with urllib.request.urlopen(url, timeout=4, context=ctx if url.startswith("https") else None) as r:
                m = re.search(rb"<scan:AdfState>(\w+)</scan:AdfState>", r.read())
            return m.group(1).decode() if m else None
        except Exception:
            continue
    return None


def adf_loaded(ip):
    """Liegt Papier im Vorlageneinzug? True/False, None wenn unbekannt oder gestoert."""
    st = adf_state(ip)
    if st is None or st in ADF_PROBLEMS:
        return None
    return st == "ScannerAdfLoaded"


def escl_caps(ip):
    """Je Quelle (platen, adf, adf-duplex): groesste Flaeche in mm und Aufloesungen, laut Scanner selbst."""
    for url in (f"https://{ip}/eSCL/ScannerCapabilities", f"http://{ip}/eSCL/ScannerCapabilities"):
        try:
            with urllib.request.urlopen(url, timeout=6, context=_ssl_ctx() if url.startswith("https") else None) as r:
                xml = r.read().decode("utf-8", "replace")
            break
        except Exception:
            xml = ""
    caps = {}

    def parse(block):
        mw = re.search(r"<scan:MaxWidth>(\d+)", block)
        mh = re.search(r"<scan:MaxHeight>(\d+)", block)
        res = sorted({int(x) for x in re.findall(r"<scan:XResolution>(\d+)", block)})
        if mw and mh:
            return {"w": int(mw.group(1)) / 300 * 25.4, "h": int(mh.group(1)) / 300 * 25.4, "res": res}
        return None
    for key, tag in (("platen", "Platen"), ("adf", "AdfSimplexInputCaps"), ("adf-duplex", "AdfDuplexInputCaps")):
        m = re.search(rf"<scan:{tag}>(.*?)</scan:{tag}>", xml, re.S)
        if m and parse(m.group(1)):
            caps[key] = parse(m.group(1))
    return caps


def scanner_ip(dev, desc):
    m = re.search(r"ip=([\d.]+)", desc or "") or re.search(r"ip=([\d.]+)", dev or "")
    return m.group(1) if m else None


SAVE_FORMATS = [("PDF", "pdf"), ("JPG", "jpg"), ("PNG", "png"), ("BMP", "bmp"), ("TIFF", "tiff"), ("WEBP", "webp")]


def save_pages(files, path, fmt, dpi):
    imgs = [Image.open(f) for f in files]
    if fmt in ("pdf", "tiff"):
        conv = [im.convert("RGB") for im in imgs]
        kw = {"save_all": True, "append_images": conv[1:]}
        if fmt == "pdf":
            kw["resolution"] = float(dpi or 300)
        else:
            kw["dpi"] = (int(dpi or 300),) * 2
        conv[0].save(path, "PDF" if fmt == "pdf" else "TIFF", **kw)
        return [path]
    out = []
    base, _ = os.path.splitext(path)
    for i, im in enumerate(imgs, 1):
        target = path if len(imgs) == 1 else f"{base}_{i}.{fmt}"
        im = im.convert("RGB") if fmt in ("jpg", "bmp") else im
        im.save(target, {"jpg": "JPEG"}.get(fmt, fmt.upper()), **({"quality": 92} if fmt in ("jpg", "webp") else {}))
        out.append(target)
    return out


# ---------- Updater: neuestes Release auf GitHub, ersetzt die installierte Programmdatei ----------
def ver_tuple(v):
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3])


def latest_release():
    req = urllib.request.Request(f"https://github.com/{UPDATE_REPO}/releases/latest", method="HEAD")
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.geturl().rstrip("/").rsplit("/", 1)[-1]


def install_update(tag):
    if WINDOWS and FROZEN:
        # Windows-Fassung: das neue Setup holen und starten; es schliesst PrintDock und startet es danach neu
        url = f"https://github.com/{UPDATE_REPO}/releases/download/{tag}/PrintDock-setup.exe"
        target = os.path.join(tempfile.mkdtemp(prefix="printdock-update-"), "PrintDock-setup.exe")
        with urllib.request.urlopen(url, timeout=120) as r, open(target, "wb") as fh:
            shutil.copyfileobj(r, fh)
        subprocess.Popen([target, "/SILENT", "/SP-", "/SUPPRESSMSGBOXES", "/NORESTART"], creationflags=0x00000008)
        return "setup"
    me = os.path.realpath(__file__)
    url = f"https://github.com/{UPDATE_REPO}/releases/download/{tag}/printdock.py"
    with urllib.request.urlopen(url, timeout=60) as r:
        data = r.read()
    compile(data, "printdock.py", "exec")   # kaputter Download ersetzt nie die laufende Fassung
    tmp = me + ".neu"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, me)


# ---------- Oberflaeche ----------
class InkBar(QtWidgets.QWidget):
    def __init__(self, marker):
        super().__init__()
        self.m = marker
        self.setMinimumHeight(34)

    def paintEvent(self, e):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        r = QtCore.QRectF(self.rect().adjusted(150, 11, -60, -11))
        p.setPen(self.palette().color(QtGui.QPalette.WindowText))
        p.drawText(QtCore.QRect(0, 0, 145, self.height()), QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft,
                   self.fontMetrics().elidedText(ink_name(self.m["name"]), QtCore.Qt.ElideRight, 145))
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(QtGui.QColor(THEME.get("track", "#888888")))
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        level = self.m["level"]
        text = f"{level} %" if level >= 0 else ("vorhanden" if level == -3 else "unbekannt")
        if level >= 0 or level == -3:
            fill = QtCore.QRectF(r)
            fill.setWidth(r.width() * (max(level, 4) if level >= 0 else 50) / 100)
            cols = marker_color(self.m)
            if len(cols) == 1:
                p.setBrush(QtGui.QColor(cols[0]))
            else:
                g = QtGui.QLinearGradient(fill.topLeft(), fill.topRight())
                for i, c in enumerate(cols):
                    g.setColorAt(i / max(1, len(cols) - 1), QtGui.QColor(c))
                p.setBrush(g)
            p.drawRoundedRect(fill, r.height() / 2, r.height() / 2)
        p.setPen(self.palette().color(QtGui.QPalette.WindowText))
        p.drawText(QtCore.QRect(self.width() - 55, 0, 55, self.height()), QtCore.Qt.AlignVCenter | QtCore.Qt.AlignRight, text)


class SetupWizard(QtWidgets.QDialog):
    """Erster Start: Drucker einschalten -> suchen (USB und Netz) -> auswaehlen -> einrichten -> Testseite.
    Oder: beim PrintDock-Server anmelden, der die freigegebenen Drucker liefert."""

    def use_server(self):
        QtCore.QSettings("printdock", "printdock").setValue("setup_done", True)
        self.accept()
        QtCore.QTimer.singleShot(0, self.parent().server_login_dialog)

    def use_manual(self):
        QtCore.QSettings("printdock", "printdock").setValue("setup_done", True)
        self.accept()
        QtCore.QTimer.singleShot(0, self.parent().add_manual_printer)

    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle(tr("{0} – Einrichtung", APP_NAME))
        self.resize(640, 460)
        self.found = []
        self.chosen = None
        lay = QtWidgets.QVBoxLayout(self)
        self.stack = QtWidgets.QStackedWidget()
        lay.addWidget(self.stack, 1)
        nav = QtWidgets.QHBoxLayout()
        self.skip = QtWidgets.QPushButton(tr("Überspringen"))
        self.skip.clicked.connect(self.reject)
        self.next = QtWidgets.QPushButton(tr("Weiter"))
        self.next.setDefault(True)
        self.next.clicked.connect(self.forward)
        nav.addWidget(self.skip)
        nav.addStretch(1)
        nav.addWidget(self.next)
        lay.addLayout(nav)

        # 1: Drucker vorbereiten
        p1 = QtWidgets.QWidget()
        l1 = QtWidgets.QVBoxLayout(p1)
        t = QtWidgets.QLabel(tr("Willkommen bei PrintDock"))
        t.setStyleSheet("font-size: 20px; font-weight: bold;")
        l1.addWidget(t)
        txt = QtWidgets.QLabel(
            tr("Zuerst richten wir deinen Drucker ein.\n\n"
            "1.  Drucker einschalten und warten, bis er bereit ist.\n"
            "2.  Verbinden – eins von beiden:\n"
            "      •  USB: Kabel an diesen PC anstecken\n"
            "      •  Netzwerk: Drucker per LAN-Kabel oder WLAN mit demselben Netz verbinden wie diesen PC\n"
            "         (WLAN am Drucker einrichten: über sein Bedienfeld oder die WPS-Taste am Router)\n\n"
            "Dann auf „Drucker suchen“ klicken."))
        txt.setWordWrap(True)
        l1.addWidget(txt)
        l1.addStretch(1)
        # Dritter Weg neben USB und Netzwerk: Drucker, die eine Firma oder ein Amt zentral verwaltet
        srv = QtWidgets.QHBoxLayout()
        srv.addWidget(QtWidgets.QLabel(tr("Drucker in einer Firma oder einem Amt?")), 1)
        srv_btn = QtWidgets.QPushButton(tr("Mit PrintDock-Server verbinden…"))
        srv_btn.clicked.connect(self.use_server)
        srv.addWidget(srv_btn)
        l1.addLayout(srv)
        # Wird der Drucker nicht gefunden oder nicht unterstuetzt: von Hand anlegen und selbst beschreiben
        man = QtWidgets.QHBoxLayout()
        man.addWidget(QtWidgets.QLabel(tr("Drucker wird nicht gefunden oder nicht unterstützt?")), 1)
        man_btn = QtWidgets.QPushButton(tr("Drucker von Hand hinzufügen…"))
        man_btn.clicked.connect(self.use_manual)
        man.addWidget(man_btn)
        l1.addLayout(man)
        self.stack.addWidget(p1)

        # 2: Suche und Auswahl
        p2 = QtWidgets.QWidget()
        l2 = QtWidgets.QVBoxLayout(p2)
        self.search_label = QtWidgets.QLabel(tr("Suche Drucker über USB und im Netzwerk …"))
        self.search_label.setWordWrap(True)
        l2.addWidget(self.search_label)
        self.busy = QtWidgets.QProgressBar()
        self.busy.setRange(0, 0)
        l2.addWidget(self.busy)
        self.flist = QtWidgets.QListWidget()
        self.flist.currentRowChanged.connect(lambda r: self.next.setEnabled(r >= 0))
        self.flist.itemDoubleClicked.connect(lambda _: self.forward())
        l2.addWidget(self.flist, 1)
        again = QtWidgets.QPushButton(QtGui.QIcon.fromTheme("view-refresh"), tr("Erneut suchen"))
        again.clicked.connect(self.search)
        l2.addWidget(again, 0, QtCore.Qt.AlignLeft)
        self.stack.addWidget(p2)

        # 3: Einrichten
        p3 = QtWidgets.QWidget()
        l3 = QtWidgets.QVBoxLayout(p3)
        self.setup_label = QtWidgets.QLabel()
        self.setup_label.setWordWrap(True)
        l3.addWidget(self.setup_label)
        self.setup_busy = QtWidgets.QProgressBar()
        self.setup_busy.setRange(0, 0)
        l3.addWidget(self.setup_busy)
        self.test_btn = QtWidgets.QPushButton(QtGui.QIcon.fromTheme("document-print"), tr("Testseite drucken"))
        self.test_btn.clicked.connect(self.test_page)
        self.test_btn.hide()
        l3.addWidget(self.test_btn, 0, QtCore.Qt.AlignLeft)
        self.name_box = QtWidgets.QWidget()
        nl = QtWidgets.QVBoxLayout(self.name_box)
        nl.setContentsMargins(0, 12, 0, 0)
        nl.addWidget(QtWidgets.QLabel(tr("Wie soll der Drucker heißen? (leer lassen = Gerätename)")))
        self.name_edit = QtWidgets.QLineEdit()
        nl.addWidget(self.name_edit)
        self.name_box.hide()
        l3.addWidget(self.name_box)
        l3.addStretch(1)
        self.stack.addWidget(p3)
        self.next.setText(tr("Drucker suchen"))

    def forward(self):
        i = self.stack.currentIndex()
        if i == 0:
            self.stack.setCurrentIndex(1)
            self.search()
        elif i == 1:
            row = self.flist.currentRow()
            if 0 <= row < len(self.found):
                self.chosen = self.found[row]
                self.stack.setCurrentIndex(2)
                self.do_setup()
        else:
            if not self.name_box.isHidden():
                # nur beim ersten Einbinden gefragt; leer = echter Geraetename
                name = self.name_edit.text().strip() or real_name(self.chosen)
                QtCore.QSettings("printdock", "printdock").setValue(f"nick/{printer_key(self.chosen)}", name)
            self.accept()

    def search(self):
        self.flist.clear()
        self.busy.show()
        self.next.setEnabled(False)
        self.search_label.setText(tr("Suche Drucker über USB und im Netzwerk … (bis zu 15 Sekunden)"))

        def done(ok, res):
            self.busy.hide()
            self.found = res if ok else []
            if not ok:
                self.search_label.setText(tr("Suche fehlgeschlagen: {0}", res))
                return
            if not res:
                self.search_label.setText(
                    tr("Kein Drucker gefunden.\n\nIst er eingeschaltet? Bei USB: Kabel ab- und wieder anstecken. "
                    "Im Netzwerk: hängt er im selben WLAN/LAN wie dieser PC? Dann „Erneut suchen“."))
                return
            self.search_label.setText(tr("Gefunden – Drucker auswählen und „Einrichten“ klicken:"))
            for p in res:
                state = tr("schon eingerichtet") if p.queue else tr("noch nicht eingerichtet")
                self.flist.addItem(QtWidgets.QListWidgetItem(QtGui.QIcon.fromTheme("printer"),
                                                             f"{p.title}\n{p.connection} · {state}"))
            self.flist.setCurrentRow(next((i for i, p in enumerate(res) if not p.queue), 0))
            self.next.setText(tr("Einrichten"))
        bg(discover, done)

    def do_setup(self):
        p = self.chosen
        self.skip.setEnabled(False)
        self.next.setEnabled(False)
        if p.queue:
            self.finish(True, tr("„{0}“ ist schon eingerichtet.", p.title))
            return
        self.setup_label.setText(tr("Richte „{0}“ ein … Gleich fragt ein Fenster nach deinem Passwort.", p.title))

        def done(ok, res):
            self.finish(ok, res if ok else tr("Einrichten fehlgeschlagen: {0}", res))
        bg(lambda: setup_printer(p), done)

    def finish(self, ok, text):
        self.setup_busy.hide()
        self.skip.setEnabled(True)
        self.next.setEnabled(True)
        self.next.setText(tr("Fertig"))
        self.setup_label.setText(text + (tr("\n\nAls Nächstes kannst du eine Testseite drucken.") if ok else
                                         tr("\n\n„Fertig“ schließt die Einrichtung; sie lässt sich oben über „Einrichtung“ "
                                         "jederzeit erneut starten.")))
        settings = QtCore.QSettings("printdock", "printdock")
        if ok and not settings.value(f"nick/{printer_key(self.chosen)}", ""):
            self.name_edit.setPlaceholderText(real_name(self.chosen))
            self.name_box.show()
            self.name_edit.setFocus()
        if ok:
            def find_queue():
                for q in discover():
                    if q.queue and (set(q.uris) & set(self.chosen.uris) or norm(q.model) == norm(self.chosen.model)):
                        return q.queue
                return None
            bg(find_queue, lambda ok2, q: (setattr(self, "queue", q), self.test_btn.setVisible(bool(ok2 and q))))

    def test_page(self):
        if WINDOWS and getattr(self, "queue", None):
            q = self.queue
            bg(lambda: run(["rundll32", "printui.dll,PrintUIEntry", "/k", "/n", q], 60),
               lambda ok, res: self.setup_label.setText(self.setup_label.text() + (
                   tr("\n\nTestseite gesendet.") if ok and res[0] == 0 else tr("\n\nTestseite fehlgeschlagen: {0}", res))))
            return
        test = next((f for f in ("/usr/share/cups/data/testprint", "/usr/share/cups/data/default-testpage.pdf")
                     if os.path.exists(f)), None)
        if test and getattr(self, "queue", None):
            q = self.queue
            bg(lambda: cups.Connection().printFile(q, test, "Testseite", {}),
               lambda ok, res: self.setup_label.setText(self.setup_label.text() + (
                   tr("\n\nTestseite gesendet.") if ok else tr("\n\nTestseite fehlgeschlagen: {0}", res))))


# ---------- Optik: schlicht, folgt dem Systemthema (hell/dunkel wie im Desktop eingestellt) ----------
ACCENT, ACCENT_H = "#12A594", "#0E8C7E"
THEME = {}


def make_qss():
    """Modernes Schema: Karten ohne Rahmen, runde Ecken, eigene Akzentfarbe; hell oder dunkel wie das System."""
    win = QtWidgets.QApplication.palette().color(QtGui.QPalette.Window)
    dark = win.lightness() < 128
    THEME.update({"bg": "#121418", "side": "#0C0E11", "card": "#1C1F25", "card_h": "#252A32", "text": "#EEF1F5",
                  "dim": "#9AA3AE", "track": "#2E333C", "line": "#2A2F37", "field": "#16191E"} if dark else
                 {"bg": "#F3F5F8", "side": "#E8ECF1", "card": "#FFFFFF", "card_h": "#F0F3F7", "text": "#1A1D22",
                  "dim": "#6B7480", "track": "#E2E6EB", "line": "#DDE2E8", "field": "#FFFFFF"})
    t = THEME
    return f"""
QMainWindow, QDialog, QStackedWidget, QScrollArea, QScrollArea > QWidget > QWidget {{ background: {t['bg']}; }}
QWidget {{ color: {t['text']}; font-size: 14px; }}
QWidget#side {{ background: {t['side']}; }}
QLabel {{ background: transparent; }}
QFrame#group, QFrame#tile {{ background: {t['card']}; border: none; border-radius: 16px; }}
QFrame#tile:hover {{ background: {t['card_h']}; }}
QFrame#hero {{ border: none; border-radius: 20px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {t['card']}, stop:1 rgba(18,165,148,0.22)); }}
QLabel#title {{ font-size: 26px; font-weight: 700; }}
QLabel#big {{ font-size: 34px; font-weight: 700; }}
QLabel#h2 {{ font-size: 16px; font-weight: 700; }}
QLabel#dim {{ color: {t['dim']}; }}
QLabel#accent {{ color: {ACCENT}; font-weight: 600; }}
QLabel#chip_ok, QLabel#chip_warn, QLabel#chip_off, QLabel#badge {{ border-radius: 12px; padding: 4px 12px; font-weight: 600; }}
QLabel#chip_ok {{ background: rgba(46,158,91,0.18); color: #2FAE66; }}
QLabel#chip_warn {{ background: rgba(217,119,6,0.18); color: #E08A0B; }}
QLabel#chip_off {{ background: {t['track']}; color: {t['dim']}; }}
QLabel#badge {{ background: rgba(18,165,148,0.14); color: {ACCENT}; font-weight: 500; }}
QListWidget#nav, QListWidget#printers {{ border: none; background: transparent; outline: none; }}
QListWidget#nav::item, QListWidget#printers::item {{ padding: 9px 10px; border-radius: 10px; margin: 1px 0; }}
QListWidget#nav::item:hover, QListWidget#printers::item:hover {{ background: {t['card_h']}; }}
QListWidget#nav::item:selected, QListWidget#printers::item:selected {{ background: {ACCENT}; color: #FFFFFF; }}
QPushButton {{ background: {t['card_h']}; border: none; border-radius: 10px; padding: 8px 14px; }}
QFrame#group QPushButton, QFrame#hero QPushButton {{ background: {t['track']}; }}
QPushButton:hover, QFrame#group QPushButton:hover {{ background: {t['line']}; }}
QPushButton:disabled {{ color: {t['dim']}; }}
QPushButton#primary, QFrame#group QPushButton#primary, QFrame#hero QPushButton#primary {{
    background: {ACCENT}; color: #FFFFFF; border-radius: 18px; padding: 8px 20px; font-weight: 700; }}
QPushButton#primary:hover, QFrame#group QPushButton#primary:hover {{ background: {ACCENT_H}; }}
QPushButton#primary:disabled {{ background: {t['track']}; color: {t['dim']}; }}
QComboBox, QLineEdit, QSpinBox, QPlainTextEdit, QListWidget {{ background: {t['field']}; border: 1px solid {t['line']};
    border-radius: 10px; padding: 6px 8px; }}
QComboBox QAbstractItemView {{ background: {t['card']}; selection-background-color: {ACCENT}; selection-color: #FFFFFF; }}
QListWidget::item:selected {{ background: {ACCENT}; color: #FFFFFF; border-radius: 6px; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-radius: 4px; }}
QProgressBar {{ background: {t['track']}; border: none; border-radius: 4px; max-height: 8px; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 4px; }}
QStatusBar {{ background: {t['bg']}; color: {t['dim']}; }}
QScrollBar:vertical {{ background: transparent; width: 10px; }}
QScrollBar::handle:vertical {{ background: {t['line']}; border-radius: 5px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QMenu {{ background: {t['card']}; border: 1px solid {t['line']}; }}
QMenu::item:selected {{ background: {ACCENT}; color: #FFFFFF; }}
"""


class ScaledImage(QtWidgets.QLabel):
    """Bild, das immer so gross wie moeglich in den Platz passt (wachst und schrumpft mit dem Fenster)."""
    def __init__(self):
        super().__init__()
        self.setAlignment(QtCore.Qt.AlignCenter)
        self.setMinimumSize(200, 200)
        self.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Ignored)
        self._pix = QtGui.QPixmap()

    def set_image(self, path_or_pix):
        self._pix = path_or_pix if isinstance(path_or_pix, QtGui.QPixmap) else QtGui.QPixmap(path_or_pix or "")
        self._rescale()

    def _rescale(self):
        if self._pix.isNull():
            self.clear()
        else:
            self.setPixmap(self._pix.scaled(self.size() * 0.97, QtCore.Qt.KeepAspectRatio,
                                            QtCore.Qt.SmoothTransformation))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._rescale()


class Clickable(QtWidgets.QFrame):
    clicked = QtCore.Signal()

    def mouseReleaseEvent(self, e):
        if e.button() == QtCore.Qt.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit()


def tile(title, desc, icon_name, cb):
    """Schnellzugriff-Kachel: Symbol, Titel, kurze Beschreibung."""
    t = Clickable()
    t.setObjectName("tile")
    t.setCursor(QtCore.Qt.PointingHandCursor)
    t.setMinimumHeight(118)
    lay = QtWidgets.QVBoxLayout(t)
    lay.setContentsMargins(20, 18, 20, 16)
    icon = QtGui.QIcon.fromTheme(icon_name)
    if not icon.isNull():
        ic = QtWidgets.QLabel()
        ic.setPixmap(icon.pixmap(32, 32))
        lay.addWidget(ic)
    lay.addStretch(1)
    h = QtWidgets.QLabel(title)
    h.setObjectName("h2")
    lay.addWidget(h)
    d = QtWidgets.QLabel(desc)
    d.setObjectName("dim")
    d.setWordWrap(True)
    lay.addWidget(d)
    t.clicked.connect(cb)
    return t


STATE_COLORS = {"ok": "#2e9e5b", "warn": "#d97706", "off": "#9a9a9a", "err": "#d14343"}


def dot_icon(color):
    pix = QtGui.QPixmap(14, 14)
    pix.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(pix)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    p.setPen(QtCore.Qt.NoPen)
    p.setBrush(QtGui.QColor(color))
    p.drawEllipse(2, 2, 10, 10)
    p.end()
    return QtGui.QIcon(pix)


def group(title=None):
    """Umrandete Gruppe mit optionaler Ueberschrift."""
    f = QtWidgets.QFrame()
    f.setObjectName("group")
    lay = QtWidgets.QVBoxLayout(f)
    lay.setContentsMargins(22, 18, 22, 20)
    lay.setSpacing(10)
    if title:
        h = QtWidgets.QLabel(title)
        h.setObjectName("h2")
        lay.addWidget(h)
    return f, lay


def printer_key(p):
    for u in p.uris:
        m = re.search(r"uuid=([^&]+)", u)
        if m:
            return m.group(1)
    return p.serial or p.host or p.uri


def real_name(p):
    """Echter Geraetename, z. B. „HP Officejet Pro 8620“ (ohne Treiberzusatz wie „- IPP Everywhere“)."""
    name = re.sub(r"\s+-\s+.*$", "", p.model or "").strip() or (p.info or p.queue or "Drucker").replace("_", " ")
    hp_hint = is_hp(" ".join(p.uris)) or is_hp(p.info) or \
        any(re.match(r"hp[_ -]|hp[0-9a-f]{12}", x or "", re.I) for x in (p.queue, p.host))   # HP_…, HP6CC2….local
    if hp_hint and not re.match(r"(hp|hewlett)", name, re.I):
        name = "HP " + name
    return name


IMAGE_DIR = os.path.join(INSTALL_DIR, "bilder")


def printer_image_target(p):
    model = re.sub(r"\s+-\s+.*$", "", p.model or p.info or "drucker")
    return os.path.join(IMAGE_DIR, re.sub(r"[^a-z0-9]+", "_", norm(model) or "drucker") + ".png")


def printer_image_path(p):
    path = printer_image_target(p)
    return path if os.path.exists(path) else None


def fetch_printer_image(p, url):
    """Geraetebild aus der Vorlage holen, wenn noch keins da ist (ein eigenes Bild hat immer Vorrang).
    Liegt danach nur auf diesem PC. True = neues Bild gespeichert."""
    if not url or not url.startswith("https://") or printer_image_path(p):
        return False
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            data = r.read(5 * 1024 * 1024 + 1)
        if len(data) > 5 * 1024 * 1024:
            return False
        import io
        img = Image.open(io.BytesIO(data))
        if img.width * img.height > 4000 * 4000:   # Dekompressions-Bombe
            return False
        img = img.convert("RGBA")
        img.thumbnail((600, 400))
        target = printer_image_target(p)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        img.save(target)
        return True
    except Exception:
        return False


def is_toner(markers):
    return any("toner" in (m.get("name") or "").lower() for m in markers)


class MainWindow(QtWidgets.QMainWindow):
    OVERVIEW, PRINT, SCAN, FAX, MAINT = range(5)
    HOME = OVERVIEW
    NAV = [(tr("Übersicht"), "go-home"), ("Drucken", "document-print"), ("Scannen", "scanner"),
           ("Fax", "mail-send"), ("Wartung", "configure")]

    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1180, 800)
        self.setStyleSheet(make_qss())
        self.printers = []
        self.current = None
        self.scanners = []
        self.pages = []          # PNG-Dateien der aktuellen Scans
        self.scan_saved = True   # False, solange gescannte Seiten nicht gespeichert sind
        self.urgent_seen = {}    # je Drucker: schon gemeldete dringende Meldungen (fuer Desktop-Mitteilungen)
        self.scan_dpi = "300"
        self.status_cache = {}   # Drucker-Schluessel -> letzter Status
        self.settings = QtCore.QSettings("printdock", "printdock")

        self.act_search = QtGui.QAction(tr("Drucker suchen"), self, triggered=self.search)
        self.act_setup = QtGui.QAction(tr("Einrichten"), self, triggered=self.setup_current)
        self.act_test = QtGui.QAction(tr("Testseite"), self, triggered=self.test_page)
        self.act_web = QtGui.QAction(tr("Weboberfläche"), self, triggered=self.open_web)
        self.act_remove = QtGui.QAction(tr("Entfernen"), self, triggered=self.remove_current)
        self.update_tag = None

        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        root = QtWidgets.QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self.build_sidebar())
        right = QtWidgets.QVBoxLayout()
        right.setContentsMargins(22, 16, 22, 8)
        self.banner = QtWidgets.QVBoxLayout()
        right.addLayout(self.banner)
        self.back_btn = QtWidgets.QPushButton(tr("←  Übersicht"))
        self.back_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self.back_btn.clicked.connect(self.back_to_overview)
        right.addWidget(self.back_btn, 0, QtCore.Qt.AlignLeft)
        self.stack = QtWidgets.QStackedWidget()
        right.addWidget(self.stack, 1)
        root.addLayout(right, 1)

        self.ov_scroll, self.ov_body = self.scroll_page()
        self.stack.addWidget(self.ov_scroll)
        self.tab_print = self.build_print_tab()
        self.tab_scan = self.build_scan_tab()
        self.stack.addWidget(self.titled(tr("Drucken"), self.tab_print))
        self.stack.addWidget(self.titled(tr("Scannen"), self.tab_scan, framed=False))
        self.tab_fax = self.build_fax_tab()
        self.stack.addWidget(self.titled(tr("Fax"), self.tab_fax))
        self.mt_scroll, self.mt_body = self.scroll_page()
        self.stack.addWidget(self.mt_scroll)

        self.status = self.statusBar()
        self.check_dependencies()
        self.build_overview()
        self.build_maintenance()
        self.go(self.OVERVIEW)
        # Erst Gemerktes zeigen (Scanner vor den Kacheln), dann im Hintergrund suchen
        self.refresh_scanners()
        self.load_cached_printers()
        QtCore.QTimer.singleShot(200, self.search)
        QtCore.QTimer.singleShot(1500, self.check_update)
        if server_url() and not self.settings.value("server/token", "") and not os.environ.get("DZ_SELFTEST") \
                and not self.settings.value("server/asked", False, type=bool):
            # Der Installer hat eine Server-Adresse eingetragen: einmal von selbst nach der Anmeldung fragen
            self.settings.setValue("server/asked", True)
            QtCore.QTimer.singleShot(400, self.server_login_dialog)
        elif not self.settings.value("setup_done", False, type=bool) and not os.environ.get("DZ_SELFTEST"):
            QtCore.QTimer.singleShot(300, self.run_wizard)
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.refresh_status)
        self.timer.start(30000)
        self.adf_timer = QtCore.QTimer(self)
        self.adf_timer.timeout.connect(self.poll_adf)
        self.adf_timer.start(3000)

    # ----- Rahmen -----
    def build_sidebar(self):
        side = QtWidgets.QWidget()
        side.setFixedWidth(250)
        side.setObjectName("side")
        side.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        lay = QtWidgets.QVBoxLayout(side)
        lay.setContentsMargins(12, 16, 12, 12)
        head = QtWidgets.QHBoxLayout()
        icon = QtWidgets.QLabel()
        icon.setPixmap(QtGui.QIcon.fromTheme("printer").pixmap(28, 28))
        head.addWidget(icon)
        t = QtWidgets.QLabel(APP_NAME)
        t.setStyleSheet("font-size: 16px; font-weight: bold;")
        head.addWidget(t, 1)
        lay.addLayout(head)
        lay.addSpacing(12)
        h = QtWidgets.QLabel(tr("Drucker"))
        h.setObjectName("dim")
        lay.addWidget(h)
        self.printer_list = QtWidgets.QListWidget()
        self.printer_list.setObjectName("printers")
        self.printer_list.setMaximumHeight(170)
        self.printer_list.currentRowChanged.connect(self.select)
        lay.addWidget(self.printer_list)
        row = QtWidgets.QHBoxLayout()
        b1 = QtWidgets.QPushButton(QtGui.QIcon.fromTheme("view-refresh"), tr("Suchen"))
        b1.clicked.connect(self.search)
        b2 = QtWidgets.QPushButton(QtGui.QIcon.fromTheme("list-add"), tr("Hinzufügen"))
        b2.clicked.connect(self.run_wizard)
        row.addWidget(b1)
        row.addWidget(b2)
        lay.addLayout(row)
        lay.addSpacing(14)
        self.nav = QtWidgets.QListWidget()
        self.nav.setObjectName("nav")
        for label, icon_name in self.NAV:
            self.nav.addItem(QtWidgets.QListWidgetItem(QtGui.QIcon.fromTheme(icon_name), label))
        self.nav.currentRowChanged.connect(lambda r: r >= 0 and self.stack.setCurrentIndex(r))
        self.nav.hide()   # Bereiche erreicht man ueber die Kacheln der Uebersicht
        lay.addStretch(1)
        self.update_btn = QtWidgets.QPushButton()
        self.update_btn.setObjectName("primary")
        self.update_btn.clicked.connect(self.update_clicked)
        self.update_btn.hide()
        lay.addWidget(self.update_btn)
        v = QtWidgets.QPushButton(tr("Version {0}  ·  Info", APP_VERSION))
        v.setFlat(True)
        v.setCursor(QtCore.Qt.PointingHandCursor)
        v.setStyleSheet(f"text-align: left; background: transparent; color: {THEME.get('dim', '#888')}; padding: 4px 0;")
        v.clicked.connect(self.show_info)
        lay.addWidget(v)
        return side

    def show_info(self):
        d = QtWidgets.QDialog(self)
        d.setWindowTitle(tr("Über {0}", APP_NAME))
        d.setStyleSheet(make_qss())
        d.resize(560, 520)
        lay = QtWidgets.QVBoxLayout(d)
        lay.setContentsMargins(24, 22, 24, 20)
        lay.setSpacing(12)
        t = QtWidgets.QLabel(APP_NAME)
        t.setObjectName("title")
        lay.addWidget(t)
        v = QtWidgets.QLabel(tr("Version {0}", APP_VERSION))
        v.setObjectName("accent")
        lay.addWidget(v)
        desc = QtWidgets.QLabel(tr("Drucken, Scannen, Tinte/Toner und Wartung für Drucker unter Linux. "
                                "Inoffiziell und unabhängig von Druckerherstellern. Lizenz: MIT."))
        desc.setWordWrap(True)
        lay.addWidget(desc)
        upd = QtWidgets.QHBoxLayout()
        self.info_upd_label = QtWidgets.QLabel("")
        self.info_upd_label.setObjectName("dim")
        b = QtWidgets.QPushButton(tr("Nach Updates suchen"))
        b.setObjectName("primary")
        b.clicked.connect(self.manual_update)
        upd.addWidget(b)
        upd.addWidget(self.info_upd_label, 1)
        lay.addLayout(upd)
        # Sprache: zweisprachig beschriftet, damit man auch in einer fremden Sprache zurueckfindet
        lang_row = QtWidgets.QHBoxLayout()
        lang_row.addWidget(QtWidgets.QLabel("🌐  " + (tr("Sprache") + " / Language" if LANG != "en" else "Language")))
        lang = QtWidgets.QComboBox()
        for code, name in LANGUAGES.items():
            lang.addItem(name, code)
        lang.setCurrentIndex(max(0, lang.findData(LANG)))
        lang.currentIndexChanged.connect(
            lambda _i: self.change_language(lang.currentData(), d) or lang.setCurrentIndex(max(0, lang.findData(LANG))))
        lang_row.addWidget(lang)
        lang_row.addStretch(1)
        lay.addLayout(lang_row)
        sg, sl = group(tr("PrintDock-Server"))
        srow = QtWidgets.QHBoxLayout()
        if self.settings.value("server/token", ""):
            who = QtWidgets.QLabel(tr("Angemeldet als {0} bei {1}", self.settings.value("server/name", ""), server_url()))
            who.setWordWrap(True)
            srow.addWidget(who, 1)
            out = QtWidgets.QPushButton(tr("Abmelden"))
            out.clicked.connect(lambda: (self.server_logout(), d.accept()))
            srow.addWidget(out)
        else:
            srow.addWidget(QtWidgets.QLabel(tr("Nicht verbunden – für Drucker, die eine Firma oder ein Amt zentral verwaltet.")), 1)
            con = QtWidgets.QPushButton(tr("Verbinden…"))
            con.clicked.connect(lambda: (d.accept(), self.server_login_dialog()))
            srow.addWidget(con)
        sl.addLayout(srow)
        lay.addWidget(sg)
        g, gl = group(tr("Getestete Drucker"))
        for model in TESTED_PRINTERS:
            gl.addWidget(QtWidgets.QLabel(model))
        lay.addWidget(g)
        lay.addStretch(1)
        row = QtWidgets.QHBoxLayout()
        gh = QtWidgets.QPushButton(tr("Projektseite auf GitHub"))
        gh.clicked.connect(lambda: webbrowser.open(f"https://github.com/{UPDATE_REPO}"))
        close = QtWidgets.QPushButton(tr("Schließen"))
        close.clicked.connect(d.accept)
        row.addWidget(gh)
        row.addStretch(1)
        row.addWidget(close)
        lay.addLayout(row)
        d.exec()
        self.info_upd_label = None

    def change_language(self, code, dialog=None):
        """Sprache merken, Uebersetzung holen und PrintDock neu starten (Texte stehen beim Start fest)."""
        if code == LANG or code not in LANGUAGES:
            return False
        if not self.leave_scan_ok(discard=True):   # Neustart verwirft ungespeicherte Scans – vorher fragen
            return False
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            language_table(code, refresh=True)
            if code not in ("de", "en"):
                language_table("en")
            os.makedirs(INSTALL_DIR, exist_ok=True)
            with open(LANG_FILE, "w", encoding="utf-8") as f:
                f.write(code + "\n")
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        if dialog:
            dialog.accept()
        self.status.showMessage(tr("PrintDock startet neu, damit die neue Sprache gilt."))
        QtWidgets.QApplication.processEvents()
        restart_self()

    def scroll_page(self):
        sc = QtWidgets.QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QtWidgets.QFrame.NoFrame)
        holder = QtWidgets.QWidget()
        body = QtWidgets.QVBoxLayout(holder)
        body.setContentsMargins(0, 0, 8, 0)
        body.setSpacing(14)
        sc.setWidget(holder)
        return sc, body

    def titled(self, title, inner, framed=True):
        page = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        h = QtWidgets.QLabel(title)
        h.setObjectName("title")
        lay.addWidget(h)
        if framed:
            f, fl = group()
            fl.addWidget(inner)
            lay.addWidget(f, 1)
        else:
            lay.addWidget(inner, 1)
        return page

    def back_to_overview(self):
        if self.stack.currentIndex() == self.SCAN and not self.leave_scan_ok(discard=True):
            return   # ungespeicherte Scans: Nutzerin hat abgebrochen
        self.go(self.OVERVIEW)

    def go(self, page):
        self.stack.setCurrentIndex(page)
        self.back_btn.setVisible(page != self.OVERVIEW)
        self.nav.blockSignals(True)
        self.nav.setCurrentRow(page)
        self.nav.blockSignals(False)

    # ----- Uebersicht -----
    def build_overview(self):
        self.clear(self.ov_body)
        p = self.current
        if not p:
            t = QtWidgets.QLabel(tr("Kein Drucker"))
            t.setObjectName("title")
            self.ov_body.addWidget(t)
            hint = QtWidgets.QLabel(tr("Drucker einschalten und per USB anstecken oder ins selbe LAN/WLAN bringen, "
                                    "dann links auf „Suchen“ – oder „Hinzufügen“ für den Einrichtungs-Assistenten."))
            hint.setWordWrap(True)
            self.ov_body.addWidget(hint)
            self.ov_body.addStretch(1)
            return
        hero_frame = QtWidgets.QFrame()
        hero_frame.setObjectName("hero")
        head = QtWidgets.QHBoxLayout(hero_frame)
        head.setContentsMargins(28, 24, 28, 24)
        col = QtWidgets.QVBoxLayout()
        col.addStretch(1)
        t = QtWidgets.QLabel(self.nickname(p))
        t.setObjectName("big")
        col.addWidget(t)
        model = re.sub(r"\s+-\s+.*$", "", p.model or p.info or "")
        m = QtWidgets.QLabel(model)
        m.setObjectName("accent")
        m.setStyleSheet("font-size: 16px;")
        if norm(model) != norm(self.nickname(p)):   # nicht zweimal dasselbe
            col.addWidget(m)
        col.addSpacing(10)
        chips = QtWidgets.QHBoxLayout()
        self.ov_state = QtWidgets.QLabel(tr("Status wird abgefragt …"))
        self.ov_state.setObjectName("chip_off")
        chips.addWidget(self.ov_state)
        conn = QtWidgets.QLabel(p.connection)
        conn.setObjectName("chip_off")
        chips.addWidget(conn)
        chips.addStretch(1)
        col.addLayout(chips)
        col.addStretch(1)   # Abzeichen nicht in die Hoehe ziehen, wenn das Druckerbild die Karte hoeher macht
        if not p.queue:
            col.addSpacing(8)
            b = QtWidgets.QPushButton(tr("Drucker einrichten"))
            b.setObjectName("primary")
            b.clicked.connect(self.setup_current)
            col.addWidget(b, 0, QtCore.Qt.AlignLeft)
        head.addLayout(col, 1)
        icon = QtWidgets.QLabel()
        own = printer_image_path(p)
        pix = QtGui.QPixmap(own) if own else QtGui.QPixmap()
        if not pix.isNull():
            icon.setPixmap(pix.scaled(300, 170, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation))
        else:
            icon.setPixmap(QtGui.QIcon.fromTheme("printer").pixmap(128, 128))
        head.addWidget(icon)
        self.ov_body.addWidget(hero_frame)

        grid = QtWidgets.QGridLayout()
        grid.setSpacing(12)
        self.ov_tiles = {
            self.PRINT: tile(tr("Drucken"), tr("Dokumente und Fotos"), "document-print", lambda: self.go(self.PRINT)),
            self.SCAN: tile(tr("Scannen"), tr("Als PDF oder Bild speichern"), "scanner", lambda: self.go(self.SCAN)),
            self.FAX: tile(tr("Fax"), tr("Dokumente senden"), "mail-send", lambda: self.go(self.FAX)),
            self.MAINT: tile(tr("Wartung"), tr("Reinigen, Berichte, Aufträge"), "configure", lambda: self.go(self.MAINT)),
        }
        for i, w in enumerate(self.ov_tiles.values()):
            grid.addWidget(w, 0, i)
        self.ov_body.addLayout(grid)
        self.sync_tiles()

        self.ov_msgs_box, self.ov_msgs = group(tr("Meldungen"))
        self.ov_body.addWidget(self.ov_msgs_box)
        self.ov_msgs_box.hide()
        self.ov_ink_box, self.ov_ink = group(tr("Tinte"))
        self.ov_body.addWidget(self.ov_ink_box)
        self.ov_feat_label = None   # Funktionen zeigen die Kacheln selbst

        dev, dl = group(tr("Gerät"))
        form = QtWidgets.QFormLayout()
        form.addRow(tr("Modell"), QtWidgets.QLabel(re.sub(r"\s+-\s+.*$", "", p.model or "–")))
        form.addRow(tr("Verbindung"), QtWidgets.QLabel(p.connection))
        if p.location:
            form.addRow(tr("Standort"), QtWidgets.QLabel(p.location))
        if p.host:
            form.addRow(tr("Adresse"), QtWidgets.QLabel(p.host))
        form.addRow(tr("Warteschlange"), QtWidgets.QLabel(p.queue or tr("noch nicht eingerichtet")))
        tmpl = get_template(p)
        self.ov_tmpl_label = QtWidgets.QLabel(tmpl.get("name", "Standard"))
        form.addRow(tr("Vorlage"), self.ov_tmpl_label)
        dl.addLayout(form)
        rep_row = QtWidgets.QHBoxLayout()
        if tmpl.get("name", "Standard") == "Standard" or tmpl.get("eigene"):
            rep_note = QtWidgets.QLabel(tr("Selbst beschrieben – gilt, bis es eine offizielle Vorlage gibt.") if tmpl.get("eigene")
                                        else tr("Für dieses Modell gibt es noch keine Vorlage."))
            rep_note.setObjectName("dim")
            rep_row.addWidget(rep_note, 1)
        else:
            rep_row.addStretch(1)
        if tmpl.get("name", "Standard") == "Standard" or tmpl.get("eigene"):
            own_btn = QtWidgets.QPushButton(tr("Eigenschaften festlegen…"))
            own_btn.clicked.connect(lambda: self.edit_properties(p))
            rep_row.addWidget(own_btn)
        rep_btn = QtWidgets.QPushButton(tr("Drucker melden…"))
        rep_btn.clicked.connect(lambda: self.report_printer(p))
        rep_row.addWidget(rep_btn)
        dl.addLayout(rep_row)
        self.ov_hints = QtWidgets.QVBoxLayout()
        dl.addLayout(self.ov_hints)
        self.ov_body.addWidget(dev)
        self.ov_body.addStretch(1)
        cached = self.status_cache.get(printer_key(p))
        if cached:
            self.fill_overview(cached)

    def add_manual_printer(self):
        """Netzwerkdrucker, den die Suche nicht findet: Modell und Adresse eintippen, selbst beschreiben, einrichten.
        Spricht er IPP, wird er treiberlos eingerichtet; sonst ueber den klassischen Netzwerkanschluss (Port 9100)
        mit dem passenden freien Treiber."""
        d = QtWidgets.QDialog(self.top_parent())
        d.setWindowTitle(tr("Drucker von Hand hinzufügen"))
        d.setStyleSheet(make_qss())
        lay = QtWidgets.QVBoxLayout(d)
        intro = QtWidgets.QLabel(tr("Für Netzwerkdrucker, die die Suche nicht findet. Die IP-Adresse steht im "
                                    "Netzwerkbericht oder im Menü des Druckers."))
        intro.setWordWrap(True)
        lay.addWidget(intro)
        form = QtWidgets.QFormLayout()
        model = QtWidgets.QLineEdit()
        model.setPlaceholderText("Brother HL-L2350DW")
        ip = QtWidgets.QLineEdit()
        ip.setPlaceholderText("192.168.178.50")
        form.addRow(tr("Hersteller und Modell"), model)
        form.addRow(tr("IP-Adresse"), ip)
        lay.addLayout(form)
        warn = QtWidgets.QLabel()
        warn.setWordWrap(True)
        warn.setStyleSheet(f"color: {STATE_COLORS['err']};")
        warn.hide()
        lay.addWidget(warn)
        row = QtWidgets.QHBoxLayout()
        cancel = QtWidgets.QPushButton(tr("Abbrechen"))
        go = QtWidgets.QPushButton(tr("Weiter"))
        go.setObjectName("primary")
        go.setDefault(True)
        row.addStretch(1)
        row.addWidget(cancel)
        row.addWidget(go)
        lay.addLayout(row)
        cancel.clicked.connect(d.reject)
        result = {}

        def check():
            host = ip.text().strip()
            if not model.text().strip() or not re.fullmatch(r"[A-Za-z0-9.:-]+", host):
                warn.setText(tr("Bitte Modell und eine gültige IP-Adresse angeben."))
                warn.show()
                return
            go.setEnabled(False)
            go.setText(tr("Prüfe …"))

            def probe():
                import socket
                for port in (631, 9100):
                    try:
                        socket.create_connection((host, port), timeout=3).close()
                        return port
                    except OSError:
                        continue
                return None

            def done(ok, port):
                go.setEnabled(True)
                go.setText(tr("Weiter"))
                if not ok or not port:
                    warn.setText(tr("Unter {0} antwortet kein Drucker. Ist er eingeschaltet und die Adresse richtig?", host))
                    warn.show()
                    return
                result["host"], result["port"] = host, port
                d.accept()
            bg(probe, done)
        go.clicked.connect(check)
        d.resize(480, 0)
        if d.exec() != QtWidgets.QDialog.Accepted:
            return
        p = Printer()
        p.model = p.info = model.text().strip()
        p.host = result["host"]
        p.uris = [f"ipp://{p.host}:631/ipp/print" if result["port"] == 631 else f"socket://{p.host}:9100"]
        if p not in self.printers:
            self.printers.append(p)
        self.current = p
        self.fill_printer_list()
        self.select(len(self.printers) - 1)
        self.edit_properties(p)   # selbst beschreiben, auf Wunsch melden
        self.setup_current()

    def edit_properties(self, p):
        """Drucker selbst beschreiben, solange es keine offizielle Vorlage gibt. Gilt nur auf diesem PC; kommt die
        offizielle Vorlage, loest sie diese ab und PrintDock meldet, dass der Drucker aufgenommen ist."""
        cur = get_template(p)
        sup = (self.status_cache.get(printer_key(p)) or {}).get("supported", {})
        d = QtWidgets.QDialog(self)
        d.setWindowTitle(tr("Eigenschaften festlegen"))
        d.setStyleSheet(make_qss())
        lay = QtWidgets.QVBoxLayout(d)
        intro = QtWidgets.QLabel(tr("Für „{0}“ gibt es noch keine Vorlage. Beschreibe ihn hier, dann kannst du ihn "
                                    "sofort nutzen. Sobald es eine offizielle Vorlage gibt, übernimmt PrintDock sie "
                                    "und sagt Bescheid.", real_name(p)))
        intro.setWordWrap(True)
        lay.addWidget(intro)
        form = QtWidgets.QFormLayout()
        color = QtWidgets.QCheckBox(tr("Druckt in Farbe"))
        color.setChecked(cur.get("farbe") is not False and "color" in (sup.get("print-color-mode-supported") or ["color"]))
        duplex = QtWidgets.QCheckBox(tr("Druckt selbst beidseitig"))
        duplex.setChecked(bool(cur.get("beidseitig", True)) and
                          "two-sided-long-edge" in (sup.get("sides-supported") or ["two-sided-long-edge"]))
        fax = QtWidgets.QCheckBox(tr("Kann faxen"))
        fax.setChecked(bool(cur.get("fax") if cur.get("fax") is not None else p.fax))
        scan = QtWidgets.QComboBox()
        for lbl, v in ((tr("Kein Scanner"), "keiner"), (tr("Nur Scannerglas"), "glas"),
                       (tr("Scannerglas und Vorlageneinzug"), "einzug"),
                       (tr("Vorlageneinzug kann beidseitig"), "einzug-beidseitig")):
            scan.addItem(lbl, v)
        guess = cur.get("scanner") or ("glas" if self.printer_has_scanner(p) else "keiner")
        scan.setCurrentIndex(max(0, scan.findData(guess)))
        paper = QtWidgets.QComboBox()
        for lbl, v in (("A4", "iso_a4_210x297mm"), ("Letter", "na_letter_8.5x11in")):
            paper.addItem(lbl, v)
        paper.setCurrentIndex(max(0, paper.findData(cur.get("papier"))))
        hints = QtWidgets.QPlainTextEdit("\n".join(cur.get("hinweise") or []) if cur.get("eigene") else "")
        hints.setPlaceholderText(tr("Hinweise, eine Zeile je Hinweis (freiwillig)"))
        hints.setMaximumHeight(80)
        for w in (color, duplex, fax):
            form.addRow("", w)
        form.addRow(tr("Scanner"), scan)
        form.addRow(tr("Papier"), paper)
        form.addRow(tr("Hinweise"), hints)
        lay.addLayout(form)
        also = QtWidgets.QCheckBox(tr("Drucker auch an PrintDock melden, damit eine offizielle Vorlage entsteht"))
        also.setChecked(not cur.get("eigene"))
        lay.addWidget(also)
        row = QtWidgets.QHBoxLayout()
        cancel = QtWidgets.QPushButton(tr("Abbrechen"))
        ok = QtWidgets.QPushButton(tr("Speichern"))
        ok.setObjectName("primary")
        row.addStretch(1)
        row.addWidget(cancel)
        row.addWidget(ok)
        lay.addLayout(row)
        cancel.clicked.connect(d.reject)
        ok.clicked.connect(d.accept)
        d.resize(520, 0)
        if d.exec() != QtWidgets.QDialog.Accepted:
            return
        data = {"name": tr("Eigene Vorlage"), "beidseitig": duplex.isChecked(), "fax": fax.isChecked(),
                "farbe": color.isChecked(), "scanner": scan.currentData(), "papier": paper.currentData(),
                "hinweise": [x.strip() for x in hints.toPlainText().splitlines() if x.strip()]}
        os.makedirs(TEMPLATE_DIR, exist_ok=True)
        with open(own_template_path(p), "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=1)
        p.fax = data["fax"]
        self.apply_template(p, get_template(p))
        self.apply_supported((self.status_cache.get(printer_key(p)) or {}).get("supported", {}))
        self.build_overview()
        self.update_actions()
        self.status.showMessage(tr("Gespeichert – gilt, bis es eine offizielle Vorlage gibt."))
        if also.isChecked():
            self.report_printer(p)

    def report_printer(self, p):
        """Steckbrief zeigen; Absenden oeffnet ein vorausgefuelltes GitHub-Issue (nichts geht ungesehen raus)."""
        d = QtWidgets.QDialog(self)
        d.setWindowTitle(tr("Drucker melden"))
        d.setStyleSheet(make_qss())
        d.resize(620, 520)
        lay = QtWidgets.QVBoxLayout(d)
        intro = QtWidgets.QLabel(tr("Damit wir eine Vorlage für diesen Drucker bauen können. Gesendet wird nur, was "
                                    "unten steht – keine Seriennummer, keine Adresse, keine Namen."))
        intro.setWordWrap(True)
        lay.addWidget(intro)
        text = QtWidgets.QPlainTextEdit(tr("Frage den Drucker …"))
        text.setReadOnly(True)
        lay.addWidget(text, 1)
        lay.addWidget(QtWidgets.QLabel(tr("Anmerkung (freiwillig), z. B. was nicht geht:")))
        note = QtWidgets.QPlainTextEdit()
        note.setMaximumHeight(80)
        lay.addWidget(note)
        hint = QtWidgets.QLabel(tr("„Auf GitHub melden“ öffnet den Browser; dafür braucht es ein GitHub-Konto. "
                                   "Ohne Konto: speichern und anders schicken."))
        hint.setObjectName("dim")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        row = QtWidgets.QHBoxLayout()
        save = QtWidgets.QPushButton(tr("Als Datei speichern…"))
        cancel = QtWidgets.QPushButton(tr("Abbrechen"))
        send = QtWidgets.QPushButton(tr("Auf GitHub melden"))
        send.setObjectName("primary")
        for b in (save, send):
            b.setEnabled(False)
        row.addWidget(save)
        row.addStretch(1)
        row.addWidget(cancel)
        row.addWidget(send)
        lay.addLayout(row)
        result = {}

        def done(ok, res):
            if not ok:
                text.setPlainText(tr("Fehler: {0}", res))
                return
            result["title"], result["body"] = res
            text.setPlainText(res[0] + "\n\n" + res[1])
            save.setEnabled(True)
            send.setEnabled(True)

        def do_send():
            webbrowser.open(report_url(result["title"], result["body"], note.toPlainText()))
            d.accept()
            self.status.showMessage(tr("Im Browser abschicken – danke!"))

        def do_save():
            path, _ = QtWidgets.QFileDialog.getSaveFileName(d, tr("Als Datei speichern…"),
                                                            os.path.join(os.path.expanduser("~"), "drucker.md"),
                                                            "Markdown (*.md);;Text (*.txt)")
            if path:
                extra = ("\n\n### Anmerkung / note\n" + note.toPlainText().strip()) if note.toPlainText().strip() else ""
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(f"# {result['title']}\n\n{result['body']}{extra}\n")
                self.status.showMessage(tr("Gespeichert: {0}", path))
        send.clicked.connect(do_send)
        save.clicked.connect(do_save)
        cancel.clicked.connect(d.reject)
        bg(lambda: printer_report(p), done)
        d.exec()

    def fill_overview(self, res):
        if not getattr(self, "ov_state", None):
            return
        try:
            state = res.get("state") or ("Erreichbar" if res.get("markers") else "Unbekannt")
            self.ov_state.setText(("● " + state) if state else state)
            kind = "chip_warn" if res.get("reasons") else ("chip_ok" if res.get("state") else "chip_off")
            self.ov_state.setObjectName(kind)
            self.ov_state.style().unpolish(self.ov_state)
            self.ov_state.style().polish(self.ov_state)
            self.clear(self.ov_msgs)
            texts = [reason_text(r) for r in res.get("reasons", [])] + ([res["message"]] if res.get("message") else [])
            h = QtWidgets.QLabel(tr("Meldungen"))
            h.setObjectName("h2")
            self.ov_msgs.addWidget(h)
            reasons = res.get("reasons", [])
            for i, t in enumerate(texts):
                r = reasons[i] if i < len(reasons) else ""
                bad = r.endswith("-error") or reason_base(r) in REASONS_URGENT
                lab = QtWidgets.QLabel(f"⚠  {t}")
                lab.setWordWrap(True)
                lab.setStyleSheet(f"color: {STATE_COLORS['err' if bad else 'warn']};")
                self.ov_msgs.addWidget(lab)
            self.ov_msgs_box.setVisible(bool(texts))
            self.fill_features(res)
            self.clear(self.ov_ink)
            markers = res.get("markers", [])
            h = QtWidgets.QLabel(tr("Toner") if is_toner(markers) else tr("Tinte"))
            h.setObjectName("h2")
            self.ov_ink.addWidget(h)
            for mk in markers:
                self.ov_ink.addWidget(InkBar(mk))
            if not markers:
                lab = QtWidgets.QLabel(tr("Füllstände gibt es wieder, wenn der Drucker an ist.") if "offline" in res.get("reasons", [])
                                       else tr("Der Drucker meldet keinen Füllstand.") if (self.current and (self.current.queue or self.current.host))
                                       else tr("Füllstände gibt es nach dem Einrichten."))
                lab.setObjectName("dim")
                self.ov_ink.addWidget(lab)
        except RuntimeError:
            pass   # Seite wurde gerade neu aufgebaut

    def fill_features(self, res=None):
        """Funktionsprofil: was dieser Drucker kann (aus IPP und Scanner-Suche)."""
        p = self.current
        if not p or not getattr(self, "ov_feat_label", None):
            return
        res = res or self.status_cache.get(printer_key(p)) or {}
        sup = res.get("supported", {})
        feats = []
        modes = sup.get("print-color-mode-supported") or []
        if modes:
            feats.append(tr("✓ Farbdruck") if "color" in modes else tr("✓ Schwarzweißdruck"))
        sides = sup.get("sides-supported") or []
        if sides:
            feats.append(tr("✓ Beidseitig drucken") if any(x.startswith("two-sided") for x in sides) else tr("✗ nur einseitig"))
        if self.printer_has_scanner(p):
            feats.append(tr("✓ Scannen") + (tr(" mit Vorlageneinzug") if getattr(self, "duplex_value", None) or
                                        any(re.search(r"adf|feeder", self.scan_source.itemData(i) or "", re.I)
                                            for i in range(self.scan_source.count())) else ""))
        try:
            self.clear(self.ov_feat_row)
            for f in feats:
                lab = QtWidgets.QLabel(f.replace("✓ ", ""))
                lab.setObjectName("chip_off" if f.startswith("✗") else "badge")
                self.ov_feat_row.addWidget(lab)
            if not feats:
                lab = QtWidgets.QLabel(tr("Erst nach dem Einrichten bekannt."))
                lab.setObjectName("dim")
                self.ov_feat_row.addWidget(lab)
            self.ov_feat_row.addStretch(1)
            self.ov_feat_label = lab if not feats else self.ov_feat_label
        except RuntimeError:
            pass

    def sync_tiles(self):
        p = self.current
        show = {self.SCAN: bool(self.scanners), self.FAX: bool(p and p.fax)}
        for page, w in getattr(self, "ov_tiles", {}).items():
            try:
                w.setVisible(show.get(page, True))
            except RuntimeError:
                pass

    def printer_has_scanner(self, p):
        if (getattr(p, "template", None) or {}).get("scanner") == "keiner":
            return False
        words = [w for w in re.findall(r"[a-z0-9]+", (p.model or p.title).lower())
                 if w not in ("hp", "series", "ipp", "everywhere") and len(w) > 2]
        return any(sum(w in (dev + desc).lower() for w in words) >= 1 for dev, desc in self.scanners)

    # ----- Wartung -----
    def build_maintenance(self):
        self.clear(self.mt_body)
        t = QtWidgets.QLabel(tr("Wartung"))
        t.setObjectName("title")
        self.mt_body.addWidget(t)
        p = self.current
        # Druckauftraege (alle Marken)
        jobs, jl = group(tr("Druckaufträge"))
        self.job_list = QtWidgets.QListWidget()
        self.job_list.setMaximumHeight(130)
        jl.addWidget(self.job_list)
        r = QtWidgets.QHBoxLayout()
        for text, cb in (("Aktualisieren", self.refresh_jobs), (tr("Ausgewählten abbrechen"), self.cancel_job),
                         (tr("Alle abbrechen"), self.cancel_all_jobs)):
            b = QtWidgets.QPushButton(text)
            b.clicked.connect(cb)
            b.setEnabled(bool(p and p.queue))
            r.addWidget(b)
        r.addStretch(1)
        jl.addLayout(r)
        self.mt_body.addWidget(jobs)
        # Qualitaet und Berichte: werden je nach Drucker gefuellt
        self.mt_quality, self.mt_q = group(tr("Druckkopf und Qualität"))
        self.mt_reports, self.mt_r = group(tr("Berichte"))
        self.mt_body.addWidget(self.mt_quality)
        self.mt_body.addWidget(self.mt_reports)
        self.mt_reports.hide()
        if p:
            self.add_maint_row(self.mt_q, "document-print", tr("Testseite drucken"), tr("Prüft, ob Druck und Farben stimmen."),
                               self.test_page, bool(p.queue))
            if p.host:
                self.add_maint_row(self.mt_q, "internet-web-browser", tr("Weboberfläche des Druckers"),
                                   tr("Weitere Werkzeuge am Drucker selbst ({0}), z. B. Ausrichten.", p.host), self.open_web, True)
            self.load_maintenance(p)
        else:
            lab = QtWidgets.QLabel(tr("Kein Drucker gewählt."))
            lab.setObjectName("dim")
            self.mt_q.addWidget(lab)
        f2, fl2 = group(tr("Einrichtung"))
        r = QtWidgets.QHBoxLayout()
        a = QtWidgets.QPushButton(QtGui.QIcon.fromTheme("tools-wizard"), tr("Einrichtungs-Assistent"))
        a.clicked.connect(self.run_wizard)
        r.addWidget(a)
        if p:
            rn = QtWidgets.QPushButton(QtGui.QIcon.fromTheme("document-edit"), tr("Drucker umbenennen"))
            rn.clicked.connect(self.rename)
            r.addWidget(rn)
            pic = QtWidgets.QPushButton(QtGui.QIcon.fromTheme("insert-image"), tr("Bild für diesen Druckertyp…"))
            pic.clicked.connect(self.choose_printer_image)
            r.addWidget(pic)
        if p and p.queue:
            rm = QtWidgets.QPushButton(QtGui.QIcon.fromTheme("list-remove"), tr("Drucker von diesem PC entfernen"))
            rm.clicked.connect(self.remove_current)
            r.addWidget(rm)
        r.addStretch(1)
        fl2.addLayout(r)
        self.mt_body.addWidget(f2)
        self.mt_body.addStretch(1)
        self.refresh_jobs()

    def add_maint_row(self, lay, icon_name, text, desc, cb, enabled=True, button=tr("Ausführen")):
        r = QtWidgets.QHBoxLayout()
        ic = QtWidgets.QLabel()
        ic.setPixmap(QtGui.QIcon.fromTheme(icon_name).pixmap(22, 22))
        r.addWidget(ic)
        col = QtWidgets.QVBoxLayout()
        col.addWidget(QtWidgets.QLabel(text))
        if desc:
            d = QtWidgets.QLabel(desc)
            d.setObjectName("dim")
            col.addWidget(d)
        r.addLayout(col, 1)
        b = QtWidgets.QPushButton(button)
        b.setEnabled(enabled)
        b.clicked.connect(cb)
        r.addWidget(b)
        lay.addLayout(r)

    def load_maintenance(self, p):
        """Was dieser Drucker an Wartung kann: Geraeteschnittstelle (HP, LEDM) und CUPS-Befehle des Treibers."""
        ip = p.host if re.fullmatch(r"[\d.]+", p.host or "") else None

        def work():
            # Andere Marken antworten dort einfach nicht – dann bleibt die Liste leer
            return {"ledm": ledm_jobs(ip) if ip else [],
                    "cups": cups_commands(p.queue) if p.queue else []}

        def done(ok, res):
            if not ok or p is not self.current:
                return
            try:
                seen = set()
                # Reinigung: ein Knopf, die Stufen folgen nach Rueckfrage (wie am Drucker selbst)
                levels = [j for j in CLEAN_LEVELS if j in res["ledm"]]
                if levels:
                    seen.add("clean")
                    self.add_maint_row(self.mt_q, "configure", tr("Druckkopf reinigen"),
                                       tr("Bei Streifen oder blassen Farben. Druckt eine Seite; danach fragt die App, "
                                       "ob eine gründlichere Reinigung nötig ist."),
                                       lambda _=False: self.start_cleaning(p, ip, levels))
                allowed = get_template(p).get("wartung")
                for job in res["ledm"]:
                    if job in CLEAN_LEVELS or job not in LEDM_LABELS or LEDM_LABELS[job][1] in seen:
                        continue
                    if allowed is not None and job not in allowed:
                        continue
                    kind, text, desc = LEDM_LABELS[job]
                    seen.add(text)
                    lay = self.mt_q if kind == "quality" else self.mt_r
                    self.add_maint_row(lay, "configure" if kind == "quality" else "document-preview", text, desc,
                                       lambda _=False, j=job, t=text: self.run_ledm(ip, j, t),
                                       button=tr("Drucken") if kind == "report" else tr("Ausführen"))
                    if kind == "report":
                        self.mt_reports.show()
                for c in res["cups"]:
                    if c in CUPS_COMMANDS and not (c == "Clean" and "clean" in seen):
                        text, desc = CUPS_COMMANDS[c]
                        self.add_maint_row(self.mt_q, "configure", text, desc,
                                           lambda _=False, cc=c: self.run_cups_command(cc))
            except RuntimeError:
                pass   # Seite wurde inzwischen neu aufgebaut
        bg(work, done)

    def start_cleaning(self, p, ip, levels, step=0):
        """Stufe fuer Stufe: reinigen, warten bis der Drucker fertig ist, fragen ob es reicht."""
        if step == 0 and QtWidgets.QMessageBox.question(
                self, APP_NAME, tr("Druckkopf reinigen?\n\nDie Reinigung verbraucht etwas Tinte und druckt eine "
                "Seite – bitte Papier einlegen.")) != QtWidgets.QMessageBox.Yes:
            return
        stufe = tr("Stufe {0} von {1}", step + 1, len(levels))
        self.status.showMessage(tr("Druckkopf wird gereinigt ({0}) …", stufe))

        def work():
            ledm_run(ip, levels[step])
            time.sleep(15)   # der Drucker beginnt erst nach ein paar Sekunden
            deadline = time.time() + 300
            while time.time() < deadline:
                if query_status(p).get("state") == tr("Bereit"):
                    return
                time.sleep(5)

        def done(ok, res):
            if not ok:
                self.status.showMessage(tr("Reinigung fehlgeschlagen: {0}", res))
                return
            self.status.showMessage(tr("Reinigung {0} fertig.", stufe))
            if step + 1 >= len(levels):
                QtWidgets.QMessageBox.information(
                    self, APP_NAME, tr("Die gründlichste Reinigung ist durch.\n\nSind noch Streifen zu sehen, hilft oft "
                    "eine Pause von ein paar Stunden – oder die Patrone ist leer bzw. eingetrocknet."))
                return
            box = QtWidgets.QMessageBox(self)
            box.setWindowTitle(APP_NAME)
            box.setText(tr("Ist das Druckbild auf der gedruckten Seite jetzt in Ordnung?"))
            box.setInformativeText(tr("Sind noch Streifen oder Lücken zu sehen, folgt eine gründlichere Reinigung "
                                   "(braucht mehr Tinte)."))
            ok_btn = box.addButton(tr("Ja, fertig"), QtWidgets.QMessageBox.AcceptRole)
            more = box.addButton(tr("Weitere Reinigung"), QtWidgets.QMessageBox.ActionRole)
            box.setDefaultButton(ok_btn)
            box.exec()
            if box.clickedButton() is more:
                self.start_cleaning(p, ip, levels, step + 1)
        bg(work, done)

    def run_ledm(self, ip, job, text):
        if job.startswith("cleaningPage") and QtWidgets.QMessageBox.question(
                self, APP_NAME, tr("{0} starten?\n\nDie Reinigung verbraucht Tinte und druckt eine Seite – Papier einlegen.", text)) != QtWidgets.QMessageBox.Yes:
            return
        self.status.showMessage(tr("{0} …", text))
        bg(lambda: ledm_run(ip, job),
           lambda ok, res: self.status.showMessage(tr("{0}: gestartet.", text) if ok else tr("{0} fehlgeschlagen: {1}", text, res)))

    def run_cups_command(self, cmd):
        p = self.current
        if not p or not p.queue:
            return
        bg(lambda: cups_command(p.queue, cmd),
           lambda ok, res: self.status.showMessage(tr("{0}: gesendet.", CUPS_COMMANDS[cmd][0]) if ok else tr("Fehlgeschlagen: {0}", res)))

    def refresh_jobs(self):
        p = self.current
        if not p or not p.queue or not getattr(self, "job_list", None):
            return

        def work():
            if WINDOWS:
                return win_jobs(p.queue)
            jobs = cups.Connection().getJobs(which_jobs="not-completed", requested_attributes=[
                "job-id", "job-name", "job-state", "job-printer-uri"])
            return {jid: j for jid, j in jobs.items() if str(j.get("job-printer-uri", "")).endswith("/" + p.queue)}

        def done(ok, jobs):
            try:
                self.job_list.clear()
                if not ok:
                    self.job_list.addItem(tr("Nicht abrufbar: {0}", jobs))
                    return
                states = {3: "wartet", 4: "angehalten", 5: "druckt", 6: "gestoppt"}
                for jid, j in sorted(jobs.items()):
                    item = QtWidgets.QListWidgetItem(f"#{jid}  {j.get('job-name', '')}  –  {states.get(j.get('job-state'), '')}")
                    item.setData(QtCore.Qt.UserRole, jid)
                    self.job_list.addItem(item)
                if not jobs:
                    self.job_list.addItem(tr("Keine offenen Druckaufträge."))
            except RuntimeError:
                pass
        bg(work, done)

    def cancel_job(self):
        item = self.job_list.currentItem()
        jid = item.data(QtCore.Qt.UserRole) if item else None
        if jid:
            q = self.current.queue if self.current else ""
            bg(lambda: powershell(f"Remove-PrintJob -PrinterName {ps_quote(q)} -ID {int(jid)}", 60) if WINDOWS
               else cups.Connection().cancelJob(jid),
               lambda ok, res: (self.status.showMessage(tr("Auftrag abgebrochen.") if ok else tr("Abbrechen fehlgeschlagen: {0}", res)),
                                self.refresh_jobs()))

    def cancel_all_jobs(self):
        p = self.current
        if not p or not p.queue:
            return
        if QtWidgets.QMessageBox.question(self.top_parent(), APP_NAME, tr("Alle offenen Druckaufträge abbrechen?")) != QtWidgets.QMessageBox.Yes:
            return
        bg(lambda: powershell(f"Get-PrintJob -PrinterName {ps_quote(p.queue)} | Remove-PrintJob", 60) if WINDOWS
           else cups.Connection().cancelAllJobs(name=p.queue),
           lambda ok, res: (self.status.showMessage(tr("Alle Aufträge abgebrochen.") if ok else tr("Fehlgeschlagen: {0}", res)),
                            self.refresh_jobs()))

    # ----- Druckerliste links -----
    def fill_printer_list(self):
        self.printer_list.blockSignals(True)
        self.printer_list.clear()
        for p in self.printers:
            res = self.status_cache.get(printer_key(p))
            if not p.queue:
                color = STATE_COLORS["off"]
            elif res and res.get("reasons"):
                color = STATE_COLORS["warn"]
            else:
                color = STATE_COLORS["ok"]
            sub = tr("nicht eingerichtet") if not p.queue else (p.location or p.connection.split(" ")[0])
            self.printer_list.addItem(QtWidgets.QListWidgetItem(dot_icon(color), f"{self.nickname(p)}\n{sub}"))
        if self.current in self.printers:
            self.printer_list.setCurrentRow(self.printers.index(self.current))
        self.printer_list.blockSignals(False)

    # ----- Drucker suchen und waehlen -----
    def load_cached_printers(self):
        """Drucker aus dem letzten Lauf sofort zeigen; die Suche dauert einige Sekunden."""
        try:
            cached = [Printer.from_dict(d) for d in json.loads(self.settings.value("printers_cache", "[]") or "[]")]
        except (ValueError, TypeError):
            cached = []
        if not cached:
            return
        self.printers = cached
        old = self.settings.value("last_printer", "")
        idx = next((i for i, p in enumerate(cached) if printer_key(p) == old), 0)
        self.current = cached[idx]
        self.fill_printer_list()
        self.select(idx)

    @staticmethod
    def printers_sig(printers):
        return [(printer_key(p), p.queue, sorted(p.uris), p.host) for p in printers]

    def search(self):
        self.act_search.setEnabled(False)
        self.status.showMessage(tr("Suche Drucker (USB und Netzwerk)…"))

        def done(ok, res):
            self.act_search.setEnabled(True)
            if not ok:
                self.status.showMessage(tr("Suche fehlgeschlagen: {0}", res))
                return
            if res:
                for p in res:
                    # Bekanntes behalten: ist der Drucker aus, findet die Suche nur die Warteschlange
                    # (ohne IP) – dann fehlten Name und Statusabfrage
                    known = next((q for q in self.printers if printer_key(q) == printer_key(p)
                                  or (p.queue and q.queue == p.queue)), None)
                    if known is None:
                        continue
                    p.uris += [u for u in known.uris if u not in p.uris]
                    if re.fullmatch(r"[\d.]+", known.host or "") and not re.fullmatch(r"[\d.]+", p.host or ""):
                        p.host = known.host
                    p.model = p.model or known.model
                self.settings.setValue("printers_cache", json.dumps([p.to_dict() for p in res]))
            elif self.printers:
                self.status.showMessage(tr("Drucker gerade nicht erreichbar – ist er eingeschaltet?"))
                return
            if self.printers and self.printers_sig(res) == self.printers_sig(self.printers):
                # nichts Neues: Anzeige nicht neu aufbauen, nur die frischen Daten uebernehmen
                for old_p, new_p in zip(self.printers, res):
                    old_p.__dict__.update({k: v for k, v in new_p.__dict__.items() if v is not None})
                self.status.showMessage(tr("{0} Drucker gefunden.", len(res)))
                return
            old = printer_key(self.current) if self.current else self.settings.value("last_printer", "")
            self.printers = res
            self.status.showMessage(tr("{0} Drucker gefunden.", len(res)) if res else
                                    tr("Kein Drucker gefunden. Ist er eingeschaltet und per USB oder im selben Netz verbunden?"))
            idx = next((i for i, p in enumerate(res) if printer_key(p) == old), None)
            if idx is None:
                idx = next((i for i, p in enumerate(res) if p.queue), 0 if res else -1)
            self.current = res[idx] if 0 <= idx < len(res) else None
            self.fill_printer_list()
            self.select(idx)
            for p in res:
                if p is not self.current:
                    self.refresh_status(p)
        bg(self.discover_with_server, lambda ok, res: (done(ok, res), self.after_server_sync()))

    def discover_with_server(self):
        """Suche wie bisher; ist die App bei einem PrintDock-Server angemeldet, kommen dessen Drucker dazu.
        Laeuft im Hintergrund – Fehler des Servers werden gemerkt und danach im Fenster gemeldet."""
        self.server_problem = None
        found = discover()
        if server_url() and server_settings().value("server/token", ""):
            try:
                merge_server_printers(found, server_printers())
            except ServerAuthError as e:
                self.server_problem = ("auth", str(e))
            except Exception as e:
                self.server_problem = ("other", str(e))
        return found

    def after_server_sync(self):
        problem = getattr(self, "server_problem", None)
        if problem and problem[0] == "auth":
            self.settings.remove("server/token")
            self.status.showMessage(problem[1])
            QtCore.QTimer.singleShot(200, self.server_login_dialog)
        elif problem:
            self.status.showMessage(tr("PrintDock-Server: {0}", problem[1]))
        else:
            todo = [p for p in self.printers if p.server_id and not p.queue]
            if todo:
                self.status.showMessage(tr("{0} zugewiesene(r) Drucker noch nicht eingerichtet.", len(todo)))

    # ----- PrintDock-Server: Anmeldung -----
    def server_login_dialog(self, parent=None):
        d = QtWidgets.QDialog(parent or self)
        d.setWindowTitle(tr("Mit PrintDock-Server verbinden"))
        d.setStyleSheet(make_qss())
        lay = QtWidgets.QVBoxLayout(d)
        lay.setContentsMargins(22, 20, 22, 18)
        intro = QtWidgets.QLabel(tr("Firmen und Ämter verwalten ihre Drucker zentral. Nach der Anmeldung "
                                    "richtet PrintDock die Drucker ein, die dir zugewiesen sind."))
        intro.setWordWrap(True)
        lay.addWidget(intro)
        form = QtWidgets.QFormLayout()
        url = QtWidgets.QLineEdit(server_url())
        url.setPlaceholderText("https://drucker.example.org")
        user = QtWidgets.QLineEdit(self.settings.value("server/user", "") or "")
        pw = QtWidgets.QLineEdit()
        pw.setEchoMode(QtWidgets.QLineEdit.Password)
        form.addRow(tr("Server-Adresse"), url)
        form.addRow(tr("Benutzername"), user)
        form.addRow(tr("Passwort"), pw)
        lay.addLayout(form)
        warn = QtWidgets.QLabel()
        warn.setWordWrap(True)
        warn.setStyleSheet(f"color: {STATE_COLORS['err']};")
        warn.hide()
        lay.addWidget(warn)

        def check_url():
            insecure = server_insecure(url.text().strip())
            warn.setText(tr("Achtung: ohne https gehen Passwort und Anmeldung unverschlüsselt durchs Netz."))
            warn.setVisible(insecure)
        url.textChanged.connect(check_url)
        check_url()
        row = QtWidgets.QHBoxLayout()
        later = QtWidgets.QPushButton(tr("Später"))
        later.clicked.connect(d.reject)
        go = QtWidgets.QPushButton(tr("Anmelden"))
        go.setObjectName("primary")
        go.setDefault(True)
        row.addStretch(1)
        row.addWidget(later)
        row.addWidget(go)
        lay.addLayout(row)
        (pw if user.text() else user).setFocus()

        def submit():
            if not url.text().strip() or not user.text().strip() or not pw.text():
                warn.setText(tr("Bitte Adresse, Benutzername und Passwort angeben."))
                warn.show()
                return
            go.setEnabled(False)
            go.setText(tr("Melde an…"))

            def done(ok, res):
                go.setEnabled(True)
                go.setText(tr("Anmelden"))
                if not ok:
                    warn.setText(str(res))
                    warn.show()
                    return
                u, token, name, role = res
                self.settings.setValue("server/url", u)
                self.settings.setValue("server/user", user.text().strip())
                self.settings.setValue("server/token", token)
                self.settings.setValue("server/name", name)
                self.settings.setValue("server/role", role)
                d.accept()
                self.status.showMessage(tr("Angemeldet als {0}.", name))
                self.server_sync_and_setup()
            bg(lambda: server_login(url.text(), user.text().strip(), pw.text()), done)
        go.clicked.connect(submit)
        pw.returnPressed.connect(submit)
        d.resize(460, 0)
        d.exec()

    def server_logout(self):
        token = self.settings.value("server/token", "")
        if token:
            bg(lambda: server_request("POST", "/api/v1/logout", {}, token=token))   # Fehler egal: lokal ist es weg
        self.settings.remove("server/token")
        for p in self.printers:
            p.server_id, p.location = None, ""
        self.fill_printer_list()
        self.status.showMessage(tr("Abgemeldet. Eingerichtete Drucker bleiben erhalten."))

    def server_sync_and_setup(self):
        """Nach der Anmeldung: Drucker holen und alle noch fehlenden mit einer Passwortabfrage einrichten."""
        def got(ok, res):
            if not ok:
                self.status.showMessage(tr("PrintDock-Server: {0}", res))
                return
            todo = [p for p in res if p.server_id and not p.queue]
            if not todo:
                self.search()
                return
            names = "\n".join("•  " + (p.info or p.model) + (f" ({p.location})" if p.location else "") for p in todo)
            if QtWidgets.QMessageBox.question(
                    self, APP_NAME, tr("Dir sind {0} Drucker zugewiesen:\n\n{1}\n\nJetzt einrichten? Ein Fenster fragt "
                                       "einmal nach deinem Passwort.", len(todo), names)) != QtWidgets.QMessageBox.Yes:
                self.search()
                return
            self.status.showMessage(tr("Richte Drucker ein…"))
            bg(lambda: setup_printers_batch(todo),
               lambda ok2, n: (self.status.showMessage(tr("{0} Drucker eingerichtet.", n) if ok2
                                                       else tr("Einrichten fehlgeschlagen: {0}", n)),
                               QtCore.QTimer.singleShot(1500, self.search)))
        bg(self.discover_with_server, got)

    def select(self, row):
        self.current = self.printers[row] if row is not None and 0 <= row < len(self.printers) else None
        p = self.current
        if p:
            self.settings.setValue("last_printer", printer_key(p))
        self.build_overview()
        self.build_maintenance()
        self.update_actions()
        if p:
            self.refresh_status()
            self.match_scanner()
            self.load_template(p)

    def load_template(self, p):
        """Vorlage des Modells: gemerkte sofort anwenden, sonst einmal herunterladen."""
        self.apply_template(p, get_template(p))

        def done(ok, tmpl):
            if ok and p is self.current:
                self.apply_template(p, tmpl)
            if ok and getattr(p, "newly_supported", False):
                p.newly_supported = False
                msg = tr("Dein Drucker „{0}“ ist jetzt in PrintDock aufgenommen – die passende Vorlage wurde geladen.",
                         self.nickname(p))
                notify(APP_NAME, msg)
                self.status.showMessage(msg)
                if p is self.current:
                    self.build_overview()
            if p is self.current:
                self.check_fax(p)
            if ok and tmpl.get("bild") and not printer_image_path(p):
                bg(lambda: fetch_printer_image(p, tmpl["bild"]),
                   lambda ok2, new: ok2 and new and p is self.current and self.build_overview())
        bg(lambda: fetch_template(p), done)

    def apply_template(self, p, tmpl):
        p.template = tmpl
        if tmpl.get("farbe") is False:   # laut Vorlage nur schwarzweiss
            self.color.clear()
            self.color.addItem(tr("Schwarzweiß"), "monochrome")
        if tmpl.get("fax") is not None:
            p.fax = bool(tmpl["fax"])
            self.sync_tiles()
        self.sides.setChecked(bool(tmpl.get("beidseitig", True)))
        i = self.media.findData(tmpl.get("papier"))
        if i >= 0:
            self.media.setCurrentIndex(i)
        try:
            self.ov_tmpl_label.setText(tmpl.get("name", "Standard"))
            self.clear(self.ov_hints)
            for h in template_hints(tmpl):
                lab = QtWidgets.QLabel("ℹ  " + h)
                lab.setObjectName("dim")
                lab.setWordWrap(True)
                self.ov_hints.addWidget(lab)
        except (AttributeError, RuntimeError):
            pass

    def check_fax(self, p):
        """Einmal je Drucker pruefen, ob er PC-Fax kann; das Ergebnis wird gemerkt."""
        if p.fax is not None or not re.fullmatch(r"[\d.]+", p.host or ""):
            return

        def done(ok, res):
            if not ok or not self.status_cache.get(printer_key(p), {}).get("markers") and not res:
                return   # Drucker evtl. aus: spaeter nochmal pruefen
            p.fax = bool(res)
            if p in self.printers:
                self.settings.setValue("printers_cache", json.dumps([q.to_dict() for q in self.printers]))
            if p is self.current:
                self.sync_tiles()
        bg(lambda: fax_capable(p.host), done)

    def update_actions(self):
        p = self.current
        self.act_setup.setEnabled(bool(p and not p.queue))
        self.act_test.setEnabled(bool(p and p.queue))
        self.act_remove.setEnabled(bool(p and p.queue))
        self.act_web.setEnabled(bool(p and p.host))
        self.print_btn.setEnabled(bool(p and p.queue))
        self.print_hint.setVisible(bool(p and not p.queue))
        self.nav.item(self.SCAN).setHidden(not self.scanners)
        self.sync_tiles()


    # ----- Status und Fuellstaende -----
    def refresh_status(self, p=None):
        p = p or self.current
        if not p:
            return

        def done(ok, res):
            if not ok:
                res = {"state": "", "reasons": [], "message": tr("Status nicht abrufbar: {0}", res), "markers": [],
                       "supported": {}}
            key = printer_key(p)
            urgent = {reason_base(r) for r in res.get("reasons", []) if reason_base(r) in REASONS_URGENT}
            seen = self.urgent_seen.get(key)
            if seen is not None:   # beim allerersten Abruf nichts melden, das steht ohnehin im Fenster
                for r in sorted(urgent - seen):
                    notify(self.nickname(p) or real_name(p), REASONS_DE.get(r, r))
            self.urgent_seen[key] = urgent
            self.status_cache[key] = res
            if p is self.current:
                self.fill_overview(res)
                self.apply_supported(res.get("supported", {}))
            if p in self.printers:
                i = self.printers.index(p)
                item = self.printer_list.item(i)
                if item:
                    color = STATE_COLORS["off"] if not p.queue else (STATE_COLORS["warn"] if res.get("reasons") else STATE_COLORS["ok"])
                    item.setIcon(dot_icon(color))
        bg(lambda: query_status(p), done)

    @staticmethod
    def set_icon(btn, name, fallback):
        icon = QtGui.QIcon.fromTheme(name)
        if icon.isNull():
            btn.setText(fallback)   # ohne Symbolthema (z.B. andere Desktops) wenigstens ein Zeichen
        else:
            btn.setIcon(icon)

    def leave_scan_ok(self, discard=False):
        """Ungespeicherte Scans: nachfragen. True = weitermachen (gespeichert oder verworfen)."""
        if self.stack.currentIndex() != self.SCAN and not discard:
            return True
        if not self.page_view.count() or self.scan_saved:
            if discard:
                self.clear_pages(ask=False)
            return True
        box = QtWidgets.QMessageBox(self)
        box.setWindowTitle(APP_NAME)
        box.setIcon(QtWidgets.QMessageBox.Question)
        box.setText(tr("{0} gescannte Seite(n) sind noch nicht gespeichert.", self.page_view.count()))
        box.setInformativeText(tr("Willst du sie wirklich verwerfen?"))
        save = box.addButton(tr("Speichern…"), QtWidgets.QMessageBox.AcceptRole)
        drop = box.addButton(tr("Verwerfen"), QtWidgets.QMessageBox.DestructiveRole)
        box.addButton(tr("Abbrechen"), QtWidgets.QMessageBox.RejectRole)
        box.setDefaultButton(save)
        box.exec()
        if box.clickedButton() is save:
            self.save_scan()
            return False
        if box.clickedButton() is drop:
            self.clear_pages(ask=False)
            return True
        return False

    def closeEvent(self, e):
        if self.page_view.count() and not self.scan_saved:
            self.go(self.SCAN)
            if not self.leave_scan_ok(discard=True):
                e.ignore()
                return
        e.accept()

    @staticmethod
    def clear(layout):
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                MainWindow.clear(item.layout())

    def nickname(self, p):
        key = f"nick/{printer_key(p)}"
        name = self.settings.value(key, "")
        if not name:
            # einmalig festlegen, danach nur noch den gespeicherten Namen lesen
            name = real_name(p)
            if p.model:   # ohne Modellangabe noch nicht festschreiben (sonst bliebe „Drucker“ stehen)
                self.settings.setValue(key, name)
        return name

    def open_print(self, photos):
        self.photo_mode = photos
        if photos:
            i = self.media.findData("na_index-4x6_4x6in")
            if i < 0:
                i = self.media.findData("om_small-photo_100x150mm")
            if i >= 0:
                self.media.setCurrentIndex(i)
        self.go(self.PRINT)

    def choose_printer_image(self):
        """Eigenes Bild je Druckertyp (Modell). Liegt nur auf diesem PC, wird nie mit der App verteilt."""
        p = self.current
        if not p:
            return
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, tr("Bild für diesen Druckertyp"), os.path.expanduser("~"),
                                                        tr("Bilder (*.png *.jpg *.jpeg *.webp *.bmp)"))
        if not path:
            return
        target = printer_image_target(p)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        Image.open(path).convert("RGBA").save(target)
        self.build_overview()
        self.status.showMessage(tr("Bild gespeichert – gilt für alle Drucker dieses Typs."))

    def rename(self):
        p = self.current
        if not p:
            return
        name, ok = QtWidgets.QInputDialog.getText(self, tr("Drucker umbenennen"),
                                                  tr("Name für diesen Drucker (leer lassen = Gerätename):"),
                                                  text=self.nickname(p))
        if ok:
            self.settings.setValue(f"nick/{printer_key(p)}", name.strip() or real_name(p))
            self.build_overview()
            self.fill_printer_list()

    def run_wizard(self):
        wiz = SetupWizard(self)
        wiz.setStyleSheet(make_qss())
        wiz.exec()
        self.settings.setValue("setup_done", True)
        self.search()

    def top_parent(self):
        """Elternfenster fuer Rueckfragen: der gerade offene Dialog, sonst das Hauptfenster."""
        return QtWidgets.QApplication.activeModalWidget() or self

    def manual_update(self):
        if self.update_tag:
            info = QtWidgets.QApplication.activeModalWidget()
            if info is not None and info is not self:
                info.accept()
            QtCore.QTimer.singleShot(0, self.update_clicked)
            return
        self.status.showMessage(tr("Suche nach Updates…"))
        self.check_update(manual=True)

    def check_update(self, manual=False):
        def done(ok, tag):
            if manual and not (ok and tag and ver_tuple(tag) > ver_tuple(APP_VERSION)):
                msg = tr("v{0} ist aktuell.", APP_VERSION) if ok else tr("Update-Prüfung fehlgeschlagen: {0}", tag)
                self.status.showMessage(msg)
                if getattr(self, "info_upd_label", None) is not None:
                    self.info_upd_label.setText(msg)
            if ok and tag and ver_tuple(tag) > ver_tuple(APP_VERSION):
                self.update_tag = tag
                self.update_btn.setText(tr("⬆ Update {0}", tag))
                self.update_btn.show()
                self.status.showMessage(tr("Update verfügbar: {0} (installiert: v{1})", tag, APP_VERSION))
                if manual:
                    info = QtWidgets.QApplication.activeModalWidget()
                    if info is not None and info is not self:
                        info.accept()   # Info-Fenster schliessen, damit die Frage nicht dahinter landet
                    QtCore.QTimer.singleShot(0, self.update_clicked)
        bg(latest_release, done)

    def update_clicked(self):
        if not self.update_tag:
            return
        if QtWidgets.QMessageBox.question(self.top_parent(), APP_NAME, tr("Auf {0} aktualisieren?\n\nDas Programm startet danach neu.", self.update_tag)) != QtWidgets.QMessageBox.Yes:
            return
        self.update_btn.setEnabled(False)
        self.update_btn.setText(tr("Lade Update…"))

        def done(ok, res):
            if not ok:
                self.update_btn.setEnabled(True)
                self.update_btn.setText(tr("⬆ Update {0}", self.update_tag))
                QtWidgets.QMessageBox.warning(self.top_parent(), APP_NAME, tr("Update fehlgeschlagen: {0}", res))
                return
            if res == "setup":
                QtWidgets.QApplication.quit()   # das Setup ersetzt die Programmdatei und startet sie neu
            else:
                restart_self()
        bg(lambda: install_update(self.update_tag), done)

    def check_dependencies(self):
        if WINDOWS:
            return   # die Windows-Fassung bringt alles mit
        missing = []
        if cups is None:
            missing.append("python-pycups")
        if Image is None:
            missing.append("python-pillow")
        if not shutil.which("scanimage"):
            missing.append("sane")
        if not os.path.exists("/usr/lib/sane/libsane-airscan.so.1") and not os.path.exists("/usr/lib64/sane/libsane-airscan.so.1"):
            missing.append("sane-airscan")
        if not shutil.which("ipp-usb"):
            missing.append("ipp-usb")
        if not missing:
            return
        bar = QtWidgets.QFrame()
        bar.setObjectName("group")
        lay = QtWidgets.QHBoxLayout(bar)
        lab = QtWidgets.QLabel(tr("Es fehlen Pakete: ") + ", ".join(missing))
        lay.addWidget(lab, 1)
        if shutil.which("pacman") and shutil.which("pkexec"):
            btn = QtWidgets.QPushButton(tr("Jetzt installieren"))
            btn.setObjectName("primary")
            btn.clicked.connect(lambda: self.install_packages(missing, bar))
            lay.addWidget(btn)
        self.banner.addWidget(bar)

    def install_packages(self, pkgs, bar):
        self.status.showMessage(tr("Installiere ") + " ".join(pkgs) + tr(" …"))

        def work():
            rc, out, err = run(["pkexec", "pacman", "-S", "--needed", "--noconfirm"] + pkgs, 900)
            if rc != 0:
                raise RuntimeError((err or out).strip().splitlines()[-1] if (err or out).strip() else "abgebrochen")

        def done(ok, res):
            if ok:
                QtWidgets.QMessageBox.information(self.top_parent(), APP_NAME, tr("Installiert. Bitte das Programm neu starten."))
                bar.hide()
            else:
                QtWidgets.QMessageBox.warning(self.top_parent(), APP_NAME, tr("Installation fehlgeschlagen: {0}", res))
        bg(work, done)

    # ----- Drucken -----
    def build_print_tab(self):
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        self.print_hint = QtWidgets.QLabel(tr("Zum Drucken den Drucker erst einrichten (oben „Einrichten“)."))
        self.print_hint.setStyleSheet("color: #d97706;")
        lay.addWidget(self.print_hint)
        self.print_files = QtWidgets.QListWidget()
        lay.addWidget(self.print_files, 1)
        row = QtWidgets.QHBoxLayout()
        add = QtWidgets.QPushButton(QtGui.QIcon.fromTheme("document-open"), tr("Dateien hinzufügen…"))
        add.clicked.connect(self.add_print_files)
        rem = QtWidgets.QPushButton(tr("Liste leeren"))
        rem.clicked.connect(self.print_files.clear)
        row.addWidget(add)
        row.addWidget(rem)
        row.addStretch(1)
        lay.addLayout(row)
        form = QtWidgets.QFormLayout()
        self.copies = QtWidgets.QSpinBox()
        self.copies.setRange(1, 99)
        self.pages_edit = QtWidgets.QLineEdit()
        self.pages_edit.setPlaceholderText(tr("alle, oder z. B. 1-3,5"))
        self.sides = QtWidgets.QCheckBox(tr("Beidseitig drucken"))
        self.sides.setChecked(True)
        self.color = QtWidgets.QComboBox()
        self.media = QtWidgets.QComboBox()
        self.quality = QtWidgets.QComboBox()
        self.fit = QtWidgets.QCheckBox(tr("Auf Seite einpassen (Bilder)"))
        self.fit.setChecked(True)
        form.addRow(tr("Kopien"), self.copies)
        form.addRow(tr("Seiten"), self.pages_edit)
        form.addRow("", self.sides)
        form.addRow(tr("Farbe"), self.color)
        form.addRow(tr("Papier"), self.media)
        form.addRow(tr("Qualität"), self.quality)
        form.addRow("", self.fit)
        lay.addLayout(form)
        self.apply_supported({})
        self.print_btn = QtWidgets.QPushButton(QtGui.QIcon.fromTheme("document-print"), tr("Drucken"))
        self.print_btn.setMinimumHeight(36)
        self.print_btn.setObjectName("primary")
        self.print_btn.clicked.connect(self.do_print)
        lay.addWidget(self.print_btn)
        return w

    def apply_supported(self, sup):
        def fill(combo, items, current=None):
            keep = combo.currentData()
            combo.clear()
            for label, val in items:
                combo.addItem(label, val)
            i = combo.findData(keep if keep is not None else current)
            combo.setCurrentIndex(max(0, i))
        sides = sup.get("sides-supported") or ["one-sided", "two-sided-long-edge", "two-sided-short-edge"]
        # Haken nur zeigen, wenn der Drucker beidseitig kann (umblaettern wie ein Buch)
        self.sides.setVisible("two-sided-long-edge" in sides)
        modes = sup.get("print-color-mode-supported") or ["color", "monochrome"]
        if (getattr(self.current, "template", None) or {}).get("farbe") is False:
            modes = ["monochrome"]
        fill(self.color, [(tr(lbl), v) for v, lbl in (("color", "Farbe"), ("monochrome", "Schwarzweiß")) if v in modes])
        media = sup.get("media-supported") or ["iso_a4_210x297mm", "iso_a5_148x210mm", "na_letter_8.5x11in", "na_index-4x6_4x6in"]
        named = [(pretty_media(m), m) for m in media if not m.startswith("custom_")]
        named.sort(key=lambda x: x[0][1])
        items, seen = [], set()
        for (label, _), m in named:
            if label not in seen:   # gleich benannte Varianten (z. B. zwei „Foto 10×15“) nur einmal
                seen.add(label)
                items.append((label, m))
        fill(self.media, items, "iso_a4_210x297mm")
        qual = [str(q) for q in (sup.get("print-quality-supported") or [3, 4, 5])]
        fill(self.quality, [(tr(lbl), v) for v, lbl in (("4", "Normal"), ("3", "Entwurf"), ("5", "Hoch")) if v in qual], "4")

    def add_print_files(self):
        files, _ = QtWidgets.QFileDialog.getOpenFileNames(self, tr("Dateien drucken"), os.path.expanduser("~"),
                                                          tr("Druckbar (*.pdf *.jpg *.jpeg *.png *.bmp *.tif *.tiff *.txt *.ps);;Alle Dateien (*)"))
        for f in files:
            self.print_files.addItem(f)

    def do_print(self):
        p = self.current
        files = [self.print_files.item(i).text() for i in range(self.print_files.count())]
        if not p or not p.queue:
            return
        if not files:
            self.status.showMessage(tr("Erst Dateien hinzufügen."))
            return
        opts = {"copies": str(self.copies.value())}
        opts["sides"] = "two-sided-long-edge" if self.sides.isVisible() and self.sides.isChecked() else "one-sided"
        for combo, key in ((self.color, "print-color-mode"), (self.media, "media"),
                           (self.quality, "print-quality")):
            if combo.currentData():
                opts[key] = str(combo.currentData())
        if self.pages_edit.text().strip():
            opts["page-ranges"] = self.pages_edit.text().strip().replace(" ", "")
        if self.fit.isChecked():
            opts["fit-to-page"] = "true"

        def work():
            if WINDOWS:
                return win_print_files(p.queue, files, opts)
            conn = cups.Connection()
            return conn.printFiles(p.queue, files, os.path.basename(files[0]), opts)

        def done(ok, res):
            self.status.showMessage(tr("Druckauftrag {0} gesendet.", res) if ok else tr("Drucken fehlgeschlagen: {0}", res))
            if ok:
                QtCore.QTimer.singleShot(3000, self.refresh_status)
        bg(work, done)

    def test_page(self):
        p = self.current
        if WINDOWS and p and p.queue:   # Windows druckt seine eigene Testseite
            bg(lambda: run(["rundll32", "printui.dll,PrintUIEntry", "/k", "/n", p.queue], 60),
               lambda ok, res: self.status.showMessage(tr("Testseite gesendet.") if ok and res[0] == 0
                                                       else tr("Testseite fehlgeschlagen: {0}", res)))
            return
        test = next((f for f in ("/usr/share/cups/data/testprint", "/usr/share/cups/data/default-testpage.pdf")
                     if os.path.exists(f)), None)
        if not p or not p.queue or not test:
            return
        bg(lambda: cups.Connection().printFile(p.queue, test, "Testseite", {}),
           lambda ok, res: self.status.showMessage(tr("Testseite gesendet.") if ok else tr("Testseite fehlgeschlagen: {0}", res)))

    def setup_current(self):
        p = self.current
        if not p:
            return
        self.status.showMessage(tr("Richte Drucker ein…"))

        def done(ok, res):
            self.status.showMessage(res if ok else tr("Einrichten fehlgeschlagen: {0}", res))
            if ok:
                key = f"nick/{printer_key(p)}"
                if not self.settings.value(key, ""):
                    name, given = QtWidgets.QInputDialog.getText(
                        self, tr("Druckername"), tr("Wie soll der Drucker heißen? (leer lassen = Gerätename)"),
                        text="")
                    self.settings.setValue(key, (name.strip() if given else "") or real_name(p))
                QtCore.QTimer.singleShot(1500, self.search)
        bg(lambda: setup_printer(p), done)

    def remove_current(self):
        p = self.current
        if not p or not p.queue:
            return
        if QtWidgets.QMessageBox.question(self.top_parent(), APP_NAME, tr("Warteschlange „{0}“ entfernen?\nDer Drucker selbst bleibt unverändert.", p.queue)) \
                != QtWidgets.QMessageBox.Yes:
            return
        bg(lambda: remove_queue(p.queue),
           lambda ok, res: (self.status.showMessage("Entfernt." if ok else tr("Entfernen fehlgeschlagen: {0}", res)), ok and self.search()))

    def open_web(self):
        if self.current and self.current.host:
            webbrowser.open(f"http://{self.current.host}")

    # ----- Fax -----
    def build_fax_tab(self):
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        form = QtWidgets.QFormLayout()
        self.fax_number = QtWidgets.QLineEdit()
        self.fax_number.setPlaceholderText(tr("Faxnummer, z. B. 030 1234567"))
        form.addRow(tr("An"), self.fax_number)
        lay.addLayout(form)
        self.fax_files = QtWidgets.QListWidget()
        lay.addWidget(self.fax_files, 1)
        row = QtWidgets.QHBoxLayout()
        add = QtWidgets.QPushButton(tr("Dokumente hinzufügen…"))
        add.clicked.connect(self.add_fax_files)
        take = QtWidgets.QPushButton(tr("Gescannte Seiten übernehmen"))
        take.clicked.connect(self.fax_from_scan)
        clear = QtWidgets.QPushButton(tr("Liste leeren"))
        clear.clicked.connect(lambda: self.fax_files.clear())
        for b in (add, take, clear):
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        self.fax_state = QtWidgets.QLabel(tr("Am Drucker muss eine Telefonleitung angeschlossen sein."))
        self.fax_state.setObjectName("dim")
        self.fax_state.setWordWrap(True)
        lay.addWidget(self.fax_state)
        row = QtWidgets.QHBoxLayout()
        self.fax_cancel_btn = QtWidgets.QPushButton(tr("Abbrechen"))
        self.fax_cancel_btn.hide()
        self.fax_cancel_btn.clicked.connect(lambda: self.fax_cancel.set())
        self.fax_send_btn = QtWidgets.QPushButton(tr("Fax senden"))
        self.fax_send_btn.setObjectName("primary")
        self.fax_send_btn.setMinimumHeight(36)
        self.fax_send_btn.clicked.connect(self.send_fax)
        row.addWidget(self.fax_cancel_btn)
        row.addWidget(self.fax_send_btn, 1)
        lay.addLayout(row)
        self.fax_cancel = threading.Event()
        return w

    def add_fax_files(self):
        files, _ = QtWidgets.QFileDialog.getOpenFileNames(self, tr("Dokumente faxen"), os.path.expanduser("~"),
                                                          tr("Dokumente (*.pdf *.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp)"))
        for f in files:
            self.fax_files.addItem(f)

    def fax_from_scan(self):
        files = [self.page_view.item(i).data(QtCore.Qt.UserRole) for i in range(self.page_view.count())]
        if not files:
            self.status.showMessage(tr("Keine gescannten Seiten."))
            return
        for f in files:
            self.fax_files.addItem(f)

    def send_fax(self):
        p = self.current
        number = re.sub(r"[^0-9+*#]", "", self.fax_number.text())
        files = [self.fax_files.item(i).text() for i in range(self.fax_files.count())]
        if not p or not number or not files:
            self.fax_state.setText(tr("Faxnummer und mindestens ein Dokument angeben."))
            return
        if QtWidgets.QMessageBox.question(self.top_parent(), APP_NAME, tr("{0} Dokument(e) an {1} faxen?", len(files), number)) \
                != QtWidgets.QMessageBox.Yes:
            return
        self.fax_cancel.clear()
        self.fax_send_btn.setEnabled(False)
        self.fax_cancel_btn.show()

        def progress(text):
            ui(lambda: self.fax_state.setText(text))

        def done(ok, res):
            self.fax_send_btn.setEnabled(True)
            self.fax_cancel_btn.hide()
            self.fax_state.setText(res if ok else tr("Fehler: {0}", res))
            self.status.showMessage(res if ok else tr("Fax fehlgeschlagen."))
        bg(lambda: fax_send(p.host, number, files, progress, self.fax_cancel), done)

    # ----- Scannen -----
    def field(self, label, widget):
        """Feld mit kleiner Beschriftung ueber dem Wert."""
        f = QtWidgets.QFrame()
        lay = QtWidgets.QVBoxLayout(f)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        lab = QtWidgets.QLabel(label)
        lab.setObjectName("dim")
        lay.addWidget(lab)
        lay.addWidget(widget)
        return f

    def build_scan_tab(self):
        page = QtWidgets.QWidget()
        page.setObjectName("page")
        outer = QtWidgets.QHBoxLayout(page)
        outer.setContentsMargins(0, 10, 0, 16)
        outer.setSpacing(18)

        # links: Hinweis, Vorschau oder gescannte Seiten
        left = QtWidgets.QVBoxLayout()
        self.scan_area_stack = QtWidgets.QStackedWidget()
        hint = QtWidgets.QLabel(tr("Lege dein Dokument in den Scanner und wähle <b>Scannen</b> oder <a href=\"import\" style=\"color:{0};\">importiere</a> eine Datei.", ACCENT))
        hint.setAlignment(QtCore.Qt.AlignCenter)
        hint.setWordWrap(True)
        hint.setStyleSheet("font-size: 17px;")
        hint.linkActivated.connect(lambda _: self.import_pages())
        hint_box = QtWidgets.QWidget()
        hl = QtWidgets.QVBoxLayout(hint_box)
        hl.addStretch(1)
        hl.addWidget(hint)
        hl.addStretch(1)
        self.scan_area_stack.addWidget(hint_box)
        self.preview_label = ScaledImage()
        self.scan_area_stack.addWidget(self.preview_label)
        pages_box = QtWidgets.QWidget()
        pl = QtWidgets.QVBoxLayout(pages_box)
        pl.setContentsMargins(0, 0, 0, 0)
        # Seiten untereinander in einer schmalen Spalte (mit gedrueckter linker Maustaste verschieben),
        # daneben gross die gewaehlte Seite bzw. die Vorschau – wie bei der Scan-Software unter Windows
        self.md_bar = QtWidgets.QFrame()
        self.md_bar.setObjectName("group")
        mb = QtWidgets.QHBoxLayout(self.md_bar)
        mb.setContentsMargins(12, 6, 12, 6)
        mb.addWidget(QtWidgets.QLabel(tr("Rückseiten falsch einsortiert?")), 1)
        b = QtWidgets.QPushButton(tr("Reihenfolge umkehren"))
        b.clicked.connect(lambda: self.manual_toggle("reverse"))
        mb.addWidget(b)
        b = QtWidgets.QPushButton(tr("Um 180° drehen"))
        b.clicked.connect(lambda: self.manual_toggle("rotate"))
        mb.addWidget(b)
        self.md_bar.hide()
        pl.addWidget(self.md_bar)
        split = QtWidgets.QHBoxLayout()
        split.setSpacing(12)
        self.page_view = QtWidgets.QListWidget()
        self.page_view.setViewMode(QtWidgets.QListView.ListMode)
        self.page_view.setFlow(QtWidgets.QListView.TopToBottom)
        self.page_view.setIconSize(QtCore.QSize(120, 165))
        self.page_view.setSpacing(4)
        self.page_view.setFixedWidth(250)
        self.page_view.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.page_view.setTextElideMode(QtCore.Qt.ElideNone)
        self.page_view.setDragDropMode(QtWidgets.QAbstractItemView.InternalMove)
        self.page_view.setDefaultDropAction(QtCore.Qt.MoveAction)
        self.page_view.setDragEnabled(True)
        self.page_view.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.page_view.model().rowsMoved.connect(lambda *a: self.renumber_pages())
        self.page_view.currentItemChanged.connect(self.show_page)
        split.addWidget(self.page_view)
        self.page_big = ScaledImage()
        self.page_big.setObjectName("group")
        split.addWidget(self.page_big, 1)
        pl.addLayout(split, 1)
        row = QtWidgets.QHBoxLayout()
        more = QtWidgets.QPushButton(tr("+ Seite importieren"))
        more.clicked.connect(self.import_pages)
        delete = QtWidgets.QPushButton(tr("Ausgewählte löschen"))
        delete.clicked.connect(self.delete_pages)
        clear = QtWidgets.QPushButton(tr("Alle löschen"))
        clear.clicked.connect(lambda: self.clear_pages())
        self.save_fmt = QtWidgets.QComboBox()
        for lbl, ext in SAVE_FORMATS:
            self.save_fmt.addItem(lbl, ext)
        save = QtWidgets.QPushButton(tr("Speichern…"))
        save.setObjectName("primary")
        save.clicked.connect(self.save_scan)
        rot_l = QtWidgets.QPushButton("↺")
        rot_l.setToolTip(tr("Ausgewählte Seiten nach links drehen"))
        rot_l.clicked.connect(lambda: self.rotate_pages(90))
        rot_r = QtWidgets.QPushButton("↻")
        rot_r.setToolTip(tr("Ausgewählte Seiten nach rechts drehen"))
        rot_r.clicked.connect(lambda: self.rotate_pages(-90))
        for w in (more, rot_l, rot_r, delete, clear):
            row.addWidget(w)
        row.addStretch(1)
        row.addWidget(self.save_fmt)
        row.addWidget(save)
        pl.addLayout(row)
        self.scan_area_stack.addWidget(pages_box)
        left.addWidget(self.scan_area_stack, 1)
        note = QtWidgets.QLabel(tr("Nimm das Original nach dem Scannen aus dem Gerät – liegt es im Scanner, "
                                "kann jeder im Netzwerk es scannen."))
        note.setObjectName("dim")
        note.setAlignment(QtCore.Qt.AlignCenter)
        note.setWordWrap(True)
        note.setStyleSheet("font-size: 12px;")
        left.addWidget(note)
        outer.addLayout(left, 1)

        # rechts: Einstellungen
        panel = QtWidgets.QFrame()
        panel.setObjectName("group")
        panel.setFixedWidth(280)
        rl = QtWidgets.QVBoxLayout(panel)
        rl.setContentsMargins(18, 20, 18, 18)
        rl.setSpacing(12)
        self.scanner_combo = QtWidgets.QComboBox()
        self.scanner_combo.currentIndexChanged.connect(self.load_scanner_options)
        self.scanner_field = self.field(tr("Scanner"), self.scanner_combo)
        rl.addWidget(self.scanner_field)
        self.scan_source = QtWidgets.QComboBox()
        rl.addWidget(self.field(tr("Quelle"), self.scan_source))
        self.scan_duplex = QtWidgets.QCheckBox(tr("Beidseitig"))
        self.scan_duplex.hide()
        self.scan_duplex.toggled.connect(self.source_changed)
        rl.addWidget(self.scan_duplex)
        # Beidseitig ohne Wenden im Geraet: erst alle Vorderseiten, dann den Stapel umdrehen und die
        # Rueckseiten – das Papier laeuft nur einfach durch, das schont die Einzugsrollen
        self.scan_manual = QtWidgets.QCheckBox(tr("Beidseitig von Hand (Stapel wenden)"))
        self.scan_manual.setToolTip(tr("Erst alle Vorderseiten, dann den Stapel umdrehen und die Rückseiten scannen.\n"
                                    "Schont den Einzug – nichts wird im Gerät gewendet."))
        self.scan_manual.hide()
        rl.addWidget(self.scan_manual)
        self.scan_manual.toggled.connect(lambda on: on and self.scan_duplex.setChecked(False))
        self.scan_duplex.toggled.connect(lambda on: on and self.scan_manual.setChecked(False))
        self.scan_source.currentIndexChanged.connect(self.source_changed)
        self.scan_crop = QtWidgets.QCheckBox(tr("Kanten erkennen"))
        rl.addWidget(self.scan_crop)
        self.scan_preset = QtWidgets.QComboBox()
        for lbl in ("Dokument", "Foto"):
            self.scan_preset.addItem(tr(lbl), lbl)
        self.scan_preset.currentIndexChanged.connect(self.apply_preset)
        rl.addWidget(self.field(tr("Voreinstellungen"), self.scan_preset))
        self.scan_area = QtWidgets.QComboBox()
        for lbl, area in SCAN_AREAS:
            self.scan_area.addItem(lbl, area)
        rl.addWidget(self.field(tr("Scanbereich"), self.scan_area))
        self.scan_mode = QtWidgets.QComboBox()
        rl.addWidget(self.field(tr("Ausgabe"), self.scan_mode))
        self.scan_res = QtWidgets.QComboBox()
        rl.addWidget(self.field(tr("Auflösung"), self.scan_res))
        reset = QtWidgets.QPushButton(tr("Einstellungen zurücksetzen"))
        reset.setFlat(True)
        reset.clicked.connect(self.load_scanner_options)
        rl.addWidget(reset)
        rl.addStretch(1)
        self.adf_alert = QtWidgets.QLabel()
        self.adf_alert.setWordWrap(True)
        self.adf_alert.setStyleSheet(f"color: {STATE_COLORS['err']}; font-weight: 600;")
        self.adf_alert.hide()
        rl.addWidget(self.adf_alert)
        self.preview_btn = QtWidgets.QPushButton(tr("Vorschau"))
        self.preview_btn.setMinimumHeight(34)
        self.preview_btn.clicked.connect(self.do_preview)
        rl.addWidget(self.preview_btn)
        self.scan_btn = QtWidgets.QPushButton(tr("Scannen"))
        self.scan_btn.setObjectName("primary")
        self.scan_btn.setMinimumHeight(34)
        self.scan_btn.clicked.connect(self.do_scan)
        rl.addWidget(self.scan_btn)
        outer.insertWidget(0, panel)   # Einstellungen links, Vorschau rechts
        return page

    def apply_preset(self):
        # Immer Farbe als Standard; Foto nur feiner aufgeloest
        res = "600" if self.scan_preset.currentData() == "Foto" else "300"
        for combo, val in ((self.scan_mode, "Color"), (self.scan_res, res)):
            i = combo.findData(val)
            if i >= 0:
                combo.setCurrentIndex(i)

    def is_feeder(self, src):
        return bool(src) and bool(re.search(r"adf|feeder", src, re.I))

    def source_changed(self, *_):
        feeder = self.is_feeder(self.scan_source.currentData())
        self.scan_duplex.setVisible(feeder and bool(getattr(self, "duplex_value", None)))
        self.scan_manual.setVisible(feeder)
        # Aufloesungen und Scanbereiche nur, soweit die gewaehlte Quelle sie kann
        caps = getattr(self, "scan_caps", {}) or {}
        key = ("adf-duplex" if self.scan_duplex.isChecked() and self.scan_duplex.isVisible() else "adf") if feeder else "platen"
        c = caps.get(key) or caps.get("adf" if feeder else "platen")
        allres = getattr(self, "scan_res_all", None) or [self.scan_res.itemData(i) for i in range(self.scan_res.count())]
        res = [r for r in allres if not c or not c["res"] or int(r) in c["res"]] or allres
        cur = self.scan_res.currentData()
        self.scan_res.blockSignals(True)
        self.scan_res.clear()
        for r in res:
            self.scan_res.addItem(tr("{0} dpi", r), r)
        want = cur if cur in res else max((r for r in res if cur and int(r) <= int(cur)), key=int, default=res[-1] if res else None)
        self.scan_res.setCurrentIndex(max(0, self.scan_res.findData(want)))
        self.scan_res.blockSignals(False)
        area = self.scan_area.currentText()
        self.scan_area.clear()
        for lbl, a in SCAN_AREAS:
            if a is None or not c or (a[0] <= c["w"] + 1 and a[1] <= c["h"] + 1):
                self.scan_area.addItem(lbl, a)
        self.scan_area.setCurrentIndex(max(0, self.scan_area.findText(area)))

    def poll_adf(self):
        """Papier im Einzug -> Vorlageneinzug waehlen, Einzug leer -> Scannerglas (nur bei Aenderung).
        Stau, offene Klappe usw. erscheinen rot ueber den Knoepfen – auch waehrend gescannt wird."""
        if self.stack.currentIndex() != self.SCAN:
            return
        i = self.scanner_combo.currentIndex()
        dev = self.scanner_combo.currentData()
        ip = scanner_ip(dev, self.scanners[i][1] if 0 <= i < len(self.scanners) else "") or \
            (self.current.host if self.current else None)
        if not dev or not ip:
            return

        def done(ok, st):
            if not ok:
                return
            problem = ADF_PROBLEMS.get(st or "")
            if problem != getattr(self, "adf_problem", None):
                self.adf_problem = problem
                self.adf_alert.setText("⚠  " + problem if problem else "")
                self.adf_alert.setVisible(bool(problem))
                if problem:
                    notify(tr("Vorlageneinzug"), problem)
            if problem or st is None or not self.scan_btn.isEnabled():
                return
            loaded = st == "ScannerAdfLoaded"
            if loaded == getattr(self, "adf_state", None):
                return
            self.adf_state = loaded
            want = next((self.scan_source.itemData(j) for j in range(self.scan_source.count())
                         if self.is_feeder(self.scan_source.itemData(j)) == loaded), None)
            if want is not None:
                self.scan_source.setCurrentIndex(self.scan_source.findData(want))
                self.status.showMessage(tr("Papier im Vorlageneinzug erkannt.") if loaded else tr("Vorlageneinzug leer – Scannerglas."))
        bg(lambda: adf_state(ip), done)

    def scan_args(self):
        src = self.scan_source.currentData()
        if self.is_feeder(src) and self.scan_duplex.isChecked() and self.scan_duplex.isVisible() and \
                getattr(self, "duplex_value", None):
            src = self.duplex_value
        return (self.scanner_combo.currentData(), self.scan_mode.currentData(), self.scan_res.currentData(),
                src, self.scan_area.currentData(), self.scan_crop.isChecked())

    def do_preview(self):
        dev, mode, res, src, area, crop = self.scan_args()
        if not dev:
            return
        self.preview_btn.setEnabled(False)
        self.preview_btn.setText(tr("Vorschau läuft…"))

        def done(ok, files):
            self.preview_btn.setEnabled(True)
            self.preview_btn.setText(tr("Vorschau"))
            if not ok:
                self.status.showMessage(tr("Vorschau fehlgeschlagen: {0}", files))
                return
            # gibt es schon Seiten, erscheint die Vorschau gross neben ihnen; sonst allein
            if self.page_view.count():
                self.page_view.setCurrentItem(None)
                self.page_big.set_image(files[0])
            else:
                self.preview_label.set_image(files[0])
                self.scan_area_stack.setCurrentIndex(1)
        # Vorschau immer von der Glasscheibe, niedrige Aufloesung, nicht in die Seiten
        flat = src if not (src and re.search(r"adf|feeder|duplex", src, re.I)) else None
        bg(lambda: scan(dev, mode, "75" if "75" in [self.scan_res.itemData(i) for i in range(self.scan_res.count())]
                        else res, flat, area, crop), done)

    def add_page_files(self, files):
        for f in files:
            self.pages.append(f)
            item = QtWidgets.QListWidgetItem(QtGui.QIcon(QtGui.QPixmap(f).scaled(260, 360, QtCore.Qt.KeepAspectRatio,
                                                                                  QtCore.Qt.SmoothTransformation)),
                                             tr("Seite {0}", self.page_view.count() + 1))
            item.setData(QtCore.Qt.UserRole, f)
            self.page_view.addItem(item)
        if files:
            self.scan_saved = False
            self.page_view.setCurrentRow(self.page_view.count() - 1)   # neueste Seite gross zeigen
            self.page_view.scrollToBottom()
        if self.page_view.count():
            self.scan_area_stack.setCurrentIndex(2)

    def show_page(self, item, _prev=None):
        self.page_big.set_image(item.data(QtCore.Qt.UserRole) if item else None)

    def renumber_pages(self):
        for i in range(self.page_view.count()):
            self.page_view.item(i).setText(tr("Seite {0}", i + 1))

    def import_pages(self):
        files, _ = QtWidgets.QFileDialog.getOpenFileNames(self, tr("Bilder importieren"), os.path.expanduser("~"),
                                                          tr("Bilder (*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp)"))
        self.add_page_files(files)

    def clear_pages(self, ask=True):
        if ask and self.page_view.count() and not self.scan_saved and self.stack.currentIndex() == self.SCAN:
            self.leave_scan_ok(discard=True)
            return
        self.scan_saved = True
        self.page_view.clear()
        self.page_big.set_image(None)
        self.md_bar.hide()
        self.md_last = None
        self.pages.clear()
        self.scan_area_stack.setCurrentIndex(0)

    def refresh_scanners(self):
        # Die Suche (scanimage -L) dauert rund 10 s. Bekannte Scanner aus dem letzten Lauf sofort zeigen,
        # im Hintergrund still nachsehen und nur bei einer Aenderung neu aufbauen.
        try:
            cached = [tuple(x) for x in json.loads(self.settings.value("scanners_cache", "[]") or "[]")]
        except ValueError:
            cached = []
        if cached:
            self.fill_scanners(True, cached)
        else:
            self.scanner_combo.clear()
            self.scanner_combo.addItem(tr("Suche Scanner…"), None)
            self.scanner_combo.setEnabled(False)

        def done(ok, res):
            if ok and res:
                self.settings.setValue("scanners_cache", json.dumps(res))
                if res != self.scanners:
                    self.fill_scanners(True, res)
            elif not cached:
                self.fill_scanners(ok, res)   # nichts gefunden (bei bekanntem Scanner: evtl. nur gerade aus)
        bg(list_scanners, done)

    def fill_scanners(self, ok, res):
        self.scanner_combo.blockSignals(True)
        self.scanner_combo.clear()
        self.scanners = res if ok else []
        if not ok:
            self.scanner_combo.addItem(tr("Scannen nicht möglich: {0}", res), None)
        elif not res:
            self.scanner_combo.addItem(tr("Kein Scanner gefunden"), None)
        for dev, desc in self.scanners:
            kind = "Netzwerk/IPP" if dev.startswith("airscan") else "Treiber"
            short = re.sub(r"^eSCL\s+|\s+ip=.*$", "", desc)   # airscan haengt Protokoll und IPs an
            self.scanner_combo.addItem(f"{short}  ({kind})", dev)
        self.scanner_combo.setEnabled(bool(self.scanners))
        self.scanner_field.setVisible(len(self.scanners) != 1)
        self.scanner_combo.blockSignals(False)
        self.match_scanner()
        self.load_scanner_options()
        self.update_actions()
        self.fill_features()

    def match_scanner(self):
        p = self.current
        if not p or not self.scanners:
            return
        words = [w for w in re.findall(r"[a-z0-9]+", (p.model or p.title).lower()) if w not in ("hp", "series")]
        best = max(range(len(self.scanners)), key=lambda i: sum(w in self.scanners[i][1].lower() or w in self.scanners[i][0].lower()
                                                                 for w in words), default=None)
        if best is not None:
            self.scanner_combo.setCurrentIndex(best)

    def load_scanner_options(self):
        dev = self.scanner_combo.currentData()
        for c in (self.scan_mode, self.scan_res, self.scan_source):
            c.clear()
        self.scan_btn.setEnabled(bool(dev))
        if not dev:
            return

        def done(ok, opts):
            if dev != self.scanner_combo.currentData():
                return
            for c in (self.scan_mode, self.scan_res, self.scan_source):
                c.clear()   # kann zweimal laufen (gemerkt, dann frisch) – nichts doppelt eintragen
            opts = opts if ok else {}
            names = {"Color": tr("Farbe"), "Gray": tr("Graustufen"), "Lineart": tr("Schwarzweiß"), "Flatbed": tr("Scannerglas"),
                     "ADF": tr("Vorlageneinzug")}
            # wie HP Smart: nur Vorlageneinzug und Scannerglas; beidseitig ist ein Haken beim Einzug
            if "source" in opts:
                srcs, cur = opts["source"]
                self.duplex_value = next((x for x in srcs if re.search(r"duplex", x, re.I)), None)
                srcs = [x for x in srcs if not re.search(r"duplex", x, re.I)]
                kind = (getattr(self.current, "template", None) or {}).get("scanner")
                if kind == "glas":   # laut Vorlage kein Einzug
                    srcs = [x for x in srcs if not self.is_feeder(x)] or srcs
                if kind in ("glas", "einzug"):
                    self.duplex_value = None
                srcs.sort(key=lambda x: not re.search(r"adf|feeder", x, re.I))
                opts["source"] = (srcs, cur if cur in srcs else (srcs[0] if srcs else ""))
            for key, combo, fallback in (("mode", self.scan_mode, ["Color", "Gray"]),
                                         ("resolution", self.scan_res, ["150", "300", "600"]),
                                         ("source", self.scan_source, [])):
                choices, cur = opts.get(key, (fallback, fallback[1] if len(fallback) > 1 else ""))
                for c in choices:
                    combo.addItem(tr("{0} dpi", c) if key == "resolution" else names.get(c, c), c)
                i = combo.findData("300" if key == "resolution" and "300" in choices else cur)
                combo.setCurrentIndex(max(0, i))
            self.scan_source.setEnabled(self.scan_source.count() > 1)
            self.scan_res_all = [self.scan_res.itemData(i) for i in range(self.scan_res.count())]
            self.apply_preset()
            self.adf_state = None
            self.source_changed()
            i = self.scanner_combo.currentIndex()
            ip = scanner_ip(dev, self.scanners[i][1] if 0 <= i < len(self.scanners) else "") or \
                (self.current.host if self.current else None)
            if ip:
                bg(lambda: escl_caps(ip), lambda ok2, caps: (setattr(self, "scan_caps", caps if ok2 else {}),
                                                            self.source_changed()))
        key = "scanopts/" + re.sub(r"[^A-Za-z0-9]", "_", dev)
        try:
            cached = json.loads(self.settings.value(key, "") or "null")
        except ValueError:
            cached = None
        if cached:
            done(True, cached)   # sofort aus dem letzten Lauf

        def fresh(ok, opts):
            if not ok or not opts:
                if not cached:
                    done(ok, opts)
                return
            if json.loads(json.dumps(opts)) != cached:
                self.settings.setValue(key, json.dumps(opts))
                done(True, opts)
        bg(lambda: scanner_options(dev), fresh)

    def do_scan(self):
        dev, mode, res, src, area, crop = self.scan_args()
        if not dev:
            return
        manual = self.is_feeder(src) and self.scan_manual.isChecked() and self.scan_manual.isVisible()
        self.scan_btn.setEnabled(False)
        self.scan_btn.setText(tr("Scanne…"))

        def done(ok, files):
            self.scan_btn.setEnabled(True)
            self.scan_btn.setText(tr("Scannen"))
            if not ok:
                problem = getattr(self, "adf_problem", None)
                self.status.showMessage(tr("Scan fehlgeschlagen: {0}", problem or files))
                QtCore.QTimer.singleShot(0, self.poll_adf)   # Grund sofort nachsehen statt erst in 3 s
                return
            self.scan_dpi = res or "300"
            if manual:
                self.manual_backs(dev, mode, res, src, area, crop, files)
                return
            self.add_page_files(files)
            self.status.showMessage(tr("{0} Seite(n) gescannt.", len(files)))
        bg(lambda: scan(dev, mode, res, src, area, crop), done)

    # ----- Beidseitig von Hand -----
    def manual_merge(self, fronts, backs):
        """Vorder- und Rueckseiten verzahnen; Reihenfolge/Drehung wie zuletzt eingestellt."""
        rev = self.settings.value("manual_duplex/reverse", True, type=bool)
        rot = self.settings.value("manual_duplex/rotate", False, type=bool)
        backs = list(reversed(backs)) if rev else list(backs)
        if rot:
            backs = [self.rotated(f) for f in backs]
        out = []
        for i in range(max(len(fronts), len(backs))):
            out += ([fronts[i]] if i < len(fronts) else []) + ([backs[i]] if i < len(backs) else [])
        return out

    @staticmethod
    def rotated_name(f):
        return re.sub(r"(\.\w+)$", r"-180\1", f)

    def rotated(self, f):
        target = self.rotated_name(f)
        if not os.path.exists(target):
            Image.open(f).rotate(180).save(target)
        return target

    def manual_toggle(self, key):
        """Rueckseiten neu einsortieren und die Wahl fuer das naechste Mal merken."""
        last = getattr(self, "md_last", None)
        if not last:
            return
        fronts, backs = last
        k = f"manual_duplex/{key}"
        self.settings.setValue(k, not self.settings.value(k, key == "reverse", type=bool))
        old = set(fronts) | set(backs) | {self.rotated_name(b) for b in backs}
        rows = [i for i in range(self.page_view.count()) if self.page_view.item(i).data(QtCore.Qt.UserRole) in old]
        at = rows[0] if rows else self.page_view.count()
        for i in reversed(rows):
            self.page_view.takeItem(i)
        tail = [self.page_view.takeItem(at).data(QtCore.Qt.UserRole) for _ in range(self.page_view.count() - at)]
        self.add_page_files(self.manual_merge(fronts, backs) + tail)
        self.page_view.setCurrentRow(at + (1 if len(fronts) > 0 and backs else 0))

    def manual_backs(self, dev, mode, res, src, area, crop, fronts):
        box = QtWidgets.QMessageBox(self)
        box.setWindowTitle(tr("Rückseiten scannen"))
        box.setIcon(QtWidgets.QMessageBox.Information)
        box.setText(tr("{0} Vorderseite(n) gescannt.", len(fronts)))
        box.setInformativeText(tr("Nimm den Stapel aus der Ablage, dreh ihn um, ohne ihn neu zu sortieren, "
                               "und leg ihn wieder in den Einzug."))
        go = box.addButton(tr("Rückseiten scannen"), QtWidgets.QMessageBox.AcceptRole)
        box.addButton(tr("Nur Vorderseiten behalten"), QtWidgets.QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is not go:
            self.add_page_files(fronts)
            self.status.showMessage(tr("{0} Seite(n) gescannt.", len(fronts)))
            return
        self.scan_btn.setEnabled(False)
        self.scan_btn.setText(tr("Scanne Rückseiten…"))

        def done(ok, backs):
            self.scan_btn.setEnabled(True)
            self.scan_btn.setText(tr("Scannen"))
            if not ok:
                self.add_page_files(fronts)
                self.status.showMessage(tr("Rückseiten fehlgeschlagen: {0} – Vorderseiten sind übernommen.", backs))
                return
            self.md_last = (fronts, backs)
            self.add_page_files(self.manual_merge(fronts, backs))
            self.md_bar.show()
            msg = tr("{0} Blatt beidseitig gescannt.", len(fronts))
            if len(backs) != len(fronts):
                msg = tr("Achtung: {0} Vorderseiten, aber {1} Rückseiten – bitte prüfen.", len(fronts), len(backs))
            self.status.showMessage(msg)
        bg(lambda: scan(dev, mode, res, src, area, crop), done)

    def rotate_pages(self, angle):
        """Ausgewaehlte Seiten (sonst die angezeigte) um 90° drehen; positiv = nach links."""
        items = self.page_view.selectedItems() or [x for x in [self.page_view.currentItem()] if x]
        for item in items:
            f = item.data(QtCore.Qt.UserRole)
            self._rot_n = getattr(self, "_rot_n", 0) + 1
            # neue Datei statt ueberschreiben: importierte Bilder gehoeren dem Benutzer
            if not getattr(self, "_rot_dir", None):
                self._rot_dir = tempfile.mkdtemp(prefix="dz-gedreht-")   # nur fuer diesen Benutzer lesbar
            target = os.path.join(self._rot_dir, f"seite-{self._rot_n}.png")
            Image.open(f).rotate(angle, expand=True).save(target)
            item.setData(QtCore.Qt.UserRole, target)
            item.setIcon(QtGui.QIcon(QtGui.QPixmap(target).scaled(260, 360, QtCore.Qt.KeepAspectRatio,
                                                                   QtCore.Qt.SmoothTransformation)))
        if items:
            self.scan_saved = False
            self.md_bar.hide()   # Zuordnung Vorder-/Rueckseite gilt nach dem Drehen nicht mehr
            self.md_last = None
            self.show_page(self.page_view.currentItem())

    def delete_pages(self):
        for item in self.page_view.selectedItems():
            self.page_view.takeItem(self.page_view.row(item))
        self.md_bar.hide()   # nach dem Loeschen passt die Zuordnung Vorder-/Rueckseite nicht mehr sicher
        self.md_last = None
        self.renumber_pages()
        self.show_page(self.page_view.currentItem())
        if not self.page_view.count():
            self.scan_area_stack.setCurrentIndex(0)

    def save_scan(self):
        files = [self.page_view.item(i).data(QtCore.Qt.UserRole) for i in range(self.page_view.count())]
        if not files:
            self.status.showMessage(tr("Noch nichts gescannt."))
            return
        if Image is None:
            self.status.showMessage(tr("python-pillow fehlt."))
            return
        ext = self.save_fmt.currentData()
        start = os.path.join(QtCore.QStandardPaths.writableLocation(QtCore.QStandardPaths.DocumentsLocation)
                             or os.path.expanduser("~"), f"Scan.{ext}")
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, tr("Scan speichern"), start, f"{ext.upper()} (*.{ext})")
        if not path:
            return
        if not path.lower().endswith("." + ext):
            path += "." + ext
        def done(ok, res):
            self.status.showMessage(("Gespeichert: " + ", ".join(res)) if ok else tr("Speichern fehlgeschlagen: {0}", res))
            if ok:
                self.scan_saved = True
        bg(lambda: save_pages(files, path, ext, self.scan_dpi), done)

def migrate_old_install():
    """Fruehere Namen („HP Druckzentrale“, „Druckzentrale“): einmalig umziehen – Programm, Menueeintrag,
    Einstellungen, eigene Druckerbilder. Gibt den neuen Programmpfad zurueck, falls umgezogen."""
    new_settings = QtCore.QSettings("printdock", "printdock")
    if not new_settings.allKeys():
        for old in reversed(OLD_NAMES):   # die juengsten Einstellungen zuerst
            old_settings = QtCore.QSettings(old, old)
            if old_settings.allKeys():
                for k in old_settings.allKeys():
                    new_settings.setValue(k, old_settings.value(k))
                new_settings.sync()
                break
    me = os.path.realpath(__file__)
    apps = os.path.dirname(DESKTOP_FILE)
    old_dirs = [os.path.expanduser(f"~/.local/share/{n}") for n in OLD_NAMES]
    old_desktops = [os.path.join(apps, f"{n}.desktop") for n in OLD_NAMES]
    if not (any(os.path.exists(d) for d in old_desktops) or any(me.startswith(d + os.sep) for d in old_dirs)):
        return None
    os.makedirs(INSTALL_DIR, exist_ok=True)
    for d in old_dirs:   # eigene Druckerbilder mitnehmen
        src = os.path.join(d, "bilder")
        if os.path.isdir(src):
            shutil.copytree(src, IMAGE_DIR, dirs_exist_ok=True)
    target = os.path.join(INSTALL_DIR, "printdock.py")
    shutil.copyfile(me, target)
    os.chmod(target, 0o755)
    os.makedirs(apps, exist_ok=True)
    with open(DESKTOP_FILE, "w") as f:
        f.write("[Desktop Entry]\nType=Application\nName=PrintDock\n"
                "Comment=Drucken, Scannen, Fax, Tintenstand und Wartung für Drucker\n"
                f"Exec=python3 {target}\nIcon=printer\nCategories=Office;Graphics;Utility;\n"
                "StartupWMClass=printdock\n")
    for path in old_desktops:
        try:
            os.remove(path)
        except OSError:
            pass
    for d in old_dirs:
        shutil.rmtree(d, ignore_errors=True)
    run(["update-desktop-database", apps], 20)
    return target if target != me else None


def main():
    global _bridge
    moved = None if WINDOWS else migrate_old_install()
    if moved:
        os.execv(sys.executable, [sys.executable, moved] + sys.argv[1:])
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setDesktopFileName("printdock")
    _bridge = Bridge()
    _bridge.call.connect(lambda fn: fn(), QtCore.Qt.QueuedConnection)
    win = MainWindow()
    win.show()
    bg(refresh_languages)   # neue Uebersetzungen fuer das naechste Mal holen
    if os.environ.get("DZ_SELFTEST"):
        if os.environ.get("DZ_PAGE"):
            QtCore.QTimer.singleShot(int(os.environ.get("DZ_SELFTEST_MS", "3000")) - 500,
                                     lambda: win.go(int(os.environ["DZ_PAGE"])))
        QtCore.QTimer.singleShot(int(os.environ.get("DZ_SELFTEST_MS", "3000")),
                                 lambda: (win.grab().save(os.environ["DZ_SELFTEST"]), app.quit()))
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
