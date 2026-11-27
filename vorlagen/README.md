# Druckervorlagen / Printer templates

PrintDock lädt beim Einbinden eines Druckers **nur die Vorlage dieses Modells** und merkt sie sich.
Gibt es keine, gilt die Standard-Vorlage (eingebaut in `printdock.py`, `STANDARD_TEMPLATE`).

**Dateiname:** Gerätename in Kleinbuchstaben, Leerzeichen und Sonderzeichen als `-`,
z. B. „HP Officejet Pro 8620“ → `hp-officejet-pro-8620.json`.

| Feld | Bedeutung | fehlt → |
|---|---|---|
| `name` | Anzeigename der Vorlage | „Standard“ |
| `treiber` | Pakete je Distribution (`arch`, `deb`, `rpm`, `suse`), nur für Drucker ohne treiberloses Drucken; `{}` = keine | freie Treiber (Gutenprint, Foomatic) |
| `treiber_suche` | Suchbegriff für den Treiber | Modellname |
| `papier` | Standardpapier (IPP-Name, z. B. `iso_a4_210x297mm`) | A4 |
| `beidseitig` | standardmäßig beidseitig drucken | `true` |
| `fax` | `true`/`false` legt fest, ob es Fax gibt | beim Drucker nachsehen |
| `wartung` | erlaubte Wartungs- und Berichtsaufträge (Druckkopfreinigung immer) | alles, was der Drucker anbietet |
| `hinweise` | kurze Hinweise, stehen in der Übersicht unter „Gerät“ | keine |
| `treiber_windows` | Windows-Treiber für Drucker ohne IPP, z. B. `Microsoft PS Class Driver` | `Microsoft PCL6 Class Driver` |
| `farbe` | `false` = druckt nur schwarzweiß | beim Drucker nachsehen |
| `scanner` | `keiner`, `glas`, `einzug` oder `einzug-beidseitig` | beim Scanner nachsehen |
| `hinweise_<sprache>` | dieselben Hinweise übersetzt, z. B. `hinweise_en`, `hinweise_fr` (Kürzel wie in `sprachen/`) | Englisch, sonst `hinweise` |
| `bild` | Adresse (https) eines Gerätebilds, z. B. beim Hersteller. Nur der Link steht hier, das Bild lädt jeder PC selbst; ein eigenes Bild hat Vorrang | Druckersymbol |

Eine neue Vorlage ist nach dem Hochladen sofort für alle da – ohne neue App-Version.
Bereits gemerkte Vorlagen liegen unter `~/.local/share/printdock/vorlagen/` und werden einmal am Tag neu geholt.

## Neuer Drucker

Gibt es für ein Modell keine Vorlage, kann man in PrintDock unter *Gerät* den Drucker **melden** (GitHub-Issue mit
Label `neuer-drucker`: Modell, Gerätekennung, Produktnummer, Firmware – keine Seriennummer, keine Adresse) und ihn
bis dahin **selbst beschreiben** (gilt nur auf diesem PC). Wird hier die Vorlage hochgeladen, übernimmt PrintDock sie
beim nächsten Abgleich, löscht die eigene Beschreibung und meldet: „ist jetzt in PrintDock aufgenommen“.
