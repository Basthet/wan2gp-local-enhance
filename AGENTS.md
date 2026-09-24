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
- **Words** (Zeile 2, Preset-Dropdown neben dem Modus-Dropdown) — ersetzt die
  feste 150-Wort-Grenze in WanGPs Anweisungen
  (`shared/prompt_enhancer/prompt_enhance_utils.py:25/34/42/51/56`):
  die Presets `no limit` (0/0), `short - 150 words`, `medium - 300 words` und
  `long - 500 words` setzen Min auf 0; `custom (min/max)` blendet die beiden
  Zahlenfelder `Min`/`Max` ein (0 = keine Grenze). Aufgelöst wird das
  in `_read_controls` über `_preset_range`; Anweisungen: beide gesetzt →
  „Keep between MIN and MAX words.", nur Max → wie bisher, nur Min →
  „Write at least MIN words.", beide 0 → Sätze entfernt.
  Das Token-Budget wächst mit (`_output_token_budget`), sonst schneidet das
  512-Token-Limit den Prompt ab.

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
- **Arbeitsstand, noch nicht committet** — Modus-Fix: der Modus kommt live aus
  WanGPs verstecktem `prompt_enhancer`-Text (`request_component`,
  `_mode_components`, `_split_mode_input`, `_effective_mode`), `_resolve_mode`
  ist nur noch Fallback bei leerem Wert. Beide Knöpfe haben dadurch **7**
  Klick-Eingaben (`state, prompt, Modus, Think, Preset, Min, Max`), der lokale
  **7 + Bild-Eingaben**. Vorher stand im Klick immer der Modell-Default, wodurch
  Modelle mit erstem Modus `"T"` (`qwen_image_21_7B`) die Bilder verwarfen.
- **`2f6f3e6`, `446da1e`, `61f25ae`, `40215b9` und `084acf1` sind gepusht.**
  Nach dem Neustart prüfen: `local_enhance_remote_btn` **7 Inputs**,
  `local_enhance_local_btn` **7 + Anzahl der Bild-Eingaben** des Modells, alle
  vier Kästen in Zeile 2 auf einer Linie, Preset wechseln → Felder verschwinden,
  `custom` → sie kommen mit ihren alten Werten zurück, und der Vision-Lauf aus
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
  Plugin-Tabs (`wgp.py:13976`). Deshalb sitzen die Regler in Zeile 1/2 und der
  Tab-Knopf wird in `create_ui()` nachträglich mitverdrahtet.
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
    vorgeben — das schlägt auch das Inline-Style. Betrifft die Reihe, die
    Think-Checkbox und die Wort-Regler (Preset-Dropdown 190px, Zahlenfelder
    84px, siehe `_UI_CSS`).
  - **Höhe und vertikales Padding der Eingaben bleiben Gradios Vorgabe.** Eigene
    `input{padding…; font-size…}`-Regeln machen die Zahlenfelder niedriger als
    die Dropdowns daneben (live 21px statt 33px) und zerreissen die gemeinsame
    Grundlinie. Erlaubt ist nur horizontal: `padding-left/right:4px`, sonst
    schneidet „1500" in den 84px ab (5px Überlauf).
  - **Captions sind `<span data-testid="block-info">`** im Kopf des Blocks, nicht
    das `<label>` — Letzteres umschliesst bei `gr.Number` die Eingabe. Wer die
    Caption stylen will, darf nicht `… label{…}` schreiben; die Schriftgrössen
    sind ohne Zutun schon einheitlich.
  - **WanGP versteckt die Caption des Modus-Dropdowns**, wenn der Enhancer
    on-demand läuft (`wgp.py:12174`: `show_label = not on_demand_prompt_enhancer`).
    Ohne Caption sitzt dessen Eingabe 32px höher als unsere beschrifteten Regler
    (live gemessen: y665 gegen y697) — genau der schiefe Screenshot. Das Plugin
    schaltet WanGPs eigene Caption deshalb in `create_inline_button` ein
    (`mode_dropdown.show_label = True`), und zwar **vor** dem Anhängen der
    eigenen Regler, sonst findet die Dropdown-Suche das eigene Preset. Ein
    Modellwechsel setzt sie nicht zurück: `refresh_prompt_enhancer_labels`
    schickt nur `choices` (`wgp.py:10898`).
  - Die Wort-Regler nutzen **Gradios eigene Captions** (`label="Words"` /
    `"Min"` / `"Max"`, `show_label=True`): sie stehen direkt über der Eingabe,
    kosten keine eigene Komponente und halten die Formulargruppe zusammen. Die
    früheren `gr.HTML`-Beschriftungen sind weg — genau deshalb ist der
    Unwrap-Code jetzt kurz.
  - Das Wortzahl-Preset ist ein `gr.Dropdown`, also ebenfalls FormComponent, und
    läuft durch dieselbe Unwrap-/Move-Mechanik wie die Zahlenfelder.
  - `visible=False` ändert nur das Rendering: die beiden Zahlenfelder werden
    weiter mitgesendet, ihr Wert überlebt also das Umschalten auf ein Preset und
    zurück (live geprüft).
  - Die Regler werden **nach Typ** ausgelesen (`*controls`), weil die
    Think-Checkbox fehlen kann: `bool` = Think, `str` = Preset-Schlüssel, Zahlen
    = Custom-Felder. Feste Reihenfolge der Klick-Eingaben:
    `state, prompt, Modus, Think, Preset, Min, Max`. Der Modus-String wird
    vorher mit `_split_mode_input()` abgezogen — sonst läse `_read_controls()`
    ihn als Preset und alles verschöbe sich um eins.
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
  Zeile 2 (der `Form` mit dem Dropdown) = `[Textbox(prompt_enhancer),
  Dropdown, Dropdown(preset "Words"), Number(Min), Number(Max)]`,
  Regler = `[Textbox(Modus), Checkbox, Dropdown, Number, Number]` → **7**
  Klick-Eingaben (bzw. 7 + Bild-Eingaben am lokalen Knopf),
  `mode-components-at-wiring=1`, und im Layout darf keine Komponente doppelt
  eingetragen sein.
  Das Modus-Dropdown wird im Nachbau mit `show_label=False` angelegt (wie WanGP
  im On-Demand-Modus) — der Dump muss danach `show_label=True` zeigen, sonst
  greift der Caption-Fix nicht.
  `PREVIEW_MIN`/`PREVIEW_MAX` setzen die Startwerte; `PREVIEW_MAX=150` ergibt den
  Preset-Fall (Felder `display:none`), der Default `1500` den Custom-Fall.
