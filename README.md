**Language / Sprache:** [🇬🇧 English](#printdock) | [🇩🇪 Deutsch](#printdock-1)

---

# PrintDock

Print, scan, fax, check ink or toner and maintain – for **printers on Linux**, in one simple window. Works over **USB, LAN and Wi-Fi** and with printers from any manufacturer that Linux supports. Standalone: no manufacturer software needed – for HP printers, fax, printhead cleaning and printer reports go straight through the printer's built-in interface.

Unofficial and independent – not made by or affiliated with any printer manufacturer. Formerly called *Druckzentrale*. Available in 13 languages.

![Overview](docs/overview.png)

## Privacy

**No ads, no tracking, no location data, no account.** Unlike many manufacturer apps, PrintDock does not ask where you are, shows no advertising, sends no usage statistics and does not need a manufacturer account to print or scan.

What it does connect to – and only for this:

| Where | Why |
|---|---|
| your printers in the local network / USB | printing, scanning, levels, maintenance |
| GitHub (this project) | update check, printer template and language file for *your* printer and language only |
| the picture address in your printer's template (e.g. the manufacturer's image server) | the device picture, downloaded once |
| a PrintDock Server – only if you log in to one | the printers your company or authority has released for you |

Nothing else, and never the content of what you print or scan.

## Installation

