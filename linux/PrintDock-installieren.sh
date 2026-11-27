#!/usr/bin/env bash
# PrintDock (früher Druckzentrale) — Linux-Installer
# Per Doppelklick (ueber PrintDock-*-installer.desktop) oder im Terminal.
# Installiert alles, was die App braucht, mit einer einzigen Passwortabfrage:
#   Pakete (Qt mit Wayland-Modul, CUPS, SANE + sane-airscan, ipp-usb, Avahi). Druckertreiber holt PrintDock
#   erst, wenn ein Drucker sie braucht (laut seiner Vorlage),
#   Druck- und Netzwerkdienste,
#   die App selbst nach ~/.local/share und einen Menueeintrag.
# Ist sie schon installiert, fragt das Skript: aktualisieren oder deinstallieren.
set -euo pipefail

TITLE="PrintDock"
INSTALL_DIR="$HOME/.local/share/printdock"
OLD_INSTALL_DIRS="$HOME/.local/share/hp-druckzentrale $HOME/.local/share/druckzentrale"
DESKTOP_FILE="$HOME/.local/share/applications/printdock.desktop"
OLD_DESKTOP_FILES="$HOME/.local/share/applications/hp-druckzentrale.desktop $HOME/.local/share/applications/druckzentrale.desktop"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$PWD/x}")" && pwd)"
RELEASE_URL="https://github.com/LucyWolf/printdock/releases/latest/download"

GUI=0
if command -v kdialog >/dev/null 2>&1 && [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]; then
    GUI=1
elif command -v zenity >/dev/null 2>&1 && [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]; then
    GUI=2
fi

# Ohne kdialog/zenity (z. B. frisch installiertes System) gaebe es weder Fenster noch Passwortabfrage:
# dann sich selbst in einem Terminal oeffnen, dort ist alles sichtbar.
open_in_terminal() {
    SELF="$(readlink -f "$0")"
    export IN_TERMINAL=1
    for t in konsole gnome-terminal kgx ptyxis xfce4-terminal alacritty kitty foot wezterm xterm; do
        command -v "$t" >/dev/null 2>&1 || continue
        case "$t" in
            gnome-terminal|kgx|ptyxis) exec "$t" -- bash "$SELF" ;;
            xfce4-terminal) exec "$t" -x bash "$SELF" ;;
            kitty|foot) exec "$t" bash "$SELF" ;;
            wezterm) exec "$t" start -- bash "$SELF" ;;
            *) exec "$t" -e bash "$SELF" ;;
        esac
    done
}
if [ "$GUI" = "0" ] && [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ] && [ ! -t 0 ] && [ -z "${IN_TERMINAL:-}" ]; then
    open_in_terminal
fi
# Texte in der gewaehlten Sprache: dieselbe Sprachdatei wie die App (sprachen/<kuerzel>.json, Schluessel = deutscher
# Text). Ohne Datei oder ohne python3 bleibt es deutsch. {0}, {1} … werden mit den weiteren Argumenten gefuellt.
LANGJSON=""
T() {
    local key="$1" out="" i=0 a; shift
    if [ -n "$LANGJSON" ] && [ -f "$LANGJSON" ] && command -v python3 >/dev/null 2>&1; then
        out=$(python3 -c 'import json, sys
d = json.load(open(sys.argv[1], encoding="utf-8")); t = d.get(sys.argv[2]) or sys.argv[2]
print(t.format(*sys.argv[3:]), end="")' "$LANGJSON" "$key" "$@" 2>/dev/null) || out=""
    fi
    if [ -z "$out" ]; then
        out="$key"
        for a in "$@"; do out="${out//"{$i}"/"$a"}"; i=$((i + 1)); done
    fi
    printf '%s' "$out"
}
pause_in_terminal() { [ -n "${IN_TERMINAL:-}" ] && [ -t 0 ] && read -rp "$(T "Enter zum Schließen ")" _ || true; }

info() {
    case "$GUI" in
        1) kdialog --title "$TITLE" --msgbox "$(printf '%b' "$1")" ;;
        2) zenity --info --title="$TITLE" --text="$1" --width=380 ;;
        *) printf '%b\n' "$1" ;;
    esac
}
fail() {
    trap - ERR
    case "$GUI" in
        1) kdialog --title "$TITLE" --error "$(printf '%b' "$1")" ;;
        2) zenity --error --title="$TITLE" --text="$1" --width=380 ;;
        *) printf '%s: %b\n' "$(T "FEHLER")" "$1" >&2 ;;
    esac
    pause_in_terminal
    exit 1
}
note() {
    case "$GUI" in
        1) kdialog --title "$TITLE" --passivepopup "$1" 8 & ;;
        2) zenity --notification --text="$TITLE: $1" & ;;
        *) echo "$1" ;;
    esac
}
# Protokoll: jeder Schritt landet hier, damit ein Abbruch nachvollziehbar ist
LOG="$HOME/.cache/printdock-installer.log"
mkdir -p "$(dirname "$LOG")"
{ echo; echo "=== $(date) – $0 – GUI=$GUI – Terminal: $([ -t 0 ] && echo ja || echo nein)"; } >> "$LOG"
exec {LOGFD}>>"$LOG"
BASH_XTRACEFD=$LOGFD
set -x -E   # -E: Abbruchmeldung auch bei Fehlern in Funktionen
# Bricht ein Befehl unerwartet ab, nicht still verschwinden, sondern melden
# (nur im Hauptskript melden, nicht zusaetzlich aus $(...)-Unterprozessen – sonst kaeme die Meldung doppelt)
trap 'if [ "$BASH_SUBSHELL" = 0 ]; then fail "$(T "Der Installer ist unerwartet abgebrochen (Zeile {0}).\n\nProtokoll: {1}" "$LINENO" "$LOG")"; fi' ERR

