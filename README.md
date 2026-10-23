# UW Kabel-Master ToolUI by Jens – Web

Web-App für Excel-Listen, **Kabelzug**, KMK, Schrank-Erkennung und Auswertungen, nutzbar am PC, Tablet und Handy (installierbare PWA), teils auch **ohne Internet**.
Änderungen werden lokal gespeichert und später abgeglichen. Dazu gibt es Projekte mit Arbeitsverzeichnissen,
Benutzerverwaltung, temporäre Links für Externe und eine Schnittstelle für die Windows-App.

```
Browser / PWA  ──►  nginx (optional)  ──►  FastAPI  ──►  PostgreSQL
 (IndexedDB,                                  │
  Offline-Sync)                               └──►  /data/projects/<projekt>/files   (Excel-Dateien)
Windows-App / Skript ── API-Key ──────────────┘
```

| Ordner | Inhalt |
|---|---|
| `server/` | FastAPI-Backend (Auth, Projekte, Dateien, Sync, Share-Links, Audit), Alembic-Migrationen, Tests |
| `web/` | React-PWA (alle Reiter, Offline-Speicher, Sync-Outbox) |
| `core/` | Kopie der Logik der Desktop-App (Excel-Import, Suche, Export, KMK, Schrank, Kabelzug, Prognose, Bericht) |
| `windows_client/` | `wtsync`: Offline-Abgleich per API-Key (Bibliothek + Kommandozeile) |
| `deploy/nginx/` | Reverse-Proxy-Konfiguration (mitgeliefert oder als Vorlage für den eigenen nginx) |

## Schnellstart

Voraussetzung: Docker mit Compose.

```bash
cp .env.example .env
# In .env mindestens setzen: POSTGRES_PASSWORD, SECRET_KEY (openssl rand -hex 32), ADMIN_PASSWORD, BASE_URL
docker compose up -d --build
```

Die App läuft dann auf `http://127.0.0.1:8000` (Port/Bind über `APP_PORT`/`APP_BIND`). Anmeldung mit `ADMIN_USERNAME` /
`ADMIN_PASSWORD` (wird beim ersten Start angelegt). API-Dokumentation: `/api/docs`.

> `POSTGRES_PASSWORD` nur mit URL-sicheren Zeichen wählen (z. B. `openssl rand -hex 24`), da es in die DB-URL eingesetzt wird.

### Reverse Proxy

* **Eigener nginx vor dem Stack** (Standard): auf `127.0.0.1:8000` weiterleiten, Vorlage `deploy/nginx/external-proxy.conf`.
  In `.env`: `BASE_URL=https://listen.example.org` und `COOKIE_SECURE=true`. `X-Forwarded-*` Header werden ausgewertet.
* **Mitgelieferter nginx:** `docker compose --profile proxy up -d --build` (Ports `PROXY_HTTP_PORT`/`PROXY_HTTPS_PORT`).
  Für HTTPS Zertifikate nach `deploy/nginx/certs/` legen (`fullchain.pem`, `privkey.pem`) und den HTTPS-Block in
  `deploy/nginx/default.conf` aktivieren. Ohne HTTPS funktionieren Service Worker/Offline-Modus nur auf `localhost` –
  für Handy/Tablet im Netz ist **HTTPS Pflicht**.

## Anmeldung

Alle Arten laufen gleichzeitig; das Login-Formular zeigt nur die aktivierten.

