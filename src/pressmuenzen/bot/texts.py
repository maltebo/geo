"""German user-facing strings (was data/telegram_constants.py). One place for copy."""

from __future__ import annotations

START = (
    "Willkommen zum Pressmünzen-Bot! Hier findest du schnell heraus, wo der nächste "
    "Stempelautomat ist.\n\n"
    "Funktionen:\n"
    "/suche – Automaten in der Nähe finden\n"
    "/alle_zeigen – Karte mit allen Automaten\n"
    "/finden <text> – Automaten per Namenssuche finden (z. B. /finden Hamburg Dom)\n"
    "/details <id> – Details zu einem Automaten (z. B. /details 2023)\n"
    "/besucht <id> – Automat als besucht markieren\n"
    "/nicht_besucht <id> – Markierung entfernen\n"
    "/heimat – Heimatort setzen (für Benachrichtigungen)\n"
    "/beobachten <radius_km> – neue Automaten im Umkreis beobachten\n"
    "/beobachtungen – Beobachtungen verwalten\n"
    "/stumm – Benachrichtigungen stummschalten\n"
    "/melden <id> – einen Automaten melden oder korrigieren"
)

SUCHE_START = (
    "Willst du alle Automaten im Umkreis von n Kilometern oder insgesamt die "
    "nächsten n Automaten angezeigt bekommen?"
)
ENTER_RADIUS = "Gib bitte den Radius in Kilometern an. Zum Beispiel 10 oder 5.7"
ENTER_COUNT = "Gib bitte die Anzahl der Automaten an, die du sehen willst."
ENTER_LOCATION = (
    "Bitte gib mir jetzt den Ort, von dem aus du suchen willst. Entweder als Text "
    "(z. B. „Hauptbahnhof Köln“) oder als Standort über das Menü."
)
TRYING_ADDRESS = "Okay, ich versuche, ob ich diese Adresse kenne!"
ADDRESS_NOT_FOUND = "Dieser Ort ({query}) wird leider nicht gefunden."
LOCATION_ERROR = "Da ist leider ein Fehler aufgetreten, der Ort konnte nicht gefunden werden."
NO_MACHINE_FOUND = "Leider wurde kein Automat gefunden."
INVALID_OPTION = "Das war keine gültige Option. Bitte starte erneut mit /suche."
GENERIC_ERROR = "Da ist etwas schiefgegangen ..."
BYE = "Abgebrochen. Bis bald!"

MAP_READY = "Hier ist deine Karte: {url}"
MAP_ALL_READY = "Karte mit allen Automaten: {url}"

DETAILS_USAGE = "Bitte benutze diese Funktion so:\n/details <id>\nZum Beispiel: /details 1894"
DETAILS_NOT_FOUND = "Die ID {id} scheint nicht zu existieren ..."

FIND_USAGE = "Bitte gib einen Suchbegriff an, z. B.:\n/finden Hamburg Dom"
FIND_NONE = "Kein Automat gefunden für „{query}“."
FIND_HEADER = "Treffer für „{query}“ ({count}):"
FIND_FLAG_GONE = " – entfernt"
FIND_FLAG_NO_COORDS = " – nicht auf der Karte (keine Koordinaten)"
FIND_TRUNCATED = "… (nur die ersten {limit} Treffer; bitte Suchbegriff verfeinern)"

VISITED_USAGE = "Bitte benutze: /besucht <id>\nZum Beispiel: /besucht 1894"
VISITED_ADDED = "Der Automat {name} wurde zu den besuchten Automaten hinzugefügt."
VISITED_ALREADY = "Der Automat {name} war schon als besucht markiert."
NOT_VISITED_USAGE = "Bitte benutze: /nicht_besucht <id>"
NOT_VISITED_REMOVED = "Der Automat {name} wurde aus den besuchten Automaten entfernt."
NOT_VISITED_ABSENT = "Der Automat {name} war noch nicht als besucht markiert."

