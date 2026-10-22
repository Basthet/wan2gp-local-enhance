# PLAN.md — System-Prompt-Bibliothek (Plugin)

Ziel: Zeile 1 bekommt ein **Dropdown** statt Checkbox; es zeigt nur `default` +
gespeicherte Namen. `default` = WanGPs normaler System-Prompt (kein Override).
Der Plugin-Tab legt neue benannte Prompts an (max 64 Zeichen) im
**installationsweit einstellbaren Ordner** (Standard `~/Prompts/`, Feld mit
eigenem Speichern-Knopf).

## Lücken des ursprünglichen Plans (hier entschieden)

1. **Speicherpfad der Auswahl:** Ein gespeicherter Name ist nur gültig, wenn
   `_save_template()` ihn durchlässt. Heute prüft die Stelle
   (`plugin.py:838`) gegen `_TEMPLATE_PRESETS` und schreibt sonst
   `_DEFAULT_TEMPLATE` zurück — ein Bibliotheksname würde also beim nächsten
   Speichern still auf `default` zurückfallen. **Entscheidung:** die gültige
   Menge ist `{_PROMPT_DEFAULT} ∪ _list_prompt_names()`; die Legacy-Presets
   (`WanGP-Standard`, `Character Sheet`, `Turnaround`, `Eigene Vorlage`)
   bleiben **nur lesend** als Fallback gültig (alte Config-Werte), werden aber
   nicht mehr neu angeboten.
