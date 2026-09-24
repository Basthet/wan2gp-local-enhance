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
Modell-Default zurück (`_resolve_mode`).

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

Unter den beiden Feldern steht der **Modell-Check**: die englische Hinweiszeile
(`_MODEL_CHECK_HINT`), darunter ein eingeklapptes `Which models ignore Min/Max?`
mit dem Knopf *Check models*, einer Statuszeile und der Liste. Beim Aufbau des
Tabs wird **nichts** berechnet — Liste und Status kommen aus
`enhancer_models.json` neben `plugin.py`; erst der Klick auf *Check models* liest
den Katalog (`_main("models_def")`, nur lesen), zählt, rendert und schreibt die
Datei. Die Liste nennt die Modelle, deren Definitionen eigene
Enhancer-Anweisungen mitbringen — dort gewinnen sie gegen die vom Plugin
übergebenen (`_fallback_instructions`), Min/Max wirken also nicht.

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
  bei leerem Wert. Beide Knöpfe haben dadurch **7** Klick-Eingaben
  (`state, prompt, Modus, Think, Preset, Min, Max`), der lokale **7 +
  Bild-Eingaben**. Seit `e5ed6d8` sind es **6** (`… Think, Min, Max`), das
  Preset ist weg. Vorher stand im Klick immer der Modell-Default, wodurch
  Modelle mit erstem Modus `"T"` (`qwen_image_21_7B`) die Bilder verwarfen.
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
- **Alle Commits bis `39dbd33` sind gepusht**, samt dieser Fassung der
  Anleitung.
  Nach dem Neustart prüfen: `local_enhance_remote_btn` **6 Inputs**,
  `local_enhance_local_btn` **6 + Anzahl der Bild-Eingaben** des Modells, die
  beiden Felder **Min words** / **Max words** ganz oben im Plugin-Tab
  nebeneinander und ohne abgeschnittene „1500", darunter der Modell-Check
  (Klick auf *Check models* füllt Status und Liste), und der Vision-Lauf aus
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
  Plugin-Tabs (`wgp.py:13976`). Deshalb sitzen Knöpfe und Think-Checkbox in
  Zeile 1, während die Wort-Regler und der Tab-Knopf erst in `create_ui()`
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
    Inline-Style. Betroffen sind nur noch Reihe und Think-Checkbox
    (`.local-enhance-label`, `.cbx_centered`). Die beiden Wort-Regler brauchen
    keine Regel: sie bekommen ihre Breite über `min_width=_WORD_FIELD_WIDTH`
    (120px) plus `scale=0`. `_UI_CSS` enthält damit nur noch vier Regeln: den
    Originalknopf ausblenden, Zeile 1 umbrechen lassen, die Breiten von Label
    und Think-Checkbox und die volle Breite der fremden Formularzeile
    (`#local_enhance_row + .form`, inzwischen nur noch das Modus-Dropdown).
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
    `state, prompt, Modus, Think, Min, Max` → **6**. Der Modus-String wird
    vorher mit `_split_mode_input()` abgezogen, die Bilder trennt
    `_split_image_inputs()` von rechts ab.
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
  `visible == False` wird übersprungen. Ergebnis und Status landen in
  `enhancer_models.json` neben `plugin.py` (Name in `.gitignore`, damit
  Testläufe und der geladene Klon sauber bleiben).