as_root() {
    # im Terminal sudo (Passwort dort eingeben), sonst das Passwortfenster des Systems
    if [ ! -t 0 ] && command -v pkexec >/dev/null 2>&1; then
        pkexec /bin/sh -c "$1"
    else
        sudo /bin/sh -c "$1"
    fi
}

uninstall() {
    local msg
    msg="$(T "PrintDock wurde entfernt.\n\nDie Pakete (CUPS, SANE …) und eingerichtete Drucker bleiben erhalten,\nandere Programme nutzen sie auch.")"
    rm -rf "$INSTALL_DIR" $OLD_INSTALL_DIRS
    rm -f "$DESKTOP_FILE" $OLD_DESKTOP_FILES
    command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$HOME/.local/share/applications" || true
    info "$msg"
    pause_in_terminal
    exit 0
}

# 0) Sprache: erkannt wird die Systemsprache (oder die schon gewaehlte), dann einmal zur Auswahl anbieten.
# Die Wahl gilt fuer den Installer und die App (~/.local/share/printdock/sprache, die App liest sie beim Start).
LANG_FILE="$INSTALL_DIR/sprache"
LANG_CODES="de en fr es it pt nl pl tr ru uk zh ja"
lang_name() {
    case "$1" in de) echo Deutsch ;; en) echo English ;; fr) echo Français ;; es) echo Español ;;
        it) echo Italiano ;; pt) echo Português ;; nl) echo Nederlands ;; pl) echo Polski ;; tr) echo Türkçe ;;
        ru) echo Русский ;; uk) echo Українська ;; zh) echo 中文 ;; ja) echo 日本語 ;; esac
}
IL=""
if [ -f "$LANG_FILE" ]; then IL="$(head -c 8 "$LANG_FILE" | tr -dc 'a-z')"; fi
case " $LANG_CODES " in *" $IL "*) ;; *) IL="" ;; esac
if [ -z "$IL" ]; then
    for v in "${LANGUAGE:-}" "${LC_ALL:-}" "${LC_MESSAGES:-}" "${LANG:-}"; do
        c="${v%%:*}"; c="${c:0:2}"; c="${c,,}"
        [ -n "$c" ] || continue
        case " $LANG_CODES " in *" $c "*) IL="$c" ;; *) [ "$c" = "c" ] || [ "$c" = "po" ] || IL="en" ;; esac
        [ -n "$IL" ] && break
    done
