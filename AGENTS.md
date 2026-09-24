# AGENTS.md — WanGP-Plugin „Enhance: OpenCode / Bonsai 27B"

Kurzfassung für jede Session in diesem Repo. Was der Code tut, steht im Code —
hier steht nur, was man sonst mühsam herausfinden muss.

## Was das Plugin tut

Zwei Knöpfe neben WanGPs „Enhance Prompt":

- **OpenCode** — verbessert remote über die konfigurierte Engine
  (`process_prompt_enhancer()` erkennt am Engine-Namen, dass remote gearbeitet
  wird, `wgp.py:6409`).
- **Local 27B** — lädt Qwen3.8-27B lokal (`enhancer_enabled=5`, `gguf_ptq1`) und
  gibt den VRAM danach wieder frei.

Drei Regler, alle gelten für **beide** Knöpfe:

- **Think** — WanGPs eigene Checkbox (Zeile 1). Gesetzt: lokal `K` im
  Enhancer-Modus (`wgp.py:6451` → `thinking_enabled`), remote der höchste
  `reasoning_effort` des Modells als `variant` (`opencode_backend.py:226`).
  Ungesetzt: kein Denken lokal, niedrigster Level remote (Anbieter haben kein
  echtes „aus").
- **words** (Zeile 2, Preset-Dropdown neben dem Modus-Dropdown) — ersetzt die
  feste 150-Wort-Grenze in WanGPs Anweisungen
  (`shared/prompt_enhancer/prompt_enhance_utils.py:25/34/42/51/56`):
  die Presets `no limit` (0/0), `short - 150 words`, `medium - 300 words` und
  `long - 500 words` setzen Min auf 0; `custom (min/max)` blendet die beiden
  kleinen Zahlenfelder `min:`/`max:` ein (0 = keine Grenze). Aufgelöst wird das
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
- **`2f6f3e6`, `446da1e` und `61f25ae` sind gepusht.** Ob der geladene Klon sie
  schon hat, ist offen (Stand vor dem letzten Neustart: `d429ffb`, 5 Inputs).
  Nach dem Neustart prüfen: beide Knöpfe **6 Inputs**
  (`state, prompt, Think, Preset, Min, Max`), Preset wechseln → Felder
  verschwinden, `custom` → sie kommen mit ihren alten Werten zurück.

## Technisches, das man sonst neu herausfinden muss

- **Nur ein lokaler LLM-Slot:** `resolve_role_engine()` ignoriert die Rolle. Das
  Plugin stellt `llm_engines.deepy` und `enhancer_enabled` nur für den Klick um
  und restauriert danach exakt.
- **Aufruf:** `process_prompt_enhancer(model_type, model_def, mode, [prompt],
  None, None, is_image, audio_only, -1,
  prompt_enhancer_instructions=…, text_encoder_max_tokens=…)`.
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
  - Die Min/Max-Felder nutzen **Gradios eigenes Label** (`label="min:"` /
    `"max:"`, `show_label=True`): es steht direkt über der Eingabe, kostet keine
    eigene Komponente und hält die Formulargruppe zusammen. Die früheren
    `gr.HTML`-Beschriftungen sind weg — genau deshalb ist der Unwrap-Code jetzt
    kurz.
  - Das Wortzahl-Preset ist ein `gr.Dropdown`, also ebenfalls FormComponent, und
    läuft durch dieselbe Unwrap-/Move-Mechanik wie die Zahlenfelder.
  - `visible=False` ändert nur das Rendering: die beiden Zahlenfelder werden
    weiter mitgesendet, ihr Wert überlebt also das Umschalten auf ein Preset und
    zurück (live geprüft).
  - Die Regler werden **nach Typ** ausgelesen (`*controls`), weil die
    Think-Checkbox fehlen kann: `bool` = Think, `str` = Preset-Schlüssel, Zahlen
    = Custom-Felder. Feste Reihenfolge der Klick-Eingaben:
    `state, prompt, Think, Preset, Min, Max`.
- **Config-Keys:** `local_enhance_min_words`, `local_enhance_max_words`
  (`local_enhance_word_limit` ist Altbestand und dient als Fallback für Max).
  Defaults: Min 0 (= keine Untergrenze), Max 150.
- Ist Min > Max, werden beide getauscht.

## Prüfen

- Syntax/Import (WanGP-venv, aus dem WanGP-Ordner):
  `cd ~/git/Wan2GP && ./.wan2gp/bin/python -c "import sys; sys.path.insert(0,'/home/stefan/git/wan2gp-local-enhance'); import plugin; print(plugin.PlugIn_Name)"`
- UI ohne WanGP-Start: `dev/ui_preview.py` baut die Umgebung nach (Row mit
  eingebautem Knopf + verstecktem `gr.Text` + Dropdown + Think-Checkbox, danach
  die `insert_after`-Mechanik `pop(-1)` + `insert(target_index+1, …)`) und gibt
  den Komponentenbaum aus. Aufruf aus dem WanGP-Ordner:
  `./.wan2gp/bin/python ~/git/wan2gp-local-enhance/dev/ui_preview.py 7899`.
  Erwartung:
  Zeile 1 = `[HTML, Button, Button, Checkbox]`,
  Zeile 2 (der `Form` mit dem Dropdown) =
  `[Dropdown, Dropdown(preset "words"), Number(min:), Number(max:)]`,
  Regler = `[Checkbox, Dropdown, Number, Number]` → **6** Klick-Eingaben, und im
  Layout darf keine Komponente doppelt eingetragen sein.
  `PREVIEW_MIN`/`PREVIEW_MAX` setzen die Startwerte; `PREVIEW_MAX=150` ergibt den
  Preset-Fall (Felder `display:none`), der Default `1500` den Custom-Fall.
- Auflösung ohne UI (schneller Matrix-Check gegen `_read_controls`):
  `(False,"off",0,1500)` → `(0,0)`, `(False,"300",100,1500)` → `(0,300)`,
  `(False,"custom",800,100)` → `(100,800)`, `(False,None,0,1500)` → `(0,1500)`.
- Bild der Zeile ohne Browserfenster (Chromium ist installiert, Playwright nicht):
  `--headless=new --user-data-dir=.ui-shots/prof --force-device-scale-factor=2
  --virtual-time-budget=9000 --window-size=780,300 --screenshot=….png
  "http://127.0.0.1:7899/?__theme=dark"` (mit `env -u DISPLAY`, sonst bricht
  Chromium an der X11-Autorisierung ab). `.ui-shots/` ist ignoriert und
  Crashpad/Benutzerprofil wandern dorthin.
- End-to-End (WanGP läuft): `http://127.0.0.1:7860/config` abrufen — die
  Dependencies von `local_enhance_local_btn` und `local_enhance_remote_btn`
  müssen **6 Inputs** haben (`state, prompt, Think, Preset, Min, Max`).
- Schreibzugriffe außerhalb des Workspace (WanGP-Klon, WanGP-Repo) brauchen in der
  Sandbox `danger-full-access`.

## Offen

- Modelle mit **eigenen** Enhancer-Anweisungen: dort wirken Min/Max nicht, weil
  `model_def` gegen die übergebenen Anweisungen gewinnt (`wgp.py:6476`).
- Das Denk-Budget der 27B ist hart auf **2000 Tokens** begrenzt
  (`shared/prompt_enhancer/qwen35_text.py:64`) — es gibt keinen Config-Key dafür.
- Der Tab-Knopf hat keine eigenen Widgets; er nutzt die Regler aus Zeile 1/2.