- **Warum es den Check gibt:** ein Teil der Modelldefinitionen bringt eigene
  Enhancer-Anweisungen mit (Grössenordnung: gut ein Drittel des Katalogs — im
  Nachbau dieses Checkouts mit 238 Definitionsdateien 90 betroffene). Der Host
  bevorzugt sie gegen die vom Plugin übergebenen, Min/Max wirken dort also
  nicht. Die genaue Zahl nennt die Statuszeile beim Klick selbst
  („<betroffen> von <untersucht> model definitions"). Die Liste wird
  **erzeugt**, nicht gepflegt — mit neuen Modellen wächst sie von selbst mit.
- **Config-Keys:** `local_enhance_min_words`, `local_enhance_max_words`
  (`local_enhance_word_limit` ist Altbestand und dient als Fallback für Max).
  Defaults: Min 0 (= keine Untergrenze), Max 150.
- Ist Min > Max, werden beide getauscht.

## Prüfen

- Syntax/Import (WanGP-venv, aus dem WanGP-Ordner):
  `cd ~/git/Wan2GP && ./.wan2gp/bin/python -c "import sys; sys.path.insert(0,'/home/stefan/git/wan2gp-local-enhance'); import plugin; print(plugin.PlugIn_Name)"`
- UI ohne WanGP-Start: `dev/ui_preview.py` baut die Umgebung nach (Row mit
  eingebautem Knopf + verstecktem `gr.Text` + Dropdown + Think-Checkbox, danach
  die `insert_after`-Mechanik `pop(-1)` + `insert(target_index+1, …)`). Das
  versteckte `gr.Text` ist WanGPs Modus-Komponente `prompt_enhancer`; das Skript
  setzt sie wie der PluginManager **vor** `create_inline_button()` auf das Plugin
  (`shared/utils/plugins.py:1627` vor `1657`) und gibt den Komponentenbaum, die
  Zahl der Klick-Eingaben und `mode-components-at-wiring` aus. Aufruf aus dem
  WanGP-Ordner:
  `./.wan2gp/bin/python ~/git/wan2gp-local-enhance/dev/ui_preview.py 7899`.
  Erwartung:
  Zeile 1 = `[HTML, Button, Button, Checkbox]`,
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
  Der Dump zeigt ausserdem den Modell-Check: Hinweis-Text vorhanden, Accordion
  `open=False`, der Knopf-Klick mit den Ausgaben Liste/Statuszeile und beim
  Aufbau den Ersatztext `Not checked yet in this installation - press **Check
  models**.` bei leerer Statuszeile. Der Klick wird **nicht** ausgelöst — er
  würde `enhancer_models.json` schreiben.
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
  `./.wan2gp/bin/python ~/git/wan2gp-local-enhance/dev/check_enhancer_overrides.py`.
  Erwartung: 18 `PASS`-Zeilen und `Alle Faelle bestanden.` (Exit 0). Geprüft
  werden die beiden Zähler, Gruppenzuordnung und -reihenfolge, alphabetische
  duplikatfreie Namen, das Überspringen von `visible == False` (das aber als
  untersucht zählt), Ziffernsuffixe innerhalb und ausserhalb 1-4, dass
  `*_max_tokens*`-Schlüssel **nicht** treffen, die Audio-Unterteilung nach
  `family_label`, kaputte Einträge und das Rendern (eine Zeile je Gruppe, keine
  Tabelle). `--dump <models_def.json>` gibt ohne Testlauf den gerenderten Text
  für einen eigenen Katalog aus.
- Verdrahtung der Knöpfe (ohne WanGP-Start): im `gr.Blocks`-Aufbau Bild-Komponenten
  auf den Plugin-Instanzen setzen (`p.image_start = gr.File(...)`,
  `p.image_prompt_type = gr.CheckboxGroup(...)`, `p.video_prompt_type = …`) und
  `demo.get_config_file()` nach `targets == [<knopf-id>, "click"]` durchsuchen:
  `local_enhance_remote_btn` muss **6** Inputs haben, `local_enhance_local_btn`
  **6 + Anzahl der Bild-Komponenten**; der Tab-Knopf wird mit denselben Reglern
  verdrahtet, also ebenfalls **6 + Anzahl der Bild-Eingaben**.
- End-to-End (WanGP läuft): `http://127.0.0.1:7860/config` abrufen — die
  Dependencies von `local_enhance_remote_btn` müssen **6 Inputs** haben
  (`state, prompt, Modus, Think, Min, Max`), `local_enhance_local_btn`
  **6 + Anzahl der Bild-Eingaben** des Modells.
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
- Bewusst **nicht** gebaut: ein Hinweis beim Klick, ob das **aktuelle** Modell
  eigene Anweisungen hat. Wäre machbar, aber die beiden Zeilen-Knöpfe schreiben
  nur ins Promptfeld (`outputs=[prompt_component]`; Status geht allenfalls als
  `gr.Info`/`gr.Warning`-Toast raus) und haben keine Statuszeile — ein Hinweis
  bräuchte dort eine eigene Ausgabe-Komponente.
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