fi
[ -n "$IL" ] || IL="en"
CHOSEN=""
case "$GUI" in
    1) ARGS=()
       for c in $LANG_CODES; do ARGS+=("$c" "$(lang_name "$c")" "$([ "$c" = "$IL" ] && echo on || echo off)"); done
       CHOSEN="$(kdialog --title "$TITLE" --radiolist "Sprache / Language" "${ARGS[@]}" 2>/dev/null)" || CHOSEN="" ;;
    2) ARGS=()
       for c in $LANG_CODES; do ARGS+=("$([ "$c" = "$IL" ] && echo TRUE || echo FALSE)" "$c" "$(lang_name "$c")"); done
       CHOSEN="$(zenity --list --radiolist --title="$TITLE" --text="Sprache / Language" --height=480 \
           --column="" --column="code" --column="Sprache / Language" --hide-column=2 --print-column=2 \
           "${ARGS[@]}" 2>/dev/null)" || CHOSEN="" ;;
    *) if [ -t 0 ]; then
           echo "Sprache / Language:"
           i=1
           for c in $LANG_CODES; do printf '  %2d) %s%s\n' "$i" "$(lang_name "$c")" "$([ "$c" = "$IL" ] && echo '  *')"; i=$((i + 1)); done
           read -rp "[Enter = $(lang_name "$IL")] " N || N=""
           if [[ "$N" =~ ^[1-9][0-9]?$ ]]; then CHOSEN="$(echo $LANG_CODES | cut -d' ' -f"$N")" || CHOSEN=""; fi
       fi ;;
esac
case " $LANG_CODES " in *" ${CHOSEN:-x} "*) IL="$CHOSEN" ;; esac
mkdir -p "$INSTALL_DIR/sprachen"
printf '%s\n' "$IL" > "$LANG_FILE"
# Sprachdatei holen (neben dem Installer, sonst aus dem Projekt); Englisch dazu als Rueckfall der App
for c in "$IL" en; do
    [ "$c" = "de" ] && continue
    SRC=""
    for d in "$SCRIPT_DIR/../sprachen" "$SCRIPT_DIR/sprachen"; do
        if [ -f "$d/$c.json" ]; then SRC="$d/$c.json"; break; fi
    done
    if [ -n "$SRC" ]; then
        cp -f "$SRC" "$INSTALL_DIR/sprachen/$c.json"
    elif command -v curl >/dev/null 2>&1; then
        curl -fsSL --connect-timeout 15 --max-time 60 -o "$INSTALL_DIR/sprachen/$c.json.tmp" \
            "https://raw.githubusercontent.com/LucyWolf/printdock/main/sprachen/$c.json" \
            && mv -f "$INSTALL_DIR/sprachen/$c.json.tmp" "$INSTALL_DIR/sprachen/$c.json" \
            || rm -f "$INSTALL_DIR/sprachen/$c.json.tmp"
    fi
done
if [ "$IL" != "de" ]; then LANGJSON="$INSTALL_DIR/sprachen/$IL.json"; fi

# Schon installiert? Dann aktualisieren oder deinstallieren
if [ -f "$INSTALL_DIR/printdock.py" ] || [ -f "$HOME/.local/share/druckzentrale/druckzentrale.py" ] \
   || [ -f "$HOME/.local/share/hp-druckzentrale/hp_druckzentrale.py" ]; then
    Q="$(T "PrintDock ist schon installiert.")"
    L_UPD="$(T "Aktualisieren")"; L_DEL="$(T "Deinstallieren")"; L_CANCEL="$(T "Abbrechen")"
    case "$GUI" in
        1) set +e; kdialog --title "$TITLE" --yesnocancel "$Q" --yes-label "$L_UPD" --no-label "$L_DEL"
           CHOICE=$?; set -e ;;
        2) set +e; OUT=$(zenity --question --title="$TITLE" --text="$Q" --ok-label="$L_UPD" \
                --cancel-label="$L_CANCEL" --extra-button="$L_DEL"); RC=$?; set -e
           if [ "$OUT" = "$L_DEL" ]; then CHOICE=1; elif [ "$RC" = 0 ]; then CHOICE=0; else CHOICE=2; fi ;;
        *) read -rp "$Q  [1] $L_UPD  [2] $L_DEL  [x] $L_CANCEL: " A || A=""
           case "$A" in 1|a|A) CHOICE=0 ;; 2|d|D) CHOICE=1 ;; *) CHOICE=2 ;; esac ;;
    esac
    case "$CHOICE" in
        0) ;;
        1) uninstall ;;
        *) info "$(T "Abgebrochen – es wurde nichts verändert.")"; pause_in_terminal; exit 0 ;;
    esac
fi

# 1) Programmdatei: neben dem Installer, sonst die neueste aus dem Release
APP_SRC=""
if [ -z "${DZ_FROM_WEB:-}" ]; then
    for c in "$SCRIPT_DIR/printdock.py" "$SCRIPT_DIR/../printdock.py"; do
        if [ -f "$c" ]; then APP_SRC="$c"; break; fi
    done