HOME_ASK = "Bitte sende mir deinen Heimatort als Standort oder als Adresse (Text)."
HOME_SET = (
    "Heimatort gespeichert. Ich habe eine Standard-Beobachtung im Umkreis von {radius} km angelegt."
)
WATCH_USAGE = "Bitte benutze: /beobachten <radius_km>\nZum Beispiel: /beobachten 30"
WATCH_NEED_HOME = "Bitte setze zuerst deinen Heimatort mit /heimat."
WATCH_ADDED = "Beobachtung angelegt: neue Automaten im Umkreis von {radius} km."
WATCH_NONE = "Du hast keine aktiven Beobachtungen."
WATCH_LIST_HEADER = "Deine Beobachtungen:"
WATCH_REMOVED = "Beobachtung {id} entfernt."
MUTED = "Benachrichtigungen sind jetzt stummgeschaltet. /stumm hebt das wieder auf."
UNMUTED = "Benachrichtigungen sind wieder aktiv."
NOTIFY_NEW_MACHINE = "Neuer Automat in deiner Nähe ({distance} km): {name}\n{url}"

REPORT_DEEPLINK_INVALID = "Dieser Link ist ungültig oder abgelaufen."
REPORT_DEEPLINK_THANKS = (
    'Danke! Deine Korrektur für "{name}" wurde an die Moderation weitergeleitet.'
)

REPORT_USAGE = "Bitte benutze: /melden <id>\nZum Beispiel: /melden 1894"
REPORT_START = (
    "Was möchtest du zu „{name}“ melden?\n"
    "Sende eine Standort-Pin, um die Position zu korrigieren, oder schreibe:\n"
    "weg – Automat existiert nicht mehr\n"
    "umgezogen – Automat wurde versetzt\n"
    "name – Name ist falsch\n"
    "sonstiges – etwas anderes"
)
REPORT_THANKS = "Danke! Deine Meldung wurde an die Moderation weitergeleitet."

# Admin / moderation
ADMIN_ONLY = "Diese Funktion ist nur für Admins."
QUEUE_EMPTY = "Die Moderations-Warteschlange ist leer."
QUEUE_HEADER = "Offene Meldungen:"
QUEUE_ITEM = "#{id} [{type}] {name}: {comment}"
QUEUE_ITEM_GPS = (
    "#{id} [gps] {name}\n"
    "  Alt: {old_url}\n"
    "  Neu: {new_url}\n"
    "  Verschiebung: {distance}\n"
    "  Karte: {map_url}"
)
QUEUE_ITEM_GPS_NO_OLD = (
    "#{id} [gps] {name} (kein bisheriger Standort)\n  Neu: {new_url}\n  Karte: {map_url}"
)
QUEUE_ITEM_ACTIONS = "\n  /ok_{id}  /nope_{id}"
OK_USAGE = "Bitte benutze: /ok <correction_id>"
NOPE_USAGE = "Bitte benutze: /nope <correction_id>"
CORRECTION_APPROVED = "Meldung {id} wurde angenommen."
CORRECTION_REJECTED = "Meldung {id} wurde abgelehnt."
CORRECTION_NOT_FOUND = "Meldung {id} wurde nicht gefunden."

# Admin catalogue-change notifications (always sent to ADMIN_CHAT_IDS)
NOTIFY_ADMIN_ADDED = "Neue Standorte hinzugefügt ({count}):"
NOTIFY_ADMIN_ADDED_ITEM = "#{id} {name}\n{url}"
NOTIFY_ADMIN_DELETED = "Standort entfernt: #{id} {name}"
NOTIFY_ADMIN_NEW_CORRECTION = "Neue Meldung #{id} [{type}] {name}\n{comment}"

# Stale-location review (/stale) and admin removal (/entfernen)
STALE_NONE = "Keine veralteten Standorte: alle wurden kürzlich in der Quelle gesehen."
STALE_HEADER = "Seit über {days} Tagen nicht mehr in der Quelle gesehen:"
STALE_ITEM = "#{id} {name} – zuletzt vor {days} Tagen"
STALE_FOOTER = (
    "\nDas heißt nicht zwingend, dass der Automat weg ist (Forenthemen bleiben oft "
    "bestehen). Bei Bedarf entfernen mit: /entfernen <id>"
)
REMOVE_USAGE = "Bitte benutze: /entfernen <id>\nZum Beispiel: /entfernen 1894"
REMOVE_DONE = "Standort #{id} ({name}) wurde entfernt."
REMOVE_ALREADY_GONE = "Standort #{id} ist bereits entfernt."
