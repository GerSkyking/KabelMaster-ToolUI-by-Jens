import { Link } from "react-router-dom";

/** Kurzanleitung: der übliche Ablauf und wofür welcher Reiter da ist. */
export function HelpPage() {
  return (
    <div className="help">
      <h1>Hilfe</h1>

      <section className="card">
        <h2>Der übliche Ablauf</h2>
        <ol>
          <li><b>Projekt anlegen</b> (Startseite) und Kolleginnen und Kollegen unter <i>Mitglieder</i> hinzufügen.</li>
          <li><b>Excel-Datei hochladen</b> (Projekt → Arbeitsverzeichnis). Mehrere Dateien gehen auf einmal, auch per Drag &amp; Drop.</li>
          <li><b>Als Liste importieren.</b> Hat die Datei mehrere Blätter, wählst du: alle Blätter zu einer Liste, ein Blatt oder nur das erste.</li>
          <li><b>Spalten zuordnen</b> (Liste → Kabelzug → Spalten): Kabel-ID, Soll-Länge, Von, Bis, Ist-Länge, Datum …</li>
          <li><b>Arbeiten</b> in den Reitern der Liste. Änderungen sehen alle sofort, Konflikte werden gemeldet.</li>
        </ol>
      </section>

      <section className="card">
        <h2>Die Reiter einer Liste</h2>
        <ul>
          <li><b>Kabelzug</b> – Länge eintragen, „Speichern &amp; weiter“. Funktioniert auch ohne Internet.</li>
          <li><b>Einzelsuche / Stapelsuche</b> – suchen und als Excel oder PDF ausgeben.</li>
          <li><b>Farbmarkierung</b> – Treffer farbig markieren und exportieren.</li>
          <li><b>KMK</b> – Beschriftungen als PDF/Excel, danach als „beschriftet“ abhaken.</li>
          <li><b>Schrank-Erkennung</b> – Schränke aus den Texten erkennen und je Schrank exportieren.</li>
          <li><b>Übersetzer</b> – Werte aus einer zweiten Tabelle über eine Schlüsselspalte (z. B. W-Nummer) eintragen.
            Vorher siehst du jede Änderung, danach kannst du den Lauf rückgängig machen.</li>
          <li><b>Übersicht</b> – Fortschritt je Querschnitt, Prognose, Tagesbericht.</li>
          <li><b>Konflikte</b> – wenn zwei Personen dasselbe Feld unterschiedlich geändert haben, entscheidest du hier.</li>
          <li><b>Verlauf</b> – wer hat wann was geändert; einzelne Werte oder ganze Läufe zurücksetzen.</li>
        </ul>
      </section>

      <section className="card">
        <h2>Einkauf, Whiteboard, Kalender, Tagesbericht</h2>
        <ul>
          <li><b>Einkauf:</b> Im <i>Katalog</i> liegen alle Artikel (mit Bild und Artikelnummer) für alle Projekte. „Zur Liste“ setzt einen Artikel auf die Packliste eines Projekts,
            ohne ihn zu kaufen oder zu packen. Auf der Packliste hakst du <i>gepackt</i> und <i>erledigt / mitgebracht</i> ab – mit deinem Namen und der Uhrzeit.
            Erledigtes wandert ins <i>Archiv</i> mit Auswertung (häufigste Artikel, je Monat, je Person, je Projekt) und Excel-Export. „Bilder“ zeigt statt der Liste Kacheln mit Foto.</li>
          <li><b>Whiteboard:</b> Haftnotizen frei verschieben; eines je Projekt und ein gemeinsames zur Planung über alle Projekte. Andere sehen Änderungen nach wenigen Sekunden.</li>
          <li><b>Kalender:</b> Phasen, Termine, Urlaub und Meilensteine je Projekt. Externe Kalender (iCal-/ICS-Link von Nextcloud, Google, Outlook) lassen sich einbinden und erscheinen schreibgeschützt.</li>
          <li><b>Tagesbericht:</b> persönliche Notizen, was du im Projekt gemacht hast (nur du siehst sie), mit Auswertung nach Tag, Woche, Monat und Jahr.</li>
        </ul>
      </section>

      <section className="card">
        <h2>Gut zu wissen</h2>
        <ul>
          <li><b>Offline:</b> „Offline bereithalten“ (Projekt → Listen) lädt die Liste aufs Gerät. Die Seite muss dazu über HTTPS laufen und einmal im Browser geöffnet worden sein. Änderungen werden bei Verbindung automatisch übertragen.</li>
          <li><b>Excel-Export bei mehreren Blättern:</b> Wurden die Blätter zu einer Liste zusammengefasst, entsteht beim Export wieder eine Mappe mit denselben Blättern. Formatierungen und Formeln der Originaldatei bleiben dabei nicht erhalten.</li>
          <li><b>Notizen</b> (Projekt) sind Markdown: <code># Überschrift</code>, <code>- [ ] Aufgabe</code>, <code>**fett**</code>. Häkchen lassen sich in der Ansicht anklicken.</li>
          <li><b>Vorlagen</b> speichern die Einstellungen eines Reiters (Spalten, Suchbegriffe, Layout) unter deinem Namen; alle können sie benutzen.</li>
          <li><b>Windows-App:</b> unter <Link to="/account">Konto</Link> einen API-Key erzeugen und in der App unter Server → Verbindung eintragen.</li>
          <li><b>Löschen:</b> Dateien landen im Papierkorb des Servers. Projekte und Listen werden aus der Datenbank entfernt – Sicherungen (Verwaltung) schützen davor.</li>
        </ul>
      </section>
    </div>
  );
}