fi
if [ -z "$APP_SRC" ]; then
    command -v curl >/dev/null 2>&1 || fail "$(T "curl fehlt – damit wird das Programm geladen.")"
    TMP_APP="$(mktemp)"
    trap 'rm -f "$TMP_APP"' EXIT
    note "$(T "Lade die neueste Version herunter …")"
    curl -fsSL --retry 2 --connect-timeout 20 --max-time 300 -o "$TMP_APP" "$RELEASE_URL/printdock.py" \
        || fail "$(T "Download fehlgeschlagen.\nBesteht eine Internetverbindung?")"
    APP_SRC="$TMP_APP"
fi

# 2) Pakete je Distribution. Alles in einem Root-Schritt (ein Passwort).
# Atomare Fedora-Systeme (Bazzite, Silverblue, Kinoite …) zuerst: dort gibt es zwar dnf, aber /usr ist
# schreibgeschuetzt. rpm-ostree legt die Pakete obendrauf, sie gelten erst nach einem Neustart.
ATOMIC=0
if [ -e /run/ostree-booted ] && command -v rpm-ostree >/dev/null 2>&1; then
    ATOMIC=1
    PKGS="python3-pyside6 qt6-qtwayland python3-cups python3-pillow cups cups-filters poppler-utils sane-backends sane-airscan ipp-usb avahi nss-mdns"
    HAVE="rpm -q"
    INSTALL="rpm-ostree install -y --idempotent --allow-inactive"
elif command -v pacman >/dev/null 2>&1; then
    PKGS="pyside6 qt6-wayland python-pycups python-pillow cups cups-filters poppler sane sane-airscan ipp-usb avahi nss-mdns"
    HAVE="pacman -Q"
    INSTALL="pacman -S --needed --noconfirm"
elif command -v apt-get >/dev/null 2>&1; then
    PKGS="qt6-wayland python3-pyside6.qtwidgets python3-pyside6.qtgui python3-pyside6.qtcore python3-cups python3-pil cups cups-filters poppler-utils sane-utils sane-airscan ipp-usb avahi-daemon libnss-mdns"
    HAVE="dpkg -s"
    INSTALL="env DEBIAN_FRONTEND=noninteractive apt-get install -y"
elif command -v dnf >/dev/null 2>&1; then
    PKGS="python3-pyside6 qt6-qtwayland python3-cups python3-pillow cups cups-filters poppler-utils sane-backends sane-airscan ipp-usb avahi nss-mdns"
    HAVE="rpm -q"
    INSTALL="dnf install -y"
elif command -v zypper >/dev/null 2>&1; then
    PKGS="python3-pyside6 qt6-wayland python3-pycups python3-Pillow cups cups-filters poppler-tools sane-backends sane-airscan ipp-usb avahi nss-mdns"
    HAVE="rpm -q"
    INSTALL="zypper --non-interactive install"
else
    fail "$(T "Unbekannte Paketverwaltung.\nBitte von Hand installieren: PySide6, pycups, Pillow, CUPS, SANE, sane-airscan, ipp-usb, Avahi.")"
fi

MISSING=""
for p in $PKGS; do
    $HAVE "$p" >/dev/null 2>&1 || MISSING="$MISSING $p"
done

# Dienste: CUPS (Drucken), Avahi (Drucker im Netz finden). ipp-usb startet von selbst beim Einstecken.
SERVICES=""
for s in cups avahi-daemon; do
    systemctl is-enabled "$s" >/dev/null 2>&1 && systemctl is-active "$s" >/dev/null 2>&1 || SERVICES="$SERVICES $s"
done