2. **Dropdown = Formularfeld:** `gr.Dropdown` wird von Gradio wie
   Checkbox/Number in einen `gr.Form` gruppiert (AGENTS.md, „Gradio-Fallen").
   Es braucht deshalb dieselbe Unwrap-Behandlung wie heute die Checkbox
   (`plugin.py:2765-2782`), sonst greift die CSS-Regel `#local_enhance_row >
   #…` nicht und das Dropdown steht in einem eigenen Wrapper.
3. **Klick-Eingaben:** Das Dropdown ist **keine** Klick-Eingabe. Die sechs
   bleiben unverändert `state, prompt, Modus, Think, Min, Max`; die Auswahl
   kommt aus der Config (`.change` schreibt `local_enhance_template`).
   `_control_components()` / `_read_controls()` werden **nicht** angefasst.
   Grund: `_read_controls()` wertet nur `bool` und Zahlen aus — ein
   Dropdown-String würde still übergangen (offener Punkt in AGENTS.md).
4. **Veraltete Einträge:** Ist der gespeicherte Name nicht mehr in der Liste
   (Datei gelöscht), zeigt das Dropdown `default`, die Config behält den alten
   Wert aber als Fallback (`_template_choice()` liefert ihn weiter, solange
   die Datei existiert).
5. **Namensregel:** `_prompt_name_ok()` erlaubt `[A-Za-z0-9][A-Za-z0-9 _.-]{0,63}`
   (max. 64 Zeichen, kein Pfadtrenner, kein führender Punkt, keine
   Leerzeichen am Rand). Groß-/Kleinschreibung bleibt erhalten; ein Name, der
   sich nur in der Schreibweise unterscheidet, überschreibt die vorhandene
   Datei (Warnung in der Statuszeile).
6. **Leere/fehlende Quelle:** `_list_prompt_names()` liefert bei fehlendem
   oder unlesbarem Ordner nur `[default]`; `*.txt`-Dateien mit leerem Inhalt
   (nach `strip()`) werden übersprungen. Sortierung: `default` zuerst, danach
   alphabetisch ohne Rücksicht auf Groß-/Kleinschreibung.
7. **Ordnerfeld:** `~` wird über `os.path.expanduser` aufgelöst; der Ordner
   wird erst beim Speichern angelegt (`os.makedirs(exist_ok=True)`). Leeres
   Feld = Standard `~/Prompts`. Nicht beschreibbarer Ordner → Statuszeile mit
   Fehler, kein Traceback, keine Datei.
8. **Migration:** läuft **nur** im Host, nie beim Import (dev-Skripte rufen sie
   nicht auf) und wird zusätzlich durch `_MIGRATE_KEY` in der Config
   abgesichert. Schreibt bei leerem Zielordner:
   `photograf.txt` = aktueller Live-Text (Inhalt von `system_prompt.txt`,
   `_SYSTEM_PROMPT_FILE`) und `sheet.txt` = `_TEMPLATE_SHEET_TEXT`.
   Danach `local_enhance_template = photograf`, außer die Auswahl zeigt schon
   auf einen gespeicherten Eintrag; das Verhalten ist identisch zu heute. Die
   Wortgrenzen-Sätze bleiben am Dateiende stehen,
   `_apply_word_limit()` ersetzt sie beim Aufruf. Die Umsetzung legt den
   Marker in `server_config` ab (`local_enhance_prompt_migrated`).
9. **dev-Skripte schreiben nie:** `ui_preview.py` setzt in der
   `server_config`-Fixture `local_enhance_prompt_migrated = True` und
   `local_enhance_prompt_dir` auf ein `tempfile`-Verzeichnis;
   `check_template_ui.py` prüft die Helfer gegen `tempfile`, ohne `~/Prompts`
   anzufassen.

## 1. Helfer (plugin.py, bei den Template-Helfern)

- `_prompt_dir()`, `_prompt_name_ok()` (max 64, dateiname-sicher),
  `_list_prompt_names()` (Scannt `<Ordner>/*.txt`, leere Dateien
  überspringen), `_read_prompt_entry()`, `_write_prompt_entry()`,
  `_migrate_library()` (einmalig, durch Marker-Key + Trigger abgesichert,
  damit dev-Skripte nie schreiben).
- Alle Helfer als `@classmethod` wie die bestehenden Template-Helfer und
  **werfen nie**: fehlende Datei, Rechte, kaputtes Encoding → `None`/leere
  Liste/Fehlertext, der Aufrufer entscheidet.
- Encoding einheitlich UTF-8, Zeilenenden `\n`, Inhalt wird beim Lesen
  `strip()`-geprüft (leer = ignorieren), beim Schreiben unverändert (ohne
  angehängte Leerzeilen).

## 2. Auflösung erweitern

- `_template_choice()`, `_template_instructions()`, `_active_template_text()`,
  `_template_status_text()` akzeptieren `default` + gespeicherte Namen
  (Legacy-Presets bleiben als Fallback); Aufrufstelle bleibt unverändert.
- Konkret: `_template_choice()` normalisiert auf `default`, wenn der Name
  nicht in `_list_prompt_names()` steht; `_template_instructions()` liest bei
  gespeichertem Namen den Dateitext (kein Config-Text mehr), bei `default`
  gilt das bisherige Verhalten für `WanGP-Standard` (kein Override).
  `_save_template()` (plugin.py:838) wird auf dieselbe Mengenprüfung
  umgestellt — das ist die eigentliche Lücke aus Punkt 1 oben.
- `_save_specific_prompt()` bleibt für alte Config-Werte lesbar, wird aber
  nicht mehr beschrieben.

## 3. Zeile 1

- Checkbox „Specific Prompt" → Dropdown (`default` + gespeicherte Namen),
  `.change` schreibt `local_enhance_template`, als Instanz-Attribut fürs Tab
  merken; CSS-Regel für die neue ID; `_toggle_sheet_template` retired;
  Klick-Eingaben bleiben 6.
- Neue `elem_id` z. B. `local_enhance_prompt_dd`; die CSS-Regel
  (`plugin.py:255`) zielt danach auf diese ID (Breite `max-content`,
  `min-width:0`) statt auf `#local_enhance_sheet_cb`.
- Unwrap: der `.form`-Wrapper des Dropdowns wird wie bei der Checkbox
  aufgelöst (Schleife über `button_row.children`, `ours`-Menge), erst danach
  darf die Think-Checkbox umgehängt werden — sonst landet das Dropdown im
  Formular-Wrapper.
- `_toggle_sheet_template` wird nicht mehr verdrahtet und ohne Ersatz
  entfernt; der neue `.change`-Handler schreibt nur die Auswahl und gibt
  `gr.update()` für die Tab-Karte zurück.

## 4. Tab-Karte

- Dropdown lädt Einträge (`default` + Namen), Name-Feld (max 64) + Speichern
  schreibt `<Ordner>/<name>.txt`, Ordner-Feld + eigener Speichern-Knopf;
  Save-Handler aktualisieren das Zeile-1-Dropdown per `gr.update`.
- Konkret: das bestehende Tab-Dropdown (`create_ui`, `choices=list(
  _TEMPLATE_PRESETS)`) wird auf `[default] + _list_prompt_names()` umgestellt;
  das Textfeld zeigt den Text des gewählten Eintrags (**nicht** editierbar
  speichern, sondern nur lesen); „Speichern unter Name" legt eine neue Datei
  an bzw. überschreibt sie. Name leer/ungültig → Statuszeile, kein Schreiben.
- „Ordner speichern" schreibt `local_enhance_prompt_dir` (expandiert), legt
  den Ordner an und aktualisiert die Dropdown-Liste; `default` bleibt immer
  wählbar und zeigt im Textfeld den Hinweis auf WanGPs Standard.
- Die Legacy-Karte (Preset-Dropdown + editierbares Textfeld + „Vorlage
  speichern"/„Zurücksetzen") wird auf die Bibliothek umgestellt; die alten
  Buttons entfallen, damit es nur **einen** Schreibweg gibt.

## 5. dev-Skripte

- `ui_preview.py` (Erwartung Zeile 1 = `[HTML, Button, Button, Dropdown,
  Checkbox]` — neu: Specific-Dropdown **plus** Think-Checkbox; Fixture-Marker
  damit nichts geschrieben wird, `_prompt_dir()` auf `tempfile`) +
  `check_template_ui.py` anpassen; Import-Check + Preview laufen lassen.
- `check_template_ui.py` bekommt Fälle für: gültiger/ungültiger Name (64/65
  Zeichen, Pfadtrenner, führender Punkt), leere Datei wird übersprungen,
  fehlender Ordner → `[default]`, `~`-Auflösung, Migration schreibt nur
  einmal (Marker), `_template_choice()` fällt bei gelöschter Datei auf
  `default` zurück.

## 6. AGENTS.md / Commit

- **AGENTS.md** aktualisieren (Zeile 1, Klick-Eingaben, Tab-Karte,
  Prompt-Ordner, Migration), Commit im Quellrepo; `system_prompt.txt`
  (uncommitted) separat committen.
- Reihenfolge: erst `plugin.py` + dev + PLAN/AGENTS (ein Commit), dann
  `system_prompt.txt` separat. Kein Force-Push.

**Migration:** beim ersten Start werden `photograf.txt` (aktuelle Live-Text)
und `sheet.txt` (Sheet-Text) in den Speicherordner geschrieben; die Auswahl
heisst danach `photograf` — das Verhalten ist dann identisch zu heute.