Download the installer for your distribution from the [Releases](https://github.com/LucyWolf/printdock/releases/latest) page and double-click it. The first time, your file manager asks whether it may run the file.

| Distribution | Installer |
|---|---|
| Arch / CachyOS / Manjaro | [`PrintDock-arch-installer.desktop`](https://github.com/LucyWolf/printdock/releases/latest/download/PrintDock-arch-installer.desktop) |
| Debian / Ubuntu | [`PrintDock-deb-installer.desktop`](https://github.com/LucyWolf/printdock/releases/latest/download/PrintDock-deb-installer.desktop) |
| Everything else (Fedora, Bazzite, openSUSE, …) – on Bazzite/Silverblue restart once afterwards | [`PrintDock-installer.desktop`](https://github.com/LucyWolf/printdock/releases/latest/download/PrintDock-installer.desktop) |
| **Windows 10/11** (network printers; new, not yet tried on real hardware) | [`PrintDock-setup.exe`](https://github.com/LucyWolf/printdock/releases/latest/download/PrintDock-setup.exe) |

The installer sets up everything with a single password prompt: Qt (PySide6, native Wayland), CUPS, Poppler (PDF for fax), SANE with sane-airscan, ipp-usb and Avahi. Printer drivers are only installed when a printer actually needs one (see *Printer templates*). It turns on the printing service and network discovery, installs the app and adds a menu entry. Running it again offers **Update** or **Uninstall**.

<details>
<summary>Prefer the terminal?</summary>

```bash
curl -fsSL -o PrintDock-installieren.sh https://github.com/LucyWolf/printdock/releases/latest/download/PrintDock-installieren.sh
bash PrintDock-installieren.sh
```
</details>

### Updates

Click **Version · Info** at the bottom left, then **Check for updates**. If a new version exists, a button also appears at the bottom left on its own. Installations of the former *Druckzentrale* or *HP Druckzentrale* move themselves over on the first start (program, menu entry, settings).

## Getting started

On the first start a wizard guides you: switch on the printer, connect it by USB or to the same network, **search**, **set up** (one password prompt) and give it a name – leave it empty to use the device name. A test page can be printed right away. More printers can be added later with **Add** in the sidebar.

## Using it

The sidebar lists your printers; the dot shows the state (green ready, orange message, grey not set up). The **overview** shows status, messages and ink or toner. The tiles lead to the functions, **← Overview** goes back. *Scan* and *Fax* only appear if the printer has them.

- **Print:** several files at once; copies, pages, color or black and white, paper size (only what the printer offers, e.g. A4, photo 10×15, envelopes, borderless), quality. *Print double-sided* is ticked by default if the printer can do it.
- **Scan:** source *document feeder* or *scanner glass* – the app notices paper in the feeder and switches by itself. Color by default; *Document* scans at 300 dpi, *Photo* at 600 dpi. Resolution and scan area only offer what the chosen source supports. Preview, edge detection, import of existing images, reorder pages; save as **PDF** (multi-page), **JPG, PNG, BMP, TIFF** or **WEBP**. Unsaved scans are not lost by accident – the app asks first.
- **Fax** (HP printers with PC fax, e.g. OfficeJet Pro): number, documents (PDF, images) or scanned pages, *Send*; the app shows dialing, connecting and sending and can cancel. A phone line must be connected to the printer.
- **Maintenance:** print jobs (view, cancel), test page, printer web interface, rename the printer, choose a picture for the printer type (stays on this PC), setup wizard, remove the printer. For HP printers additionally:
  - **Clean printhead** – starts with level 1; when the printer is done the app asks whether the print looks fine and only then goes to the next, more thorough level
  - print quality diagnostics, line feed calibration
  - reports: printer status, diagnostics, network/Wi-Fi, usage

![Scan](docs/scan.png)

## Printer templates

When a printer is added, PrintDock downloads **only the template for that model** from [`vorlagen/`](vorlagen/) and remembers it. It knows whether a driver is needed, which maintenance and fax functions exist, default paper and quirks. Without a template the standard applies: everything is asked from the printer itself, and only printers without driverless printing get the free drivers (Gutenprint, Foomatic). New templates are available to everyone as soon as they are uploaded.

## Languages

PrintDock speaks German, English, French, Spanish, Italian, Portuguese, Dutch, Polish, Turkish, Russian, Ukrainian, Chinese and Japanese. The installer detects the system language and offers the list once; it can be changed at any time under *Info*. Only the chosen language is downloaded. The translations are machine-made – corrections are welcome in `sprachen/<code>.json`; `tools/sprachen_pruefen.py` checks them.

## Tested printers

- HP OfficeJet Pro 8620
- HP Color Laser MFP 178nwg (scanning not yet tried)

Other printers should work through the standards (IPP Everywhere/AirPrint for printing, eSCL for scanning) but have not been tried yet. Older printers without these standards need a driver; PrintDock installs the free ones when needed, others are only available from the manufacturer. Printhead cleaning and reports are available for HP printers with a built-in web interface. Fax works with HP printers that offer PC fax through their built-in interface.

## Running from source

```bash
python3 printdock.py
```

Needs PySide6, pycups and Pillow; the installer pulls in everything else.

**Releases:** raise `APP_VERSION` in `printdock.py` (the last digit counts up to 99) and push to `main` – also works in the GitHub web editor. A workflow checks the code and the installer script and publishes the release with the program and all installers. Without a new version number nothing is released.

License: MIT, see [LICENSE](LICENSE).

---

# PrintDock

Drucken, Scannen, Faxen, Tinte oder Toner und Wartung – für **Drucker unter Linux**, in einem einfachen Fenster. Funktioniert über **USB, LAN und WLAN** und mit Druckern jedes Herstellers, den Linux unterstützt. Eigenständig: keine Herstellersoftware nötig – bei HP-Druckern laufen Fax, Druckkopfreinigung und Berichte direkt über die eingebaute Schnittstelle des Druckers.

Inoffiziell und unabhängig – nicht von einem Druckerhersteller und nicht mit einem verbunden. Früher hieß es *Druckzentrale*.

![Übersicht](docs/overview.png)

## Datenschutz

**Keine Werbung, kein Tracking, keine Positionsdaten, kein Konto.** Anders als viele Hersteller-Apps fragt PrintDock nicht nach deinem Standort, zeigt keine Werbung, schickt keine Nutzungsstatistiken und braucht kein Herstellerkonto zum Drucken oder Scannen.

Womit es sich verbindet – und nur dafür:

| Wohin | Wozu |
|---|---|
| deine Drucker im eigenen Netz / per USB | Drucken, Scannen, Füllstände, Wartung |
| GitHub (dieses Projekt) | Update-Prüfung, Druckervorlage und Sprachdatei nur für *deinen* Drucker und *deine* Sprache |
| die Bildadresse aus der Vorlage deines Druckers (z. B. Bildserver des Herstellers) | das Gerätebild, einmal geladen |
| ein PrintDock-Server – nur wenn du dich dort anmeldest | die Drucker, die deine Firma oder dein Amt für dich freigegeben hat |

Sonst nichts, und nie der Inhalt dessen, was du druckst oder scannst.

## Installation

Den Installer für deine Distribution von der [Releases](https://github.com/LucyWolf/printdock/releases/latest)-Seite herunterladen und doppelklicken. Beim ersten Mal fragt der Dateimanager, ob er die Datei ausführen darf.

| Distribution | Installer |
|---|---|
| Arch / CachyOS / Manjaro | [`PrintDock-arch-installer.desktop`](https://github.com/LucyWolf/printdock/releases/latest/download/PrintDock-arch-installer.desktop) |
| Debian / Ubuntu | [`PrintDock-deb-installer.desktop`](https://github.com/LucyWolf/printdock/releases/latest/download/PrintDock-deb-installer.desktop) |
| Alle anderen (Fedora, Bazzite, openSUSE, …) – bei Bazzite/Silverblue danach einmal neu starten | [`PrintDock-installer.desktop`](https://github.com/LucyWolf/printdock/releases/latest/download/PrintDock-installer.desktop) |
| **Windows 10/11** (Netzwerkdrucker; neu, an echter Hardware noch nicht ausprobiert) | [`PrintDock-setup.exe`](https://github.com/LucyWolf/printdock/releases/latest/download/PrintDock-setup.exe) |

Der Installer richtet alles mit einer einzigen Passwortabfrage ein: Qt (PySide6, nativ unter Wayland), CUPS, Poppler (PDF fürs Fax), SANE mit sane-airscan, ipp-usb und Avahi. Druckertreiber kommen nur dazu, wenn ein Drucker wirklich einen braucht (siehe *Druckervorlagen*). Er schaltet Druckdienst und Netzwerksuche ein, installiert die App und legt einen Menüeintrag an. Erneut gestartet bietet er **Aktualisieren** oder **Deinstallieren** an.

<details>
<summary>Lieber per Terminal?</summary>

```bash
curl -fsSL -o PrintDock-installieren.sh https://github.com/LucyWolf/printdock/releases/latest/download/PrintDock-installieren.sh
bash PrintDock-installieren.sh
```
</details>

### Updates

Links unten auf **Version · Info** klicken, dann **Nach Updates suchen**. Gibt es eine neue Version, erscheint links unten auch von selbst ein Knopf dafür. Installationen der früheren *Druckzentrale* bzw. *HP Druckzentrale* ziehen beim ersten Start selbst um (Programm, Menüeintrag, Einstellungen).

## Erste Schritte

Beim ersten Start führt ein Assistent durch: Drucker einschalten, per USB oder ins selbe Netz bringen, **suchen**, **einrichten** (eine Passwortabfrage) und einen Namen geben – leer lassen nimmt den Gerätenamen. Danach lässt sich gleich eine Testseite drucken. Weitere Drucker kommen später über **Hinzufügen** in der Seitenleiste dazu.

## Bedienung

Die Seitenleiste zeigt deine Drucker; der Punkt zeigt den Zustand (grün bereit, orange Meldung, grau nicht eingerichtet). Die **Übersicht** zeigt Status, Meldungen und Tinte oder Toner. Die Kacheln führen zu den Funktionen, **← Übersicht** zurück. *Scannen* und *Fax* erscheinen nur, wenn der Drucker sie hat.

- **Drucken:** mehrere Dateien auf einmal; Kopien, Seiten, Farbe oder Schwarzweiß, Papierformat (nur was der Drucker anbietet, z. B. A4, Foto 10×15, Umschläge, randlos), Qualität. *Beidseitig drucken* ist angehakt, wenn der Drucker es kann.
- **Scannen:** Quelle *Vorlageneinzug* oder *Scannerglas* – die App merkt, wenn Papier im Einzug liegt, und schaltet selbst um. Standard ist Farbe; *Dokument* scannt mit 300 dpi, *Foto* mit 600 dpi. Auflösung und Scanbereich bieten nur an, was die gewählte Quelle kann. Vorschau, Kanten erkennen, vorhandene Bilder importieren, Seiten sortieren; speichern als **PDF** (mehrseitig), **JPG, PNG, BMP, TIFF** oder **WEBP**. Ungespeicherte Scans gehen nicht versehentlich verloren – die App fragt vorher.
- **Fax** (HP-Drucker mit PC-Fax, z. B. OfficeJet Pro): Nummer, Dokumente (PDF, Bilder) oder gescannte Seiten, *Senden*; die App zeigt Wählen, Verbinden und Senden an und kann abbrechen. Am Drucker muss eine Telefonleitung angeschlossen sein.
- **Wartung:** Druckaufträge (ansehen, abbrechen), Testseite, Weboberfläche des Druckers, Drucker umbenennen, Bild für den Druckertyp wählen (bleibt auf diesem PC), Einrichtungs-Assistent, Drucker entfernen. Bei HP-Druckern zusätzlich:
  - **Druckkopf reinigen** – beginnt mit Stufe 1; ist der Drucker fertig, fragt die App, ob das Druckbild in Ordnung ist, und geht erst dann zur nächsten, gründlicheren Stufe
  - Druckqualitäts-Diagnose, Zeilenvorschub kalibrieren
  - Berichte: Druckerstatus, Diagnose, Netzwerk/WLAN, Nutzung

![Scannen](docs/scan.png)

## Druckervorlagen

Beim Einbinden lädt PrintDock **nur die Vorlage dieses Modells** aus [`vorlagen/`](vorlagen/) und merkt sie sich. Darin steht, ob ein Treiber nötig ist, welche Wartung und ob Fax es gibt, das Standardpapier und Besonderheiten. Ohne Vorlage gilt der Standard: alles wird beim Drucker selbst abgefragt, und nur Drucker ohne treiberloses Drucken bekommen die freien Treiber (Gutenprint, Foomatic). Neue Vorlagen sind nach dem Hochladen sofort für alle da.

## Sprachen

PrintDock gibt es auf Deutsch, Englisch, Französisch, Spanisch, Italienisch, Portugiesisch, Niederländisch, Polnisch, Türkisch, Russisch, Ukrainisch, Chinesisch und Japanisch. Der Installer erkennt die Systemsprache und bietet die Liste einmal zur Auswahl an; umstellen lässt sie sich jederzeit unter *Info*. Geladen wird nur die gewählte Sprache. Die Übersetzungen sind maschinell – Verbesserungen gern in `sprachen/<kürzel>.json`; `tools/sprachen_pruefen.py` prüft sie.

## Getestete Drucker

- HP OfficeJet Pro 8620
- HP Color Laser MFP 178nwg (Scannen noch nicht ausprobiert)

Andere Drucker sollten über die Standards (IPP Everywhere/AirPrint zum Drucken, eSCL zum Scannen) funktionieren, sind aber noch nicht ausprobiert. Ältere Drucker ohne diese Standards brauchen einen Treiber; die freien installiert PrintDock bei Bedarf, andere gibt es nur beim Hersteller. Druckkopfreinigung und Berichte gibt es bei HP-Druckern mit eingebauter Weboberfläche. Fax geht bei HP-Druckern, die PC-Fax über ihre eingebaute Schnittstelle anbieten.

## Aus dem Quellcode starten

```bash
python3 printdock.py
```

Braucht PySide6, pycups und Pillow; alles andere holt der Installer.

**Releases:** `APP_VERSION` in `printdock.py` erhöhen (die letzte Stelle zählt bis 99) und auf `main` hochladen – geht auch direkt im GitHub-Editor. Ein Workflow prüft Programm und Installationsskript und veröffentlicht das Release mit Programm und allen Installern. Ohne neue Versionsnummer wird nichts veröffentlicht.

Lizenz: MIT, siehe [LICENSE](LICENSE).