- Ausrichtung (headless, CDP): die sichtbaren Kästen aller vier Blöcke müssen
  oben auf derselben y liegen (Modus/Preset `box` 258…298, Min/Max 258…300) und
  `input.scrollWidth - clientWidth` muss 0 sein, sonst ist ein Wert wie „1500"
  abgeschnitten.
- Auflösung ohne UI (schneller Matrix-Check gegen `_read_controls`):
  `(False,"off",0,1500)` → `(0,0)`, `(False,"300",100,1500)` → `(0,300)`,
  `(False,"custom",800,100)` → `(100,800)`, `(False,None,0,1500)` → `(0,1500)`.
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
  als Modul `__main__` vor und prüft 17 Fälle: Modus ohne `"I"`, Startbild,
  Endbild, zwei Referenzen, Control Image allein, `fake_start_image`
  (On-Demand-Parität), Fenstermodell (erster Anker), Fallback bei mehreren
  Startbildern, fehlendes `convert_image`, IT2I- vs. T2I-Anweisungen,
  `_image_note`, Trennung der Klick-Eingaben, `_effective_mode` (leerer
  Live-Wert → Modell-Default, gesetzter Live-Wert gewinnt) und
  `_split_mode_input` (mit und ohne Modus-Komponente).
  Erwartung: `Alle Faelle bestanden.` (Exit 0).
- Verdrahtung der Knöpfe (ohne WanGP-Start): im `gr.Blocks`-Aufbau Bild-Komponenten
  auf den Plugin-Instanzen setzen (`p.image_start = gr.File(...)`,
  `p.image_prompt_type = gr.CheckboxGroup(...)`, `p.video_prompt_type = …`) und
  `demo.get_config_file()` nach `targets == [<knopf-id>, "click"]` durchsuchen:
  `local_enhance_remote_btn` muss **7** Inputs haben, `local_enhance_local_btn`
  **7 + Anzahl der Bild-Komponenten** (früher 9 bei drei Bild-Eingaben; jetzt
  7 + Anzahl).
- End-to-End (WanGP läuft): `http://127.0.0.1:7860/config` abrufen — die
  Dependencies von `local_enhance_remote_btn` müssen **7 Inputs** haben
  (`state, prompt, Modus, Think, Preset, Min, Max`), `local_enhance_local_btn`
  **7 + Anzahl der Bild-Eingaben** des Modells.
- Vision live: Modus *Based on Text Prompt and Images* wählen, Startbild mit
  markantem Inhalt setzen, Prompt „a cat" → der verbesserte Prompt muss den
  Bildinhalt beschreiben und die Statuszeile `images: start image` nennen. Dann
  Modus *Based on Text Prompt Content* bei gleichem Bild → Statuszeile ohne
  Bildhinweis (Textpfad unverändert).
- Schreibzugriffe außerhalb des Workspace (WanGP-Klon, WanGP-Repo) brauchen in der
  Sandbox `danger-full-access`.

## Offen

- Modelle mit **eigenen** Enhancer-Anweisungen: dort wirken Min/Max nicht, weil
  `model_def` gegen die übergebenen Anweisungen gewinnt (`wgp.py:6476`).
- Das Denk-Budget der 27B ist hart auf **2000 Tokens** begrenzt
  (`shared/prompt_enhancer/qwen35_text.py:64`) — es gibt keinen Config-Key dafür.
- Der Tab-Knopf hat keine eigenen Widgets; er nutzt die Regler aus Zeile 1/2.
- **Bilder — Stufe 1:** Fortsetzungsvideo (`L`/`V` ohne Startbild) liefert kein
  dekodiertes Frame; die Prompt-/Fensteraufteilung bleibt beim Ein-Prompt-Verhalten
  des Plugins (nur der erste Fensteranker kommt an); der OpenCode-Knopf sendet
  weiterhin keine Bilder; Geometrie-Felder kommen aus dem Settings-Snapshot statt
  live. Für den Standardfall (Bildmodell, Startbild/Referenzen/Control Image)
  ist die Kette vollständig.