if [ -n "$MISSING" ] || [ -n "$SERVICES" ]; then
    MSG="$(T "Es wird eingerichtet:")"
    [ -n "$MISSING" ] && MSG="$MSG\n\n$(T "Pakete:")$MISSING"
    [ -n "$SERVICES" ] && MSG="$MSG\n\n$(T "Dienste einschalten:")$SERVICES"
    [ "$ATOMIC" = 1 ] && [ -n "$MISSING" ] && MSG="$MSG\n\n$(T "Auf diesem System (z. B. Bazzite) gelten neue Pakete erst nach einem Neustart.")"
    MSG="$MSG\n\n$(T "Danach fragt ein Fenster einmal nach deinem Passwort.")"
    printf '%b\n\n' "$MSG"
    # Antwortet das Fenster nicht (z.B. kaputte Desktop-Sitzung), im Terminal fragen statt stumm aufhoeren
    ANSWER=""
    case "$GUI" in
        1) kdialog --title "$TITLE" --continuecancel "$(printf '%b' "$MSG")" && ANSWER=ja || ANSWER=nein ;;
        2) zenity --question --title="$TITLE" --text="$MSG" --width=420 && ANSWER=ja || ANSWER=nein ;;
    esac
    if [ "$ANSWER" = "nein" ] || [ -z "$ANSWER" ]; then
        if [ -t 0 ]; then
            read -rp "$(T "Jetzt einrichten? [J/n] ")" A || A=""
            # Enter = ja; nur „nein“ in gaengigen Sprachen bricht ab (n…, н…, h… wie hayır)
            case "${A:-j}" in n*|N*|н*|Н*|h*|H*) ANSWER=nein ;; *) ANSWER=ja ;; esac
        elif [ "$ANSWER" = "nein" ] && [ -z "${IN_TERMINAL:-}" ]; then
            open_in_terminal   # Fenster ging nicht: im Terminal weitermachen, dort sieht man alles
        fi
    fi
    [ "$ANSWER" = "ja" ] || { info "$(T "Abgebrochen – es wurde nichts verändert.")"; pause_in_terminal; exit 0; }
    note "$(T "Installiere Pakete – das kann ein paar Minuten dauern …")"
    ROOT_CMD=""
    [ -n "$MISSING" ] && ROOT_CMD="$INSTALL$MISSING"
    for s in $SERVICES; do
        ROOT_CMD="${ROOT_CMD:+$ROOT_CMD && }systemctl enable --now $s"
    done
    as_root "$ROOT_CMD" || fail "$(T "Die Installation wurde abgebrochen oder ist fehlgeschlagen.\n\nFehlende Pakete:{0}" "$MISSING")"
fi

# Atomar: frisch eingespielte Pakete sind erst nach dem Neustart da – dann nicht abbrechen, sondern
# fertig installieren und am Ende zum Neustart auffordern
NEED_REBOOT=0
if ! python3 -c "import PySide6, cups, PIL" 2>/dev/null; then
    if [ "$ATOMIC" = 1 ]; then
        NEED_REBOOT=1
    else
        fail "$(T "Python findet PySide6, pycups oder Pillow nicht.\nBitte prüfen, ob die Pakete installiert sind.")"
    fi
fi

# 3) Programm kopieren
mkdir -p "$INSTALL_DIR"
cp -f "$APP_SRC" "$INSTALL_DIR/printdock.py"
chmod 755 "$INSTALL_DIR/printdock.py"
# Reste der frueheren Namen; eigene Druckerbilder mitnehmen
for d in $OLD_INSTALL_DIRS; do
    [ -d "$d/bilder" ] && mkdir -p "$INSTALL_DIR/bilder" && cp -rn "$d/bilder/." "$INSTALL_DIR/bilder/"
    rm -rf "$d"
done
rm -f $OLD_DESKTOP_FILES

# 4) Menueeintrag
mkdir -p "$(dirname "$DESKTOP_FILE")"
cat > "$DESKTOP_FILE" << DESKTOP
[Desktop Entry]
Type=Application
Name=PrintDock
Comment=$(T "Drucken, Scannen, Tintenstand und Wartung für Drucker")
Exec=python3 $INSTALL_DIR/printdock.py
Icon=printer
Categories=Office;Graphics;Utility;
StartupWMClass=printdock
DESKTOP
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$HOME/.local/share/applications" || true

trap - EXIT; rm -f "${TMP_APP:-}"
if [ "$NEED_REBOOT" = 1 ]; then
    info "$(T "Installation abgeschlossen – bitte jetzt den PC neu starten.\n\nDie neuen Pakete gelten auf diesem System erst nach dem Neustart.\nDanach startet PrintDock über das Anwendungsmenü.")"
    pause_in_terminal
    exit 0
fi
info "$(T "Installation abgeschlossen!\n\nStart über das Anwendungsmenü: PrintDock\n\nUSB-Drucker, die schon stecken: einmal ab- und wieder anstecken.")"
pause_in_terminal