| Art | Aktivierung (`.env`) | Hinweise |
|---|---|---|
| Lokale Benutzer | `LOCAL_LOGIN_ENABLED=true` | Argon2-Hashes, Sperre nach 8 Fehlversuchen / 5 min je IP+Name. Admin legt Benutzer unter *Verwaltung* an. |
| LDAP / AD | `LDAP_SERVER_URI`, `LDAP_USER_BASE`, … | Dienstkonto sucht den Benutzer, danach Bind mit dessen Passwort. AD: `LDAP_USER_FILTER=(sAMAccountName={username})`. Mitglieder von `LDAP_ADMIN_GROUP_DN` werden Admin. |
| OpenID Connect | `OIDC_ISSUER`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET` | Redirect-URI beim Anbieter: `${BASE_URL}/api/auth/oidc/callback`. Optional Admin über `OIDC_ADMIN_GROUP` (Claim `OIDC_GROUPS_CLAIM`). |
| OAuth2 (generisch) | `OAUTH2_AUTHORIZE_URL`, `OAUTH2_TOKEN_URL`, `OAUTH2_USERINFO_URL`, … | z. B. GitHub/Gitea. Redirect-URI: `${BASE_URL}/api/auth/oauth2/callback`. |

Externe Benutzer werden beim ersten Login automatisch angelegt (`AUTO_CREATE_USERS=true`) und danach Projekten zugewiesen.

## Projekte, Dateien, Rechte

Jedes Projekt hat ein Arbeitsverzeichnis `/data/projects/<projekt>/files`, in dem die Excel-Dateien liegen
(Upload/Download im Browser, gelöschte Dateien landen im Papierkorb `…/trash`). Eine Datei wird als **Liste** importiert;
die Zeilen liegen dann in der Datenbank und sind versioniert.

Projektrollen: **Betrachter** (lesen) · **Bearbeiter** (Werte eintragen, importieren) · **Besitzer** (Mitglieder,
Links, Löschen). Administratoren sehen alle Projekte.

## Reiter einer Liste

Jede importierte Liste hat dieselben Reiter wie die Desktop-App:
**Kabelzug · Einzelsuche · Stapelsuche · Farbmarkierung · KMK · Schrank-Erkennung · Übersetzer · Übersicht · Konflikte · Verlauf**.
Kabelzug arbeitet auch offline; Suche, Farbmarkierung, KMK und Schrank-Erkennung rechnen auf dem Server (dieselbe Logik wie am
Desktop, erzeugen Excel/PDF) und brauchen deshalb eine Verbindung. Vor jeder Vorschau/jedem Export werden lokale Änderungen übertragen.
Kopfzeile/Dateiname (Datum, Ersteller, Firma, Projekt, Ort) stellst du je Reiter unter „Kopfzeile und Dateiname“ ein.

### Verlauf, Rückgängig, Notizen, Hilfe

Der Reiter *Verlauf* zeigt alle Änderungen einer Liste (wer, wann, alt → neu). Einzelne Werte oder ein ganzer Übersetzer-Lauf lassen sich zurücksetzen;
das geht nur, solange der Wert seither nicht erneut geändert wurde (sonst Hinweis, kein Überschreiben). Notizen im Projekt: Aufgaben-Häkchen sind in der Ansicht anklickbar.
Projektseite: Listen umbenennen, Name/Beschreibung ändern, Sprungleiste. Unter *Hilfe* (Kopfzeile) steht eine Kurzanleitung. Die Datenbank-Migration 0004 läuft beim Start automatisch.

### Einkauf/Packliste, Whiteboard, Kalender, Tagesbericht
- **Einkauf** (`/shop`): globaler Artikelkatalog (Name, Artikelnummer, Kategorie, Einheit, Bild bis 3 MB; PNG/JPEG/GIF/WebP, kein SVG, abgelegt unter `DATA_DIR/catalog`).
  Aus dem Katalog oder per Freitext kommt ein Bedarf (mitbringen/prüfen, Menge, Projekt, Datum) auf die Packliste. Je Eintrag zwei Häkchen *gepackt* und *erledigt*, jeweils mit Name und Zeit.
  Erledigte Einträge bilden das Archiv mit Auswertung (je Artikel, Monat, Person, Projekt) und Excel-Export. Ansicht als Liste oder mit Bildern. Lesende Projektmitglieder sehen nur; „ohne Projekt“ dürfen alle bearbeiten.
- **Whiteboard** (`/board`, `/projects/<id>/board`): verschiebbare Haftnotizen, je Projekt oder gemeinsam; Abgleich per Abfrage alle 5 s (keine Echtzeit-Verbindung).
- **Kalender** (`/schedule`): Phasen, Termine, Urlaub, Meilensteine; externe Kalender per ICS-Link (Server holt sie ab, Cache 6 h, nur http(s); Adressen im internen Netz sind
  gesperrt, außer `CALENDAR_ALLOW_PRIVATE=true`). Unterstützt Datum/Uhrzeit, ganztägig, einfache Wiederholungen (täglich/wöchentlich/monatlich/jährlich); komplexe Regeln und Einzel-Ausnahmen nicht.
- **Tagesbericht** (`/worklog`): persönliche Einträge je Projekt (nur für den Autor sichtbar), Auswertung nach Tag/Woche/Monat/Jahr inklusive Zahl der eigenen Listen-Änderungen, Excel-Export.
  Zeitzone der Auswertung: `TIMEZONE` (Standard Europe/Berlin). Neue Tabellen legt die Migration 0005 beim Start an.

### Übersetzer und Excel-Mappen mit mehreren Blättern

Der Reiter *Übersetzer* trägt Werte aus einer zweiten Tabelle (andere Liste oder Datei im Arbeitsverzeichnis, bei Mappen mit Blattwahl)
anhand einer Schlüsselspalte (z. B. W-Nummer) in die Liste ein. Du ordnest Spalten der Quelle Spalten der Liste zu (oder neuen Spalten),
wählst je Zuordnung „überschreiben“ oder „nur leere füllen“ und siehst vorher in der Vorschau jede Änderung. Nicht zugeordnete Spalten
bleiben unberührt. Ergebnis: auf die Liste anwenden oder als Excel herunterladen.

Hat eine Excel-Datei mehrere Blätter, fragt der Import: **alle Blätter zu einer Liste** (zusätzliche Spalte „Blatt“, Spalten aller Blätter
vereint), nur ein Blatt oder nur das erste. Bei der zusammengefassten Liste trägt der Übersetzer auf Wunsch nur in bestimmte Blätter ein,
und der Excel-Export erzeugt wieder eine **Mappe mit denselben Blättern** (je Blatt die ursprünglichen Spalten plus neue Spalten, die
dort Werte haben).

### Kabelzug

* Spalten werden **per Spalte** zugeordnet (Dropdown „A – Name“): Kabel, Querschnitt, Soll-Länge, Von, Bis, gezogene Länge, Datum.
  Optional: **Ziel 1**, **Ziel 2** (für die Prognose), **prognostizierte Länge**, **beschriftet Ziel 1/2**.
  „Neue Spalte anlegen“ ergänzt eine Spalte direkt in der Liste.
* Das aktive Kabel (↑/↓, Bild auf/ab) wird groß angezeigt; Länge = |Bis − Von|; Enter springt zum nächsten offenen Kabel.
* **Auto-Datum:** Sobald ein Kabel als gezogen gilt, wird das heutige Datum im Format `TT.MM.JJ` eingetragen (nur wenn leer).
* Analyse je Querschnitt (Stück und Meter, Stand in %), optional ohne kurze Enden (frei wählbare Grenze).

### KMK und „beschriftet“

* Jeder KMK-Export (PDF und/oder Excel-Kontrolldatei) wird als **Exportlauf** gespeichert (wer, wann, welche Kabel).
* Nach dem Export entscheidest du, ob schon beschriftet wurde: **Ziel 1 / Ziel 2 / Beide / Später entscheiden**.
  Pro Benutzer einstellbar: jedes Mal fragen, automatisch (z. B. Beide) oder immer später.
  Unter **Exportläufe** lässt sich das Abhaken jederzeit nachholen oder zurücknehmen.
* Abgehakt wird als Datum in die Spalten „beschriftet Ziel 1“ / „beschriftet Ziel 2“ (werden bei Bedarf automatisch angelegt).
  „Bereits beschriftete ausblenden“ nimmt diese Kabel aus der nächsten Ausgabe.

### Übersicht, Prognose, Tagesbericht

* **Übersicht** (je Liste und im Projekt): gezogene/fehlende Kabel, Meter und Stand je Querschnitt, Prognose und Abweichung zum Soll.
* **Prognose:** Kabel mit gleichem Querschnitt und gleichen Zielen (Ziel 1/Ziel 2, Richtung egal) sind gleich lang. Grundlage sind die
  ersten bis zu 3 gezogenen Kabel dieser Strecke. Gibt es keine, wird das Verhältnis Ist/Soll der ersten gezogenen Kabel desselben
  Querschnitts auf die Soll-Länge angewendet, sonst gilt die Soll-Länge. „Prognose in Liste schreiben“ trägt die Werte in die Spalte
  „prognostizierte Länge“ ein.
* **Tagesbericht (TXT):** pro Tag gezogene Kabel und Meter, aufgeschlüsselt nach Querschnitt (optional Zeitraum; je Liste oder je Projekt).

### Vorlagen

Vorlagen liegen zentral unter `Vorlagen/<Benutzer>/<Name>` (z. B. `Vorlagen/JensR/Siemens`). **Alle sehen und nutzen sie**, ändern und
löschen dürfen nur der Besitzer und Administratoren. Speichern/Laden im jeweiligen Reiter; Übersicht unter *Vorlagen*.
JSON-Export/-Import ist kompatibel zum Vorlagenformat der Desktop-App.

## Offline-Betrieb und Abgleich

* Die PWA speichert Listen in IndexedDB. Änderungen kommen in eine Warteschlange und werden automatisch übertragen
  (nach Eingabe, alle 30 s, beim Wiederverbinden). Pro Liste: *Projekte → „Offline bereithalten“*.
* **Feldweiser Abgleich:** Ändern zwei Personen *dasselbe Feld* unterschiedlich, wird nur dieses Feld zum Konflikt; alle anderen
  Felder der Zeile werden übernommen. Der Konflikt wird **auf dem Server gespeichert** (Reiter *Konflikte*, Zähler am Reiter und in der
  Projekt-Übersicht): beide Werte mit Person und Zeit, jemand mit Bearbeiter-Rolle entscheidet „Diesen Wert behalten“ oder
  „Diesen Wert übernehmen“. Bis dahin gilt der Wert, der zuerst im System war.
* Die Seite selbst (App-Shell) ist per Service Worker offline verfügbar, sobald sie einmal geladen wurde.

## Temporäre Links für Externe

Liste öffnen → **Teilen**: Link mit Gültigkeit (Stunden) und Modus *ansehen* oder *Werte eintragen*. Der Klartext-Link wird
nur einmal angezeigt, in der DB liegt nur der Hash. Links lassen sich jederzeit widerrufen. Gäste sehen nur diese eine Liste
und dürfen keine Zeilen anlegen/löschen.

## Windows-App / Skripte (API-Key)

*Konto → API-Keys* erzeugt einen Schlüssel (Header `X-API-Key`). Mit dem mitgelieferten Client lässt sich halb offline arbeiten:

```bash
pip install -r windows_client/requirements.txt
cd windows_client
set WT_URL=https://listen.example.org
set WT_API_KEY=wtk_...
python -m wtsync list
python -m wtsync pull 5 Kabelliste.xlsx     # Excel + Snapshot lokal ablegen
#   … Excel offline bearbeiten …
python -m wtsync push Kabelliste.xlsx       # nur geänderte Zellen übertragen, Konflikte werden gemeldet
```

Die **Desktop-App** nutzt denselben Client: Menü **Server → Verbindung / API-Key …** (Adresse, Schlüssel, Arbeitsordner; „Verbindung testen“),
dann **Liste vom Server holen …** (öffnet die Datei im aktiven Reiter) und nach der Arbeit (z. B. Kabelzug → „Als Excel speichern“)
**Änderungen zum Server senden …**. Der Schlüssel liegt in den Programmeinstellungen des Benutzers. Eine Kopie des Clients liegt im
Desktop-Projekt unter `wtsync/` – Änderungen am Client in beiden Ordnern nachziehen.

## Logging, Audit, Betrieb

* **Logs:** JSON-Zeilen auf stdout (`docker compose logs app`, für Loki/ELK geeignet) plus rotierende Datei `/data/logs/app.log`;
  jede Anfrage hat eine `X-Request-ID`.
* **Audit:** Logins, Dateiuploads, Imports, Syncs, Freigaben, API-Keys, Benutzeränderungen → Tabelle `audit_log`, einsehbar unter *Verwaltung*.
* **Health:** `/api/health/live` (ohne DB), `/api/health` (mit DB).
* **Sicherungen (Verwaltung → Sicherungen):** manuell per Knopf und **täglich automatisch** (`BACKUP_TIME`, `BACKUP_KEEP`,
  optional mit Excel-Dateien). Eine Sicherung ist eine ZIP-Datei mit Projekten, Listen, Zeilen und Vorlagen in `/data/backups`;
  Download/Upload möglich. **Versionen vergleichen:** zwei Sicherungen oder Sicherung gegen aktuellen Stand (geänderte Zellen,
  neue/entfernte Zeilen und Spalten). **Wiederherstellen** je Projekt (vorher entsteht automatisch eine „vor Wiederherstellung“-Sicherung).
  Zeilen werden dabei über die Zeilennummer zugeordnet. Zusätzlich bleibt `pg_dump` für ein komplettes DB-Backup sinnvoll:
  `docker compose exec db pg_dump -U wtlisten wtlisten > backup.sql`.
* **Änderungsprotokoll:** jede Feldänderung (wer, wann, alt, neu) wird in `row_changes` festgehalten.
* **Speicherort / Updates:** Alle Daten liegen im Host-Ordner `DATA_ROOT` (`.env`, Standard `./data`) mit den Unterordnern
  `postgres/` (Datenbank), `app/projects/<projekt>/files/` (Excel-Dateien), `app/backups/` und `app/logs/`. Die Konfiguration liegt in
  der `.env`. Update: `git pull && docker compose up -d --build` – Daten und Konfiguration bleiben erhalten, Migrationen laufen beim Start
  automatisch. Umzug auf einen anderen Server: `docker compose down`, den `DATA_ROOT`-Ordner samt `.env` kopieren, dort `docker compose up -d --build`.
  Den Ordner nie bei laufender Datenbank kopieren (erst `docker compose stop`) oder besser die Sicherungen/`pg_dump` nutzen.
* **Schema ändern:** `cd server && alembic revision --autogenerate -m "beschreibung"`.

## Entwicklung

```bash
# Backend (SQLite, kein Docker nötig)
cd server && pip install -r requirements-dev.txt && python -m pytest

# Frontend
cd web && npm install && npm test && npm run dev      # Proxy auf http://localhost:8000
# Server lokal mit gebautem Frontend:
cd web && npm run build
cd ../server && ADMIN_PASSWORD=... STATIC_DIR=../web/dist PYTHONPATH=.:.. uvicorn wtserver.main:app
```

`web/src/sync.e2e.test.ts` prüft den Client-Sync gegen einen laufenden Server (Variablen siehe Dateikopf).

## Sicherheitshinweise

* In Produktion (`ENVIRONMENT=production`, im Compose gesetzt) startet der Server nur mit einem eigenen `SECRET_KEY` (≥ 32 Zeichen).
* Sitzungen: HttpOnly-Cookie (`SameSite=Lax`, `Secure` über `COOKIE_SECURE`), CSP und weitere Header sind gesetzt.
* API-Keys und Share-Tokens werden nur als SHA-256-Hash gespeichert. API-Keys können keine weiteren Keys erzeugen.
* Die Login-Sperre liegt im Speicher je Worker-Prozess; für strengere Grenzen zusätzlich `limit_req` im nginx einsetzen.
