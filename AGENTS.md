# AGENTS.md — WanGP-Plugin „Enhance: OpenCode / Bonsai 27B"

Kurzfassung für jede Session in diesem Repo. Was der Code tut, steht im Code —
hier steht nur, was man sonst mühsam herausfinden muss.

## Was das Plugin tut

Zwei Knöpfe neben WanGPs „Enhance Prompt":

- **OpenCode** — verbessert remote über die konfigurierte Engine
  (`process_prompt_enhancer()` erkennt am Engine-Namen, dass remote gearbeitet
  wird, `wgp.py:6409`).
- **Local 27B** — lädt Qwen3.8-27B lokal (`enhancer_enabled=5`, `gguf_ptq1`) und
  gibt den VRAM danach wieder frei. Im Modus *Based on Text Prompt and Images*
  (`"I"` im Modus) liest dieser Knopf zusätzlich die ausgewählten Bilder mit dem
  Vision-Teil des Modells (Start-/Endbild, Referenzen, Control Image) und nennt
  sie in der Statuszeile; alle anderen Modi bleiben text-only.

Der **Modus** (WanGPs Dropdown „Enhance Prompt using a LLM") gilt für beide
Knöpfe und kommt **live** aus WanGPs verstecktem `prompt_enhancer`-Text — auch
`"K"` aus der Think-Checkbox steckt darin. Nur wenn dieser Wert leer ist
(„Disabled" gewählt) oder die Komponente fehlt, fällt das Plugin auf den
Modell-Default zurück (`_resolve_mode`). Ein **veralteter** Live-Wert (vom
vorigen Modell, z. B. `T` an YuE2) wird gegen die Modell-Auswahl geprüft und
verworfen — sonst fehlt das Profil (`…instructions1`) und statt Lyrics entsteht
eine allgemeine Audio-Stilbeschreibung.

Modelle mit **zwei** Textfeldern (YuE2: `prompt` = Lyrics, `alt_prompt` =
Music Style) bekommen das zweite Feld als Klick-Eingabe. Das Plugin folgt
WanGPs Routing (`T`/`L`/`B`, `O` schreibt `alt_prompt`, Komma = Kette) über
`prompt_enhancer_chaining`: `T1` schreibt Lyrics, `B2O` den Music Style,
`T1,B2O` beides nacheinander — der Style-Schritt sieht die **neuen** Lyrics als
JSON-Kontext. Die Anweisungen kommen aus der Modelldefinition; das Plugin
übergibt nur den Fallback.

Drei Regler, alle gelten für **beide** Knöpfe:

- **Think** — WanGPs eigene Checkbox (Zeile 1). Gesetzt: lokal `K` im
  Enhancer-Modus (`wgp.py:6451` → `thinking_enabled`), remote der höchste
  `reasoning_effort` des Modells als `variant` (`opencode_backend.py:226`).
  Ungesetzt: kein Denken lokal, niedrigster Level remote (Anbieter haben kein
  echtes „aus").
- **Min words** / **Max words** — zwei `gr.Number`-Felder ganz oben im
  Plugin-Tab, nebeneinander. Sie ersetzen die feste 150-Wort-Grenze in WanGPs
  Anweisungen (`shared/prompt_enhancer/prompt_enhance_utils.py:25/34/42/51/56`):
  beide gesetzt → „Keep between MIN and MAX words.", nur Max → wie bisher, nur
  Min → „Write at least MIN words.", beide 0 → die Sätze werden entfernt
  (0 = keine Grenze). Aufgelöst wird das in `_read_controls()`; ein
  Preset-Dropdown gibt es nicht mehr. Das Token-Budget wächst mit
  (`_output_token_budget`), sonst schneidet das 512-Token-Limit den Prompt ab.
- **Specific Prompt** — das Dropdown in Zeile 1 (früher die Checkbox). Es zeigt
  `default` plus die Namen aus `<Prompt-Ordner>/*.txt`; `default` heißt:
  WanGPs normaler System-Prompt, kein Override. Die Wahl landet in
  `local_enhance_template` und gilt für **beide** Knöpfe. Der Ordner ist
  installationsweit einstellbar (Standard `~/Prompts`).
  Die Tab-Karte beginnt mit zwei Sätzen, was das Plugin tut (keine
  `System Prompts`-Überschrift, rechts Build-Stempel). Reihenfolge:
  `Saved prompt` + `Folder` + `↻` + `Save`; `System prompt (result,
  editable)`; `What should the final prompt look like?`; Abschnitt „In case you
  want to empower another AI model to enhance the system prompt:" mit
  `Model`/Min/Max, **`Model guidelines (optional)`** (das einzige
  Guidelines-Feld, `Load WanGP default`), dann **Enhancer**
  (`Enhancer`, `Local model` bzw. `API model`, rechts `Configure` über
  `Generate`), der große Ergebnis-Editor, Status + `Save as`.
  **Import prompts** ist aufgeklappt (`Load .txt` = eine Datei,
  `Import folder` = alle `.txt` eines Ordners).
  Wählt man `OpenAI-compatible API`, erscheint nur `API model` + `Configure`;
  die Verbindung (`Provider` Ollama/LM Studio/OpenAI/Custom, `Base URL`,
  `API key`, `Remember API key`, `Test connection`) öffnet der Knopf.
  Der API-Key wird **nur** mit `Remember API key` in der Config gespeichert,
  sonst nur im Prozess gehalten. `Save as` öffnet ein Namensfeld
  (vorbefüllt); erst der zweite Klick schreibt `.txt` + Sidecar. `default`
  ist reserviert; das Sidecar `<name>.json` hält `model`, `description` und
  (Altbestand) `tags`.

Unter den beiden Feldern steht der **Modell-Check**: die englische Hinweiszeile
(`_MODEL_CHECK_HINT`), darunter die immer sichtbare Zeile zum **aktuellen**
Modell, dann ein eingeklapptes `Which models ignore Min/Max?` mit dem Knopf
*Check models*, einer Statuszeile und der Liste. Beim Aufbau des Tabs wird
**nichts** berechnet: die Zeile zum aktuellen Modell kommt live aus dem
Host-Zustand, Liste und Status aus den **strukturiert** abgelegten Familien in
`enhancer_models.json` neben `plugin.py` — den Anzeigetext rendert erst der
Tab-Aufbau. Erst der Klick auf *Check models* liest den Katalog
(`_main("models_def")`, nur lesen), zählt, rendert und schreibt die Datei. Die
Liste nennt die Modelle, deren Definitionen eigene Enhancer-Anweisungen
mitbringen — dort gewinnen sie gegen die vom Plugin übergebenen
(`_fallback_instructions`), Min/Max wirken also nicht.

## Zwei Klone — die wichtigste Regel

| Ort | Rolle |
|---|---|
| `~/git/wan2gp-local-enhance` | **Quelle der Wahrheit** — hier editieren, committen, pushen |
| `~/git/Wan2GP/plugins/wan2gp-local-enhance` | **wird von WanGP geladen** (eigener Klon, Eintrag `installed_remote_plugins`) |

Nie im geladenen Klon editieren — das nächste Update überschreibt es. Genau diese
Doppelablage hat schon zweimal zu Fehldiagnosen geführt.

**Ablauf:** pushen → *Update* in WanGP auslösen → **WanGP neu starten**. Plugins
werden beim Start einmal importiert; ein laufender Prozess behält den alten Code.
Der Updater ist ein reines `origin.pull()` (`shared/utils/plugins.py:1327`) und
scheitert an einem dirty working tree — den geladenen Klon also sauber halten.

Es gibt **kein** Hot-Reload für Plugins: `load_plugins_from_directory` läuft nur
beim Start (`shared/utils/plugins.py:1489/1511`, Aufruf `wgp.py:13820`). Der
Knopf *Restart* im Plugin-Manager ist der einzige Weg aus der UI — er läuft über
den Gradio-Endpunkt `_handle_save_action` → `restart_application()`
(`wgp.py:2310`) → `os._exit(42)` und braucht deshalb einen Aufpasser, der den
Prozess neu startet. Bei von Hand gestartetem `python wgp.py` also: beenden und
neu starten.

## Stand

- `212cb3e` — zwei Knöpfe, Tooltips, Remote-Fix (das Plugin liefert
  Ersatz-Anweisungen, weil die meisten Modelle keine definieren)
- `6fb5862` — Think-Checkbox gilt für beide Knöpfe (läuft)
- `6d48958` — Feld „Max words" (ein Feld, ersetzt durch Min/Max)
- `4570807` — Min/Max-Umbau: zwei Felder auf Zeile 2, Sätze je Kombination,
  Token-Budget wächst mit Max
- `d429ffb` — diese Anleitung ins Repo (vorher untracked)
- `2f6f3e6` — Min/Max kompakt: Gradio-Label `min:`/`max:` über der Eingabe,
  Felder per CSS auf 84px, `_UI_CSS` als Modulkonstante, `dev/ui_preview.py`
  (die 84px-Regel ist seit `39dbd33` weg, die Breite kommt aus `min_width`)
- `61f25ae` — Wortgrenze als Preset-Dropdown (`no limit` / `150` / `300` / `500`
  / `custom`), Custom blendet die Zahlenfelder ein; `_read_controls` löst das
  Preset auf, `dev/ui_preview.py` kann per `PREVIEW_MAX` beide Fälle zeigen
- `40215b9` — Zeile 2 ausgerichtet: Modus-Dropdown bekommt WanGPs Caption zurück
  (`show_label=True`), Zahlenfelder auf Gradio-Maß (gleiche Höhe/Grundlinie wie
  die Dropdowns), Captions `Words`/`Min`/`Max`; Vorschau baut den
  On-Demand-Fall (`show_label=False`) nach
- `084acf1` — Vision im Local-27B-Aufruf: Bilder live aus den Komponenten
  (`_IMAGE_INPUT_NAMES` als Klick-Eingaben), Aufbereitung über
  `prepare_manual`/`image_contexts` mit Fallback, IT2I/IT2V-Anweisungen,
  Bildhinweis in der Statuszeile, `dev/check_vision_inputs.py`
- `0dde6f4` — Modus-Fix: der Modus kommt live aus WanGPs verstecktem
  `prompt_enhancer`-Text (`request_component`, `_mode_components`,
  `_split_mode_input`, `_effective_mode`), `_resolve_mode` ist nur noch Fallback
  bei leerem Wert. Beide Knöpfe hatten dadurch **7** Klick-Eingaben
  (`state, prompt, Modus, Think, Preset, Min, Max`), der lokale **7 +
  Bild-Eingaben**; seit `e5ed6d8` sind es **6**
  (`state, prompt, Modus, Think, Min, Max`), das
  Preset ist weg. Mit dem zweiten Textfeld (`alt_prompt`, bei YuE2 „Music
  Style") sind es **7** bzw. **7 + Bild-Eingaben**; die Komponente existiert in
  WanGP immer, ist ohne `alt_prompt`-Definition aber unsichtbar. Vorher stand
  im Klick immer der Modell-Default, wodurch Modelle mit erstem Modus `"T"`
  (`qwen_image_21_7B`) die Bilder verwarfen.
- `e5ed6d8` — Wortgrenze in den Plugin-Tab: Preset-Dropdown entfernt, Min/Max
  als zwei Felder im Tab, `_UI_CSS` und `dev/ui_preview.py` angepasst
- `b758ac5` — Modell-Check-Kern: `_collect_enhancer_overrides()` sammelt die
  Modelle mit eigenen Enhancer-Anweisungen, dazu
  `dev/check_enhancer_overrides.py` und Testnacharbeit
- `a137980` — Tab-Hinweis und Modell-Check im Tab: Accordion mit dem Knopf
  *Check models*, Zwischenspeicher `enhancer_models.json` (in `.gitignore`) und
  die Liste daraus
- `39dbd33` — Felder nebeneinander (`min_width` statt CSS), Ziffernsuffixe im
  Schlüsselmuster, Dateizähler über den Pfad des Hauptmoduls, Kommentare
- `144c206` — Modell-Check lesbar: Zeile zum aktuellen Modell immer sichtbar,
  Familien gebündelt (eine Zeile je Familie, Zähler nur bei mehreren Varianten),
  Liste in scrollbarer Box mit Inline-Stil und fester Höhe, Knopf einzeilig
- `b0bd5ba` — Zwischenspeicher des Modell-Checks **strukturiert**: die Datei hält
  Gruppen mit Name, Variantenzahl und internen Typen plus Format-Kennzeichen
  statt des fertigen Listentexts; den Anzeigetext rendert der Tab-Aufbau, ein
  alter oder fremder Stand gilt als „noch nicht geprüft" und zeigt den
  Ersatztext
- `73fd23d` — Stand der Anleitung nachgezogen: Modell-Check mit Modellzeile und
  gebündelter Liste
- `0a21eb0` — Prompt-Bibliothek: Zeile-1-Checkbox durch Dropdown ersetzt
  (`default` + `<Ordner>/*.txt`), Tab-Karte mit Ordner-/Namensfeld und
  Speichern, einmalige Migration (`photograf` + `sheet`), Helfer und Tests
- `ecdd36b` — `system_prompt.txt` auf den Photographer-Prompt umgestellt
  (Quelle für `photograf.txt` bei der Migration), separat committet
- `3086f83` — UI-Texte der Bibliothek und der übrigen Karten auf Englisch
  (wie der Rest von WanGP); alte deutsche Preset-Namen bleiben als
  Config-Aliase lesbar
- `bb23c0b` — Bibliotheks-Zeile kompakt: Ordner, Name und Wortgrenzen in einer
  Reihe, dazu `Reload folder` und `Import prompt...` (bestehende `.txt`
  landet im Ordner); `_flatten_row` löst die Gradio-Form-Wrapper
- `92ee268` — UI-Feinschliff nach Screenshot: Bibliothek in zwei ausgerichtete
  Zeilen (Ordner + Save/Reload/Import, darunter Name + Save as name + Min/Max),
  Textfelder wachsen per CSS, Dropdown heisst `Edit prompt`, Hinweis
  „Edits apply only after Save as name."
- `17a0b20` — **System Prompts** neu: Karte mit Folder / Load / Import folder /
  Reload, Entry + Model + Min/Max, `Show prompt guidelines`, Editor mit
  `Author model` + `Enhance`, Tags, Save-Dialog; Sidecar `<name>.json` mit
  Modell + Tags; Autor lokal (27B) oder OpenAI-kompatible API
- `16d0890` — Importe ins Accordion (**Import prompts**), API-Verbindung
  sichtbar bei `OpenAI-compatible API`: Provider-Presets (Ollama/LM Studio/
  OpenAI/Custom), Base URL, Key, Model, `Test connection` (`GET /models`)
- `511653b` — Tags → Freitext **What should this system prompt do?**
  (Sidecar `description`), `Author model` + `Generate` direkt daran;
  `API model` + `Configure` in der Hauptansicht, Verbindung nur im
  Dialog; API-Key nur mit `Remember API key` gespeichert
- `88f150b` — zweispaltige Karte: links Beschreibung + editierbares
  Guidelines-Feld mit `Load WanGP default` (lädt die WanGP-Anweisungen,
  eigene Eingabe gewinnt), rechts die Box **AI to generate** mit
  `Local / provider`, `API model`, `Configure`, `Generate`
  (seit `2d81151` wieder ersetzt)
- `2d81151` — Karte senkrecht: `Folder` wieder sichtbar, Enhancer-Zeile
  (`Enhancer`, `API model`, `Configure`, `Generate`) direkt unter der
  Beschreibung, `AI to generate` entfernt; Label
  `What should the final prompt look like?`; Defaults 100/350
  plus einmalige Migration von 0/150
- `00de323` — `Configure` über `Generate` gestapelt (150px-Spalte),
  **Import prompts** aufgeklappt, `Save as` schlägt
  `_next_free_prompt_name()` vor (`Charactersheet 2`) statt den bestehenden
  Eintrag zu überschreiben
- `fe02028` — **Lyrics/Music Style (YuE2):** `alt_prompt` als Klick-Eingabe und
  Ausgabe, Modus gegen die Modell-Auswahl geprüft (altes `T` wird `T1`),
  Ketten über `prompt_enhancer_chaining` (`T1`, `B2O`, `T1,B2O`), Status nennt
  die geschriebenen Felder, Local API nutzt dieselben Modell-Anweisungen;
  `dev/check_music_fields.py` + `dev/check_music_wiring.py`
- `45a12a0` — **Music-Style-Tag-Baukasten:** fünfte Karte bei Audio-Modellen mit
  Musik-Feld, Dropdowns (Language/Genre/Vocals/Instruments/Mood/Tempo/
  Production), Live-Vorschau, `Apply`/`Append`/`Clear`, eigene
  `music_style_tags.json` im Prompt-Ordner, Sichtbarkeit über
  `refresh_form_trigger` und `on_tab_select`; `dev/check_music_tags.py`
- `04688f1` — **Lyrics-Struktur:** `Section plan (optional)` mit
  `Load from ABC`, ABC-`%`-Labels zu `[Intro]`/`[Verse]`/…, automatisch aus der
  gewählten ABC-Quelle, Kontext vor dem Lyrics-Prompt bei `T1`/`T1,B2O` (nicht
  bei `B2O`), Config-Key `local_enhance_lyrics_structure`
- **Autor-Parameter:** `Max answer tokens`, `Temperature`,
  `Reasoning effort` und `Extra body` landen im API-Payload
  (`_author_api_payload`); `Local model` wählt 9B/27B nach VRAM
  (`_author_local_enhancer_id`, Schwelle 16 GB), `Detect` findet lokale
  Server auf Loopback und LAN. `Model guidelines (optional)` und steht beim Zielmodell, nicht an der
  API-Verbindung.
- **Push-Zustand:** `main` und `origin/main` sind synchron; alle hier
  gelisteten Commits sind gepusht (kein Force-Push, kein Rebase). Der Stand
  unten beschreibt also `origin/main`, nicht einen lokalen Vorlauf.
- **Nach dem Neustart prüfen:** `local_enhance_remote_btn` **7 Inputs**
  (`state, prompt, Modus, Think, Min, Max, alt_prompt`),
  `local_enhance_local_btn` **7 + Anzahl der Bild-Eingaben** des Modells, das
  **Specific-Prompt-Dropdown** in Zeile 1 (zeigt nach der Migration
  `photograf`; `default` = kein Override), die Karte **System Prompts** mit
  `Folder` + `Reload`, Werkzeugzeile (`Entry` / `Model` / Min / Max),
  Beschreibungsfeld, `Model guidelines (optional)` (mit
  `Load WanGP default`), Zeile **Enhancer** (`Enhancer`,
  `Local model` bzw. `API model`, `Configure` über `Generate`),
  Ergebnis-Editor und Status + `Save as`
  (öffnet den Namensdialog), keine `gr.Form`-Wrapper —, das Accordion
  **Import prompts** und bei `OpenAI-compatible API` die
  Verbindungsgruppe (`Provider` / `Base URL` / `API key` /
  `Remember API key` / `Detect` / `Test connection`, `Max answer tokens`,
  `Temperature`, `Reasoning effort`, `Extra body (JSON, optional)`),
  darunter die Zeile zum aktuellen
  Modell (live, beim Tab-Wechsel neu), der Modell-Check (Klick auf
  *Check models* füllt Status und Liste; ein alter Zwischenspeicher zeigt
  vorher den Ersatztext statt einer Textwand), und der Vision-Lauf aus
  „Prüfen".

## Technisches, das man sonst neu herausfinden muss

- **Nur ein lokaler LLM-Slot:** `resolve_role_engine()` ignoriert die Rolle. Das
  Plugin stellt `llm_engines.deepy` und `enhancer_enabled` nur für den Klick um
  und restauriert danach exakt.
- **Enhancer-Modus kommt live aus WanGPs verstecktem `prompt_enhancer`-Text**
  (`wgp.py:12169`); aktuell gehalten wird er vom sichtbaren Dropdown und der
  Think-Checkbox (`wgp.py:13036-13037`), und WanGPs eigener Enhance-Knopf
  bekommt genau diese Komponente als Klick-Eingabe (`wgp.py:13189`). Das Plugin
  fragt sie in `setup_ui` an (`request_component("prompt_enhancer")`) und hängt
  sie als **erste** Klick-Eingabe an beide Knöpfe; `_effective_mode()` nimmt
  ihren Wert. Erst wenn er leer ist (Nutzer hat „Disabled" gewählt, oder die
  Komponente fehlt), greift `_resolve_mode()` als Fallback — also der
  Modell-Default, `default` bzw. `choices[0]`. Vorher stand dort **immer** der
  Default: bei Modellen, deren erster erlaubter Modus `"T"` ist
  (`qwen_image_21_7B`), verwarf `_enhancer_images()` deshalb die Bilder
  (`"I" not in mode`) und `_fallback_instructions()` schickte `T2I` statt `IT2I`.
  Reihenfolge: der PluginManager setzt die angefragten Komponenten **vor** der
  Insert-Verarbeitung (`shared/utils/plugins.py:1627` vor `1657`), beim
  Verdrahten in `create_inline_button` liefert `_mode_components()` also schon
  genau 1 Komponente (siehe `dev/ui_preview.py`).
- **Aufruf:** `process_prompt_enhancer(model_type, model_def, mode, [prompt],
  image_start, image_refs, is_image, audio_only, -1,
  prompt_enhancer_instructions=…, text_encoder_max_tokens=…,
  enhancer_kwargs=…)`.
- **Bilder (nur lokal, nur `"I"` im Modus):**
  - Der Vision-Tower gehört für `enhancer_enabled` 3/4/5 immer zum Ladepfad
    (`shared/prompt_enhancer/loader.py:213-230`, 27B-Datei
    `Qwen3.8-27B-Uncensored-vision-f16.gguf`, `assets.py:42`) — das Plugin
    aktiviert ihn also nicht, es benutzt ihn nur.
  - WanGPs Bedingung für den Bildpfad ist `"I" in mode` **und**
    `enhancer_enabled in (3,4,5)` **und** lokale Engine
    (`images.py:21`). Das Plugin erfüllt sie, weil es beides für den Klick
    umstellt (`enhancer_enabled=5` + `llm_engines.deepy`), und wertet die Bilder
    erst **nach** dem Umstellen aus.
  - Die Bilder kommen **live aus den Komponenten** (`_IMAGE_INPUT_NAMES`, als
    zusätzliche Klick-Eingaben). Der Settings-Snapshot
    (`state["all_settings"]`) taugt dafür nicht: er wird nur von
    `save_inputs()`-Flüssen geschrieben, nicht beim Hinzufügen eines Bildes zur
    Galerie (`shared/gradio/gallery.py:236-273`) — WanGPs eigener Knopf ruft
    deshalb extra `save_inputs()` davor auf (`wgp.py:13215`).
  - Aufbereitung wie `enhance_prompt()` (`wgp.py:6629-6682`): erst
    `prompt_enhancer_images.prepare_manual(...)` → `image_contexts` mit Labels
    (Start-/Endbild, Referenzen, Control Image); schlägt das fehl, Fallback auf
    die einfache Auswahl (Start-/Endbild + erste Referenz, ohne Kontexte).
    Die Kontexte gehen als `enhancer_kwargs["image_contexts"]` hinein und werden
    intern nur benutzt, wenn `images.enabled()` gilt (`wgp.py:6389`).
  - Geometrie-Felder (`force_fps`, `video_length`, `sliding_window_*`,
    `video_guide`, `video_source`, `frames_positions`, `multi_prompts_gen_type`,
    `multi_images_gen_type`) kommen weiter aus dem Snapshot — sie beeinflussen
    nur Labels/Fenster, nicht *welche* Bilder gesendet werden.
  - `fake_start_image` wird im On-Demand-Pfad **nicht** gefiltert: `prepare_manual`
    verwirft es nur im Sliding-Zweig (`images.py:201`), der Nicht-Sliding-Zweig
    und `enhance_prompt()` nutzen das Bild (`images.py:233`, `wgp.py:6633`);
    nur der Auto-Pfad filtert (`wgp.py:7540`). Das Plugin verhält sich wie der
    On-Demand-Pfad.
  - Mit Bildern gelten die Bild-Anweisungen `IT2I_VISUAL_PROMPT` /
    `IT2V_CINEMATIC_PROMPT` statt `T2I`/`T2V`; beide enthalten dieselben
    Wortgrenzen-Sätze, `_apply_word_limit` greift weiter.
  - Nur der lokale Pfad bekommt Bilder; der OpenCode-Knopf bleibt text-only.
- **Startreihenfolge:** `create_inline_button` (`wgp.py:13628`) läuft **vor** den
  Plugin-Tabs (`wgp.py:13976`). Deshalb sitzen Knöpfe, Specific-Prompt-Dropdown
  und Think-Checkbox in Zeile 1, während die Wort-Regler und der Tab-Knopf erst in `create_ui()`
  dazukommen: `_attach_word_fields()` holt die beiden Felder in den Tab, der
  Tab-Knopf wird dort mitverdrahtet.
- **`insert_after`** verschiebt nur das **zuletzt erzeugte** Kind
  (`shared/utils/plugins.py:1659`). Nichts direkt in `parent` erzeugen, sonst
  wandert das Falsche.
- **Gradio-Fallen (alle live verifiziert):**
  - `gr.Number`/`gr.Checkbox` werden in einen `gr.Form` gruppiert, und zwar pro
    Lauf **aufeinanderfolgender** Formularfelder. Ein `gr.HTML` dazwischen
    zerreisst den Lauf → **mehrere** Wrapper. Der Code löst deshalb alle Wrapper
    in einer Schleife auf (`ours = {id(child) …}`).
  - Beim Verschieben aus der Reihe in den Dropdown-Container **zuerst aus
    `button_row.children` entfernen**, sonst steht die Komponente in zwei Eltern
    gleichzeitig (im Layout doppelt sichtbar).
  - Gradio setzt `width:100%` **und** ein Inline-`min-width` (Default 160px, aus
    `min_width`) auf die Kinder. Breiten deshalb per CSS mit `!important`
    vorgeben, wo eine feste Breite nötig ist — das schlägt auch das
    Inline-Style. Betroffen sind nur noch Reihe, Think-Checkbox und das
    Specific-Prompt-Dropdown (`.local-enhance-label`, `.cbx_centered`,
    `#local_enhance_prompt_dd`). Die beiden Wort-Regler brauchen keine Regel:
    sie bekommen ihre Breite über `min_width=_WORD_FIELD_WIDTH` (120px) plus
    `scale=0`. Das Dropdown bekommt eine feste Breite (220px, min 160px, max
    260px) statt `max-content`: die Namen dürfen 64 Zeichen lang sein,
    `max-content` würde die Zeile sprengen. `_UI_CSS` enthält damit fünf
    Regeln: den Originalknopf ausblenden, Zeile 1 umbrechen lassen, die Breiten
    von Label, Think-Checkbox und Dropdown und die volle Breite der fremden
    Formularzeile (`#local_enhance_row + .form`, inzwischen nur noch das
    Modus-Dropdown).
  - **Höhe und vertikales Padding der Eingaben bleiben Gradios Vorgabe.** Eigene
    `input{padding…; font-size…}`-Regeln machten die Felder früher niedriger als
    ihre Nachbarn (live 21px statt 33px) und rissen die gemeinsame Grundlinie
    ein — es gibt deshalb keine solchen Regeln mehr. Die Breite kommt aus
    `min_width`: die beiden Wort-Regler sind je rund 120px breit (Block,
    `min(120px, 100%)`; die Eingabe darin 94px), stehen auf derselben
    Grundlinie, und `input.scrollWidth - clientWidth` ist 0 — sonst wäre „1500"
    abgeschnitten (live gemessen).
  - **Captions sind `<span data-testid="block-info">`** im Kopf des Blocks, nicht
    das `<label>` — Letzteres umschliesst bei `gr.Number` die Eingabe. Wer die
    Caption stylen will, darf nicht `… label{…}` schreiben; die Schriftgrössen
    sind ohne Zutun schon einheitlich.
  - **WanGP versteckt die Caption des Modus-Dropdowns**, wenn der Enhancer
    on-demand läuft (`wgp.py:12174`: `show_label = not on_demand_prompt_enhancer`).
    Ohne Caption sitzt dessen Eingabe 32px höher als unsere beschrifteten Regler
    (live gemessen: y665 gegen y697) — genau der schiefe Screenshot. Das Plugin
    schaltet WanGPs eigene Caption deshalb in `create_inline_button` ein
    (`mode_dropdown.show_label = True`). Ein
    Modellwechsel setzt sie nicht zurück: `refresh_prompt_enhancer_labels`
    schickt nur `choices` (`wgp.py:10898`).
  - Die Wort-Regler nutzen **Gradios eigene Captions** (`label="Min words"` /
    `"Max words"`, `show_label=True`): sie stehen direkt über der Eingabe,
    kosten keine eigene Komponente und halten die Formulargruppe zusammen. Die
    früheren `gr.HTML`-Beschriftungen sind weg — genau deshalb ist der
    Unwrap-Code jetzt kurz.
  - Die beiden Felder entstehen in `create_inline_button()` (die Knöpfe in
    Zeile 1 brauchen sie dort schon als Klick-Eingaben), werden dort aus ihrem
    `gr.Form`-Wrapper gepackt und in der Knopfreihe geparkt
    (`self._word_fields_home`); `create_ui()` holt sie mit
    `_attach_word_fields()` in den Tab. Das muss **nach** dem Verlassen des
    `with gr.Row()`-Blocks passieren: beim Verlassen gruppiert Gradio
    aufeinanderfolgende Formularfelder in einen `gr.Form`, und der stapelt seine
    Kinder vertikal — Min und Max stünden sonst untereinander statt
    nebeneinander. Prüfwerkzeug: `dev/ui_preview.py`.
  - Die Regler werden **nach Typ** ausgelesen (`*controls`), weil die
    Think-Checkbox fehlen kann: `bool` = Think, Zahlen = die beiden Wort-Regler
    (erst Min, dann Max); ein einzelnes Zahlenfeld gilt weiter als Obergrenze
    (Altbestand). Feste Reihenfolge der Klick-Eingaben:
    `state, prompt, Modus, Think, Min, Max, alt_prompt` → **7**. Der Modus-String
    wird vorher mit `_split_mode_input()` abgezogen, die Bilder trennt
    `_split_image_inputs()` von rechts ab, den Alt-Text `_split_alt_input()`.
    `alt_prompt` existiert in WanGP für **jedes** Modell (bei fehlender
    `alt_prompt`-Definition nur unsichtbar), deshalb steht die Komponente immer
    in der Verdrahtung; `_alt_prompt_component()` liefert sie oder `None`.
  - Die Feldnamen des Modells liefert `_field_labels()` (`prompt_class` bzw.
    `alt_prompt.label`), die Statuszeile nennt die tatsächlich geschriebenen
    Felder über `_field_note()`.
- **Modell-Check im Tab:** Der Knopf liest `_main("models_def")` **nur** — kein
  `refresh_model_defs()`, kein `map_family_handlers()`, kein Import von
  Host-Modulen. Beides wäre hier falsch: `refresh_model_defs()` löst den ganzen
  Katalog neu auf (jede Definitionsdatei plus Familien-Handler, `wgp.py:3295`)
  und bindet die globale `models_def` neu (`wgp.py:3351`), ohne Lock, mitten im
  laufenden Host; `map_family_handlers()` ruft `query_supported_types()` jedes
  Handlers, und der LTX2-Handler verschiebt dort beim ersten Mal LoRA-Dateien
  auf der Platte (`models/ltx2/ltx2_handler.py:409-429`, `shutil.move`).
  Erkennung: regulärer Ausdruck über
  `text_/image_/video_prompt_enhancer_instructions` mit beliebigem
  Ziffernsuffix — die zugehörigen `*_max_tokens*`-Schlüssel dürfen **nicht**
  treffen. Gruppiert wird nach der Medienart aus `metadata.main_output`
  (`Image`, `Image + Video`, `Video`, `Audio`, innerhalb Audio nach
  `family_label` wie `TTS`/`Music`), Anzeigename ist `name`,
  `visible == False` wird übersprungen. Gebündelt wird über
  `_enhancer_base_model_type()` — `metadata.base_model_type`, sonst
  `architecture`, zuletzt der interne Typ; eine Zeile je Familie, der Zähler nur
  bei mehreren Varianten. Ergebnis und Status landen in
  `enhancer_models.json` neben `plugin.py` (Name in `.gitignore`, damit
  Testläufe und der geladene Klon sauber bleiben). Gespeichert wird
  **strukturiert**: `format` (aktuell `enhancer-models/2`) plus `groups` aus
  `{label, families: [{name, count, model_types}]}` — der fertige Listentext
  steht **nicht** mehr in der Datei. `_cache_groups()` prüft Kennzeichen und
  jeden Eintrag defensiv; ein alter Stand (nur `list`), ein unbekanntes
  Kennzeichen oder unbrauchbare Struktur ergibt `None` und damit denselben
  Ersatztext wie „noch nie geprüft". Fehlende, leere, kaputte oder fremdformatige
  Dateien werfen nie.
- **Zeile zum aktuellen Modell (live, nicht zwischengespeichert):** sie steht
  ausserhalb des eingeklappten Bereichs direkt unter der Hinweiszeile und
  antwortet auf die eigentlich interessante Frage. Den internen Typ holt
  `_resolve_current_model_type()` in drei Stufen: `get_state_model_type(state)`
  (`wgp.py:356-358`), sonst `state["model_type"]` bzw. `state["edit_model_type"]`
  direkt aus dem Snapshot, sonst `server_config["last_model_type"]`
  (`wgp.py:10728` schreibt, `wgp.py:3366` liest). „Eigene Anweisungen?" entscheidet
  `_has_enhancer_instructions()` gegen `_main("models_def")` — nur lesen, wie beim
  Knopf. Jede Stufe steht in `try/except`: fehlt der Typ oder der Katalogeintrag,
  steht dort `**Current model:** unknown.` statt eines Fehlers. Neu berechnet wird
  die Zeile bei jedem Tab-Aufbau **und** bei jedem Tab-Wechsel: `create_ui()` setzt
  `self.on_tab_outputs = [text_in, current_model_out]`, der Host verdrahtet
  `tab.select` → `_handle_one_tab_selection` → `on_tab_select(state)` mit genau
  diesen Ausgaben (`shared/utils/plugins.py:1797-1804` und `1835-1843`), und
  `on_tab_select()` gibt `(Prompt, Modellzeile)` zurück.
- **Warum es den Check gibt:** ein Teil der Modelldefinitionen bringt eigene
  Enhancer-Anweisungen mit (Grössenordnung: gut ein Drittel des Katalogs — im
  Nachbau dieses Checkouts mit 238 Definitionsdateien 90 betroffene). Der Host
  bevorzugt sie gegen die vom Plugin übergebenen, Min/Max wirken dort also
  nicht. Die genaue Zahl nennt die Statuszeile beim Klick selbst
  („<betroffen> von <untersucht> model definitions"). Die Liste wird
  **erzeugt**, nicht gepflegt — mit neuen Modellen wächst sie von selbst mit.
- **System Prompts (Bibliothek):** Der Ordner kommt aus
  `local_enhance_prompt_dir` (Default `~/Prompts`, `~` wird expandiert),
  eine Datei pro Eintrag (`<name>.txt`, UTF-8) plus Sidecar `<name>.json`
  mit `{"model": "<interner Typ>", "description": "...", "tags": [...]}`.
  Die `.txt` bleibt ein reiner Prompt; fehlt das Sidecar, gelten Modell `""`,
  leere Beschreibung und keine Tags. Ein altes Sidecar mit nur `tags` wird
  als Beschreibung gelesen (`", ".join(tags)`).
  `_read_prompt_meta()`/`_write_prompt_meta()` fangen kaputte Dateien ab,
  leer = Sidecar löschen. `_prompt_name_ok()` erlaubt `[A-Za-z0-9][A-Za-z0-9
  ._-]*`, max. 64 Zeichen, kein Pfadtrenner, kein führender Punkt, kein `..`,
  `default` ist reserviert. `_list_prompt_names()` überspringt leere Dateien,
  sortiert alphabetisch; fehlender Ordner → `[]` (nur `default`).
  `_template_choice()` löst `default`, gespeicherte Namen und die alten
  Presets (`Character Sheet`, `Turnaround`, `Eigene Vorlage`) auf;
  Unbekanntes fällt auf `default`. `_template_instructions()` liest bei einem
  gespeicherten Namen die Datei (`None`, wenn sie fehlt), `default` liefert
  `None` (= Host entscheidet). `_save_template()` prüft gegen `default` +
  `_list_prompt_names()` + Altbestand.
  Die Karte ist die einzige Pflegestelle: `Saved prompt` + `Folder` + `↻` +
  `Save` (Enter speichert ebenfalls), `System prompt (result, editable)`,
  `What should the final prompt look like?`, Abschnitt `Target model` mit `Model`/Min/Max, `Model guidelines (optional)`
  mit `Load WanGP default`, dann **Enhancer** (`Enhancer`,
  `Local model` bzw. `API model`, rechts `Configure` über `Generate`),
  Ergebnis-Editor, Status + `Save as`. Importe im aufgeklappten Accordion
  **Import prompts** (`Load .txt` = eine Datei, `Import folder` =
  Verzeichnis-Upload aller `.txt`).
  `Save as` füllt **nie** den bestehenden Namen ein, sondern
  `_next_free_prompt_name()` (`Charactersheet 2`, `… 3`, …) - der alte
  Eintrag bleibt also unberührt, ein neuer Stand wird zur neuen Datei. Wer
  denselben Namen eintippt, überschreibt bewusst.
  `Load WanGP default` füllt das Feld aus `_model_guidelines()`; ein
  nicht-leeres Feld **gewinnt** gegen die WanGP-Anweisungen
  (`author_system_prompt(..., guidelines=...)`), leer = WanGP. Ein
  Modellwechsel leert das Feld wieder.
  `_model_choices()` liest `_main("models_def")` (nur lesen), nimmt
  `name` als Label und den internen Typ als Wert, überspringt
  `visible == False`; `("Any model", "")` steht vorn. `_model_guidelines()`
  sucht `^(text|image|video)_prompt_enhancer_instructions\d*$` (text vor image
  vor video) und liefert den Text der Definition — keine eigenen kuratierten
  Guidelines, keine Netzabfrage. `_guidelines_text()` erklärt den Fallback.
  `_read_prompt_meta()` füllt beim Eintragswechsel Modell + Beschreibung;
  `Save as` öffnet ein Namensfeld (vorbefüllt), erst `Save` im Dialog
  schreibt `.txt` + Sidecar und aktualisiert beide Dropdowns; `Cancel`
  blendet es aus.
  **Autor:** Das Feld **A brief description of the intent** beschreibt das
  gewünschte Ergebnis; `Enhancer` = **`WanGP local`** (gespeicherter Wert
  bleibt `Local 27B`) oder `OpenAI-compatible API`, `Generate` schreibt
  daraus den System-Prompt. Lokal wählt **`Local model`** zwischen
  `Auto (VRAM)`, `Qwen3.8-9B` und `Qwen3.8-27B`: Auto nimmt ab **16 GB**
  VRAM den 27B, sonst den 9B (IDs 6/5, Quantisierung `gguf`/`gguf_ptq1`,
  Engine über `engine_from_legacy_enhancer()`); der Swap von
  `enhancer_enabled`/`prompt_enhancer_quantization` wird nach dem Lauf
  restauriert. `_local_enhancer_ready()` gilt für den Autor **nicht** mehr.
  Die API nutzt `/v1/chat/completions` mit Base URL, Modell und Key aus
  `local_enhance_author_*`. Bei `OpenAI-compatible API` erscheinen
  `API model` + `Configure`; `Configure` öffnet `author_api_group`,
  `Done` schließt sie. `Provider` setzt die Base URL vor
  (`Ollama` `http://localhost:11434/v1`, `LM Studio`
  `http://127.0.0.1:1234/v1`, `OpenAI` `https://api.openai.com/v1`,
  `Custom` leer). **`Detect`** prüft Loopback **und** LAN-IP auf 11434/1234
  (`/v1/models`, 1,2 s) und setzt Provider, Base URL und Modellliste;
  `Test connection` prüft eine manuelle URL. **Antwort-Parameter** im Dialog:
  `Max answer tokens` (`max_tokens`, 0 = Provider-Default),
  `Temperature`, `Reasoning effort` (`reasoning_effort`, nur wenn gesetzt)
  und `Extra body (JSON)` für providerspezifische Felder (z. B.
  `{"max_thinking_tokens": 4096}`). Ein separates Denk-Budget ist nicht
  standardisiert; `max_tokens` begrenzt die Gesamtausgabe inklusive Denken.
  `model`/`messages` sind nach dem Merge geschützt. **API-Key:** nur mit
  `Remember API key` in `local_enhance_author_api_key`; ohne Haken bleibt er
  in `_AUTHOR_KEY_MEMORY` (nur Prozess). `Generate` speichert Verbindung und
  Parameter vor dem Aufruf. Das Ergebnis landet **nur im Editor**, nie
  automatisch gespeichert.
  `_migrate_library()` läuft nur in `setup_ui()` (nie in dev-Skripten),
  merkt sich `local_enhance_prompt_migrated` in `server_config` und schreibt
  beim ersten Host-Start `photograf.txt` (bisheriger Live-Text aus
  `system_prompt.txt`) und `sheet.txt` (`_TEMPLATE_SHEET_TEXT`); die Auswahl
  wird danach `photograf`, außer sie zeigt schon auf einen gespeicherten
  Eintrag. `_import_prompt_file()` übernimmt UTF-8 (Fallback latin-1),
  bereinigt den Namen, hängt bei Kollision ` 2`/` 3` an und kopiert ein
  vorhandenes Sidecar mit; leere Dateien werden abgelehnt.
  Die Karte hat **vier** Karten (System Prompts, Bypass-LoRA, Model check,
  Prompt workshop). Bei Audio-Modellen mit Musik-Feld kommt eine fünfte Karte
  **Music Style** dazu (siehe unten); ohne `alt_prompt` fehlt sie ganz, deshalb
  prüft `dev/check_template_ui.py` weiter vier Karten. Ordner- und Eintragszeile werden nach dem Aufbau mit
  `_flatten_row()` aus den Gradio-`Form`-Wrappern geholt
  (`fill_expected_parents` würde die Felder sonst vertikal stapeln). Die
  Textfelder wachsen per CSS (`flex:1 1 240px` bzw. `180px`), die Buttons
  behalten ihre `min_width`.
- **Music Style (Tag-Baukasten):** Die Karte erscheint nur, wenn
  `_music_style_visible(model_def)` gilt: `audio_only` **und** `alt_prompt` mit
  einem Musik-Label (`Music Style`, `Music Caption`, `Genres / Tags`,
  `Music Description`, `Keywords / Tags`). TTS-Felder wie `Spoken Language` oder
  `Reference Transcripts` bleiben verborgen. Sie wird beim Tab-Aufbau aus dem
  Live-Zustand gesetzt und bei `refresh_form_trigger.change` sowie über
  `on_tab_outputs`/`on_tab_select` nachgezogen; ohne `alt_prompt`-Komponente
  wird sie gar nicht gebaut.
  Inhalt: Dropdowns für Language/Vocals/Tempo (einfach, Tempo mit
  `allow_custom_value`), Genre/Instruments/Mood/Production (mehrfach),
  `Extra style notes`, darunter die read-only Vorschau `Finished Music Style`
  und die Knöpfe `Apply to Music Style` (ersetzt `alt_prompt`), `Append`
  (hängt an) und `Clear tags`.
  `_compose_music_style()` baut in fester Reihenfolge Sprache, Genre, Gesang,
  Instrumente, Stimmung, Tempo, Produktion, Freitext; doppelte Begriffe fallen
  weg. Steht irgendwo `instrumental`, wird nur `instrumental` gesetzt und
  Sprache/Gesang entfallen. Die Listen stehen als Default in
  `_MUSIC_TAG_DEFAULT`; eine eigene Datei `music_style_tags.json` im
  Prompt-Ordner (`_music_tag_path()`) überschreibt sie, kaputte/fehlende Dateien
  fallen still auf die Defaults zurück. Die Datei liegt bewusst außerhalb des
  Repos, damit eigene Tags kein Plugin-Update blockieren.
  Die Karte ist ein Geschwister der Hauptspalte (nach ihr im Tab), weil sie
  erst nach dem UI-Aufbau entsteht; `create_ui()` setzt `self._music_style_card`
  erst danach und hängt sie an `on_tab_outputs`.
- **Lyrics-Struktur (Section-Plan):** Unter den Tags steht
  `Section plan (optional)` mit `Load from ABC` und `Clear structure`. Der Plan
  wird in `local_enhance_lyrics_structure` gespeichert (Input-Event) und beim
  Lyrics-Enhancement (`T1`, `T1,B2O`, `B3` … also jeder Schritt, der `prompt`
  schreibt) als verbindlicher Kontext vor den Prompt gelegt
  (`_with_lyrics_structure`). Bei `B2O`/`L…` (kein Lyrics-Output) bleibt er
  unberührt. `_mode_writes_lyrics()` entscheidet das über
  `prompt_enhancer_chaining.parse_mode`.
  `_parse_abc_structure()` liest die `% intro`/`% verse`/`% chorus`-Kommentare
  einer SheetSage2-ABC-Datei (auch `% verse and pre-chorus`, `% fade-out`) und
  macht daraus `[Intro]`, `[Verse]`, `[Pre-Chorus]`, `[Outro]`; unbekannte
  Labels (`silence`, `loop`, `irregular`) fallen weg, aufeinanderfolgende
  Duplikate werden zusammengefasst. `Load from ABC` liest eine Datei direkt.
  Bei **Use ABC Score / Continue ABC Score** (`audio_prompt_type` `1`/`12`)
  liest `_structure_from_selected_abc()` die gewählte `custom_guide`-Datei
  automatisch, wenn das Feld leer ist. Bei **Use Score from Audio** (`A`/`A2`)
  gibt es zu diesem Zeitpunkt noch keine Transkription — der Enhancer läuft vor
  der Generierung. Dann einmal mit `Save ABC and MIDI Score` generieren und die
  exportierte `.abc` über `Load from ABC` laden.
- **Create Cover (Plugin-Schalter):** Checkbox oben in der Music-Style-Karte.
  Sie ist **kein** neuer Eintrag im Host-Dropdown (das gehört zur
  YuE2-Modelldefinition und wäre ein Host-Patch). Stattdessen setzt sie beim
  Einschalten:
  - `audio_prompt_type_sources` sichtbar auf `A` (Use Score from Audio),
  - den **versteckten** `audio_prompt_type`-Text selbst auf `A` (bzw. auf `0`
    beim Ausschalten), weil ein programmatisches Dropdown-Update den
    Host-`.change` nicht zuverlässig auslöst; Basis ist der bisherige Text ohne
    die `letters_filter`-Zeichen (`012A`) plus neuer Quelle,
  - `duration_seconds` auf die Länge der gewählten `audio_guide`-Datei
    (`soundfile`, Fallback `librosa`), begrenzt auf `min`/`max` des
    `duration_slider`,
  - die Zeile-1-Beschriftung auf `Enhance Lyrics:`.
  Ausschalten setzt die Quelle auf `New Composition` (`0`). **Music Style
  bleibt unangetastet** — die Transkription liefert Noten, keine Klangfarbe;
  ein YuE2-Cover ist eine neue Aufführung, kein Stimmen-Klon. Der Schalter
  liefert eine Statuszeile in der Karte. `_row_label` wird außerdem bei
  `refresh_form_trigger.change` (Modellwechsel) aktualisiert; die sichtbare
  Zeile heißt bei `prompt_class == "Lyrics"` oder Musik-Feld `Enhance Lyrics`.
  Die Komponenten `audio_prompt_type_sources`, `audio_prompt_type`,
  `audio_guide` und `duration_seconds` werden in `setup_ui()` angefragt; fehlen
  sie (Bild-/Video-Modell, Nachbau), filtert `_cover_components()` sie still.
- **Config-Keys:** `local_enhance_min_words`, `local_enhance_max_words`
  (`local_enhance_word_limit` ist Altbestand und dient als Fallback für Max).
  Defaults: Min 100, Max 350. `_migrate_word_defaults()` hebt beim ersten
  Start exakt die alten Vorgaben (0/150) auf 100/350; der Marker
  `local_enhance_word_defaults_v2` verhindert einen zweiten Lauf, eigene Werte
  bleiben. Dazu
  `local_enhance_prompt_dir`, `local_enhance_prompt_migrated`,
  `local_enhance_template` (Default `default`) und
  `local_enhance_lyrics_structure` (leerer Section-Plan). Dazu `local_enhance_author_source`
  (`Local 27B` / `OpenAI-compatible API`), `local_enhance_author_base_url`,
  `local_enhance_author_model`, `local_enhance_author_api_key` (nur mit
  `Remember API key`), `local_enhance_author_remember_key`,
  `local_enhance_author_provider` (Ollama/LM Studio/OpenAI/Custom),
  `local_enhance_author_max_tokens` (Default 2048, 0 = Provider-Default),
  `local_enhance_author_temperature` (Default 0.4),
  `local_enhance_author_reasoning_effort` (leer/low/medium/high),
  `local_enhance_author_extra_body` (JSON-Objekt als Text) und
  `local_enhance_author_local_model` (auto/qwen38_9b/qwen38_27b).
- Ist Min > Max, werden beide getauscht.

## Prüfen

- Syntax/Import (WanGP-venv, aus dem WanGP-Ordner):
  `cd ~/git/Wan2GP && ./.venv/bin/python -c "import sys; sys.path.insert(0,'/home/stefan/git/wan2gp-local-enhance'); import plugin; print(plugin.PlugIn_Name)"`
- UI ohne WanGP-Start: `dev/ui_preview.py` baut die Umgebung nach (Row mit
  eingebautem Knopf + verstecktem `gr.Text` + Dropdown + Think-Checkbox, danach
  die `insert_after`-Mechanik `pop(-1)` + `insert(target_index+1, …)`). Das
  versteckte `gr.Text` ist WanGPs Modus-Komponente `prompt_enhancer`; das Skript
  setzt sie wie der PluginManager **vor** `create_inline_button()` auf das Plugin
  (`shared/utils/plugins.py:1627` vor `1657`) und gibt den Komponentenbaum, die
  Zahl der Klick-Eingaben und `mode-components-at-wiring` aus. Aufruf aus dem
  WanGP-Ordner:
  `./.venv/bin/python ~/git/wan2gp-local-enhance/dev/ui_preview.py 7899`.
  Erwartung:
  Zeile 1 = `[HTML, Button, Button, Dropdown, Checkbox]` (Specific-Prompt-
  Dropdown + Think),
  die fremde Formularzeile (der `Form`, in dem der versteckte Modus-Text liegt)
  = `[Textbox(prompt_enhancer), Dropdown]` — das Modus-Dropdown steht dort
  allein; die Think-Checkbox ist in Zeile 1 gewandert, die Wort-Regler in den
  Tab,
  Tab-Wortzeile = `[Number, Number]` (`Min words` / `Max words`) **ohne**
  `Form`-Wrapper,
  Regler = `[Textbox(Modus), Checkbox, Number, Number]` → **6** Klick-Eingaben
  (bzw. 6 + Bild-Eingaben am lokalen Knopf),
  `mode-components-at-wiring=1`, und im Layout darf keine Komponente doppelt
  eingetragen sein.
  Der Dump zeigt ausserdem den Modell-Check. Erwartung (soeben gemessen):
  der Hinweis-Text ist als eigener Markdown-Block vorhanden,
  die Zeile zum aktuellen Modell kommt aus der Katalog-Fixture
  (`hidream_o1_dev` → `**Current model:** HiDream O1 Image Dev 10B - ships its own
  enhancer instructions, so Min/Max are ignored.`, `preview_plain` → `… no own
  enhancer instructions, Min/Max apply.`, leerer Snapshot →
  `**Current model:** unknown.`),
  der Detailbereich heisst `Which models ignore Min/Max?` mit
  `open=False` (Objekt **und** Konfiguration),
  sein Inhalt ist genau `[Row, Markdown, Markdown, HTML]` (Knopf, Statuszeile,
  Einleitung, Liste),
  der Knopf `Check models` hat `size='sm' scale=0 min_width=160`,
  sein Klick ist mit `outputs=[Liste, Statuszeile]` und `inputs=[]` verdrahtet,
  genau **1** `gr.HTML` trägt den Inline-Stil (`Scrollbare Box: 1`),
  `Box in _UI_CSS: False`, und beim Aufbau steht in der Box
  `<div style="max-height:260px;overflow-y:auto;">Not checked yet in this
  installation - press <b>Check models</b>.</div>` bei leerer Statuszeile
  (im HTML also `<b>`, nicht die Markdown-Sternchen). Der Klick wird **nicht**
  ausgelöst — er würde `enhancer_models.json` schreiben. Liegt dort ein gültiger
  Stand, zeigt der Dump stattdessen dessen gerenderte Liste und Statuszeile; ein
  alter Stand zeigt wieder den Ersatztext (siehe Schritt „Zwischenspeicher" in
  „Technisches").
  Das Modus-Dropdown wird im Nachbau mit `show_label=False` angelegt (wie WanGP
  im On-Demand-Modus) — der Dump muss danach `show_label=True` zeigen, sonst
  greift der Caption-Fix nicht.
  `PREVIEW_MIN`/`PREVIEW_MAX` setzen die Startwerte der beiden Felder
  (Default 0/1500).
- Geometrie (headless, CDP): die beiden Wort-Felder müssen auf derselben
  Grundlinie nebeneinander liegen — live gemessen: Block je 120px
  (`min(120px, 100%)`), die Eingabe darin 94px, beide auf y=364 —, und
  `input.scrollWidth - clientWidth` muss 0 sein, sonst ist ein Wert wie „1500"
  abgeschnitten.
- Modell-Check live (headless, CDP; `dev/ui_preview.py` auf 7899 starten und
  Chromium mit `--headless=new --remote-debugging-port` darauf zeigen lassen,
  dann `Runtime.evaluate` über `websockets` aus der WanGP-venv; den
  Accordion-Kopf vorher per `click()` öffnen, die Liste muss gefüllt sein):
  - **Knopf einzeilig:** `Check models` ist live 160×25 px, sein Text belegt
    genau **1** Zeilenbox (`Range.getClientRects()` über den Knopfinhalt = 1).
    `scale=0` allein quetschte ihn auf zwei Zeilen, deshalb
    `min_width=_MODEL_CHECK_BUTTON_WIDTH` (160).
  - **Box scrollt:** `scrollHeight` **1117** > `clientHeight` **260** — genau
    der Inline-Stil `max-height:260px;overflow-y:auto;`; ohne ihn zöge die Liste
    den Tab auseinander.
  - **Gruppenzeilen echt getrennt:** im Text der Box steht **kein** `\n`
    (gemessen 0), die **5** Gruppentitel (`Image`, `Image + Video`, `Video`,
    `Audio (Music)`, `Audio (TTS)`) liegen auf verschiedenen y. Der Mechanismus
    dahinter, direkt im Browser gemessen: derselbe Text mit `\n` statt `<br>`
    rendert als **eine** Zeile (Elementhöhe 20px), mit `<br>` als drei und mit
    `<br><br>` als vier Zeilen (80px) — HTML faltet die Zeilenumbrüche des alten
    Zwischenspeichers, `<br>` nicht. Genau das war die Textwand.
- Tab und System Prompts ohne WanGP-Start: `dev/check_template_ui.py`
  (WanGP-venv, aus dem WanGP-Ordner) baut `create_inline_button()` +
  `create_ui()` in einem `gr.Blocks` nach und prüft: **4** Karten,
  `Name (max. 64 chars)` (Save-Dialog), `Saved prompt`/`Model`,
  `Enhancer`, `What should the final prompt look like?`,
  `Model guidelines (optional)`, `Local model`, `Max answer tokens`,
  `Temperature`, `Reasoning effort`, `Extra body (JSON, optional)`,
  `API model`, `Remember API key`,
  Prompt-Textfeld, Wortgrenzen, Model check, Prompt workshop, keine doppelte
  `elem_id`, Bypass-LoRA-Nachtrag, `Load WanGP default` und `Generate`
  als Knöpfe. Die Ordnerzeile
  (`local_enhance_library_row`) muss genau
  `[Dropdown, Textbox, Button, Button]` (`Saved prompt`, `Folder`, `↻`,
  `Save`), die Eintragszeile (`local_enhance_entry_row`) genau
  `[Dropdown, Number, Number]` (`Model`, Min, Max)
  enthalten — beide ohne `Form`-Wrapper; **zwei** `upload`-Dependencies
  (Load/Import im Accordion) und die Labels `Provider`/`Base URL` sowie der
  Knopf `Test connection`. Die Provider-Presets werden ohne Netz geprüft
  (`_author_base_for_provider`). Danach die Bibliothek: Namensregel (64/65 Zeichen,
  `..`, `/`, führender Punkt, `default`), Schreiben/Lesen, leere Datei wird
  übersprungen, `default`-Fallback, `_next_free_prompt_name()`
  (`X` -> `X 2` -> `X 3`, Länge <= 64), Migration (`photograf.txt` + `sheet.txt`,
  Marker, Auswahl `photograf`), Import (Text übernommen, Kollision bekommt
  Zähler, leere Datei abgelehnt) sowie Sidecar/Modell/Guidelines:
  `_write_prompt_meta`/`_read_prompt_meta` (leer löscht), Modellkatalog ohne
  `visible == False`, `_model_guidelines` aus der Definition,
  `_author_user_message` und die API-Config.
  Der Ordner ist ein `tempfile`-Verzeichnis; das Skript schreibt nie nach
  `~/Prompts`. Erwartung: alle `OK:`-Zeilen, Exit 0.
- Auflösung ohne UI (schneller Matrix-Check gegen `_read_controls`, Eingabe ist
  immer `(Think, Min, Max)`): `(False, 0, 1500)` → `(False, 0, 1500)`,
  `(True, 800, 100)` → `(True, 100, 800)` (Tausch bei Min > Max),
  `(False, 0, 0)` → `(False, 0, 0)`, `(False, 300)` → `(False, 0, 300)`
  (Altbestand: ein einzelnes Feld ist die Obergrenze),
  `(False, "300", 0, 1500)` → `(False, 0, 1500)` (ein unbekannter Typ wird
  übersprungen).
- Bild der Zeile ohne Browserfenster (Chromium ist installiert, Playwright nicht):
  `--headless=new --user-data-dir=.ui-shots/prof --force-device-scale-factor=2
  --virtual-time-budget=9000 --window-size=780,300 --screenshot=….png
  "http://127.0.0.1:7899/?__theme=dark"` (mit `env -u DISPLAY`, sonst bricht
  Chromium an der X11-Autorisierung ab). `.ui-shots/` ist ignoriert und
  Crashpad/Benutzerprofil wandern dorthin.
- Bild-Aufbereitung ohne GPU/WanGP: `dev/check_vision_inputs.py` (WanGP-venv, aus
  dem WanGP-Ordner) täuscht `convert_image`, `get_computed_fps`,
  `get_base_model_type`, `estimate_first_window_overlap_frames`,
  `prompt_enhancer_outputs_multiple_prompts` und `get_prompt_enhancer_choices`
  als Modul `__main__` vor und prüft **20** Fälle: Modus ohne `"I"`, Startbild,
  Endbild, zwei Referenzen, Control Image allein, `fake_start_image`
  (On-Demand-Parität), Fenstermodell (erster Anker), Fallback bei mehreren
  Startbildern, fehlendes `convert_image`, IT2I- vs. T2I-Anweisungen,
  `_image_note`, Trennung der Klick-Eingaben, Trennung **ohne**
  Think-Checkbox (samt gelesener Min/Max-Werte), `_effective_mode` (leerer
  Live-Wert → Modell-Default, gesetzter Live-Wert gewinnt) und
  `_split_mode_input` (mit und ohne Modus-Komponente).
  Erwartung: 20 `PASS`-Zeilen und `Alle Faelle bestanden.` (Exit 0).
- Modell-Check ohne WanGP-Start: `dev/check_enhancer_overrides.py` (WanGP-venv,
  aus dem WanGP-Ordner) wirft eine erfundene Fixture gegen
  `_collect_enhancer_overrides()` — kein Hoststart, kein Katalog auf der Platte.
  Aufruf:
  `./.venv/bin/python ~/git/wan2gp-local-enhance/dev/check_enhancer_overrides.py`.
  Erwartung: **23** `PASS`-Zeilen und `Alle Faelle bestanden.` (Exit 0; nachgezählt
  mit `… | grep -c '^PASS'`). Geprüft werden die beiden Zähler, Bündelung und
  Gruppenreihenfolge, der Zähler nur bei mehreren Varianten, der Anzeigename aus
  der Definition mit passendem internen Typ, das Fehlen von Modellen ohne
  Schlüssel und von `visible == False` (das aber als untersucht zählt),
  Ziffernsuffixe innerhalb und ausserhalb 1-4, dass `*_max_tokens*`-Schlüssel
  **nicht** treffen, `v2i_switch_supported` in `Image + Video`, die
  Audio-Unterteilung nach `family_label`, kaputte Einträge, fehlende Namen und
  Metadaten, leere/falsche Kataloge, `metadata.main_output` gegen den Fallback
  und das Rendern: eine Zeile je **Familie**, Gruppen wirklich getrennt
  (`<br><br>`), kein `\n` im Text, Escaping, keine Tabelle.
  Danach läuft die „realistische Namensprobe": sie baut die Fixture aus
  `~/git/Wan2GP/defaults/*.json` (+ `finetunes/`) und liest die betroffenen
  Modelle aus `enhancer_models.json` — **beide** Formate (strukturierte `groups`
  des neuen Stands über die internen Typen, sonst den gerenderten `list`-Text des
  alten). Im Nachbau: 238 Definitionsdateien, 90 betroffene, 48 Familienzeilen.
  `--dump <models_def.json>` gibt ohne Testlauf den gerenderten Text für einen
  eigenen Katalog aus.
- Verdrahtung der Knöpfe (ohne WanGP-Start): im `gr.Blocks`-Aufbau Bild-Komponenten
  auf den Plugin-Instanzen setzen (`p.image_start = gr.File(...)`,
  `p.image_prompt_type = gr.CheckboxGroup(...)`, `p.video_prompt_type = …`) und
  `demo.get_config_file()` nach `targets == [<knopf-id>, "click"]` durchsuchen:
  `local_enhance_remote_btn` muss **7** Inputs haben (mit `alt_prompt`),
  `local_enhance_local_btn` **7 + Anzahl der Bild-Komponenten**; der Tab-Knopf
  wird mit denselben Reglern verdrahtet, also ebenfalls **7 + Anzahl der
  Bild-Eingaben**. Ohne `alt_prompt`-Komponente (Nachbau ohne zweites Feld)
  bleiben es **6** bzw. **6 + Bilder**.
- End-to-End (WanGP läuft): `http://127.0.0.1:7860/config` abrufen — die
  Dependencies von `local_enhance_remote_btn` müssen **7 Inputs** haben
  (`state, prompt, Modus, Think, Min, Max, alt_prompt`),
  `local_enhance_local_btn` **7 + Anzahl der Bild-Eingaben** des Modells;
  Ausgaben: Prompt + `alt_prompt` (Remote/Lokal) bzw. Prompt + `alt_prompt` +
  Knopf (Local API).
- Music-Felder ohne GPU/WanGP: `dev/check_music_fields.py` (WanGP-venv, aus dem
  WanGP-Ordner) prüft **13** Fälle: veralteter Live-Modus (`T` an YuE2) fällt
  auf `T1` zurück, leerer Wert ergibt `T1`, `T1,B2O`/`T1K` bleiben erhalten,
  `_field_labels` liefert `Lyrics`/`Music Style`, `_split_alt_input` trennt den
  Alt-Text, `T1` schreibt nur den Prompt, `B2O` nur den Style (mit JSON aus
  beiden Feldern), `T1,B2O` schreibt beide und reicht die neuen Lyrics an den
  Style-Schritt weiter. Erwartung: 13 `PASS`, Exit 0.
- Verdrahtung mit Alt-Text: `dev/check_music_wiring.py` (WanGP-venv, aus dem
  WanGP-Ordner) baut die Knöpfe mit/ohne `alt_prompt` und prüft die
  Gradio-Konfiguration: mit Alt 7/7/7 Eingaben und 2/2/3 Ausgaben, ohne Alt
  6/6/6 und 1/1/2. Erwartung: 12 `PASS`, Exit 0.
- Music-Style-Tags: `dev/check_music_tags.py` (WanGP-venv, aus dem WanGP-Ordner)
  prüft **41** Fälle: Komposition/Reihenfolge, Dedupe, instrumental-Regel,
  Sichtbarkeit (YuE2/ACE ja, TTS/Image nein), eigene `music_style_tags.json`
  inkl. kaputter Datei, Apply/Append/Clear, ABC-Struktur (inkl.
  `verse and pre-chorus`/`fade-out`), Lyrics-Kontext, `_mode_writes_lyrics`,
  Cover (Lyrics-Label, Dauer aus WAV, versteckter Source-Text), die fünfte
  Karte mit allen Dropdowns/Buttons/`Section plan`/`Create Cover` und
  `on_tab_select` (sichtbar bei YuE2, verborgen bei Krea 2). Erwartung: 41
  `PASS`, Exit 0.
- Vision live: Modus *Based on Text Prompt and Images* wählen, Startbild mit
  markantem Inhalt setzen, Prompt „a cat" → der verbesserte Prompt muss den
  Bildinhalt beschreiben und die Statuszeile `images: start image` nennen. Dann
  Modus *Based on Text Prompt Content* bei gleichem Bild → Statuszeile ohne
  Bildhinweis (Textpfad unverändert).
- Schreibzugriffe außerhalb des Workspace (WanGP-Klon, WanGP-Repo) brauchen in der
  Sandbox `danger-full-access`.

## Offen

- Modelle mit **eigenen** Enhancer-Anweisungen: dort wirken Min/Max nicht, weil
  `model_def` gegen die übergebenen Anweisungen gewinnt (`wgp.py:6476`). Fachlich
  bleibt das offen — der Host entscheidet —, ist jetzt aber im Tab sichtbar und
  prüfbar: *Check models* listet genau diese Modelle. Die Erkennung ist **grob**:
  sie sagt nur, dass die Definition einen passenden Schlüssel mitbringt, nicht ob
  der Host ihn im gewählten Modus wirklich benutzt (die erste Ziffer im Modus
  wählt ein Profil, `wgp.py:6462-6464`).
- `_read_controls()` übergeht unbekannte Eingabetypen still — ausgewertet werden
  nur `bool` und Zahlen. Ein künftiger Verdrahtungsfehler würde die Wortgrenzen
  also still verschieben, ohne Fehlermeldung. Heute ist das nicht erreichbar,
  weil der Modus-String vorher mit `_split_mode_input()` abgezogen wird.
- Der Hinweis zum **aktuellen** Modell ist gebaut — aber nur im Plugin-Tab: die
  live berechnete Zeile steht über dem eingeklappten Modell-Check und wird beim
  Tab-Wechsel neu gezogen (`on_tab_outputs`, siehe „Technisches"). Die beiden
  Knöpfe in Zeile 1 bekommen weiterhin **keinen** eigenen Hinweis: sie schreiben
  Prompt und (falls vorhanden) `alt_prompt` (`outputs=[prompt, alt_prompt]`;
  Status ginge allenfalls als `gr.Info`/`gr.Warning`-Toast raus) und haben keine
  Statuszeile — ein Hinweis dort bräuchte eine eigene Ausgabe-Komponente.
- **Style → Lyrics:** `T1` (Lyrics) liest bei YuE2 nur den Prompt; der Music
  Style fließt erst im Style-Schritt (`B2O` bzw. `T1,B2O`) ein. Das entspricht
  der Modelldefinition („Lyrics then Music Style", `yue2_handler.py:211`); eine
  Variante `B1` (Style als Kontext für die Lyrics) bietet YuE2 nicht an und wird
  deshalb auch nicht erfunden.
- Das Denk-Budget der 27B ist hart auf **2000 Tokens** begrenzt
  (`shared/prompt_enhancer/qwen35_text.py:64`) — es gibt keinen Config-Key dafür.
- Der Tab-Knopf hat keine eigenen Widgets; er nutzt dieselben Regler wie die
  Knöpfe in Zeile 1 (Think) bzw. die beiden Felder oben im Tab (Min/Max).
- **Bilder — Stufe 1:** Fortsetzungsvideo (`L`/`V` ohne Startbild) liefert kein
  dekodiertes Frame; die Prompt-/Fensteraufteilung bleibt beim Ein-Prompt-Verhalten
  des Plugins (nur der erste Fensteranker kommt an); der OpenCode-Knopf sendet
  weiterhin keine Bilder; Geometrie-Felder kommen aus dem Settings-Snapshot statt
  live. Für den Standardfall (Bildmodell, Startbild/Referenzen/Control Image)
  ist die Kette vollständig.

## Fortschrittsanzeige (2026-10-05)

Die beiden Inline-Knoepfe liefen mit `show_progress="hidden"`, und
`ensure_prompt_enhancer_loaded()` wurde ohne `progress=` aufgerufen. WanGP
meldet Fortschritt aber nur MIT progress (wgp.py:3983, `if progress is not None`)
- beim Kaltstart der 27B sah man deshalb gar nichts, der Toast kam erst am Ende.
Jetzt: `enhance()` und `enhance_inline()` nehmen `progress=gr.Progress()`,
`enhance_inline()` reicht es durch, der Loader bekommt es, und `local_btn` steht
auf `show_progress="full"` (plus Status "Enhancing Prompt" vor `process()`).
Das genaue Log bleibt das Terminal (tqdm "Qwen3.5 prompt enhancement" /
"Generating ... Prefill/Decode"). Backup: `plugin.py.bak-20261005-progress`.
