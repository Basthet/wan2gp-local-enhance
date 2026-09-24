"""Vorschau der Enhancer-Zeile und des Plugin-Tabs - ohne WanGP zu starten.

Baut genau die Umgebung nach, in der create_inline_button() laeuft:

    gr.Row -> [eingebauter Knopf, verstecktes gr.Text, Dropdown, Think-Checkbox]

Das versteckte gr.Text IST WanGPs Modus-Komponente `prompt_enhancer`
(wgp.py:12169): sie traegt die Nutzerauswahl und wird hier wie vom
PluginManager vor der Insert-Verarbeitung auf das Plugin gesetzt
(shared/utils/plugins.py:1626-1627 vor 1649-1660).

Danach dieselbe insert_after-Mechanik wie shared/utils/plugins.py:1659.

Zum Schluss der Plugin-Tab: create_ui() laeuft laut Host NACH
create_inline_button() (wgp.py:13628 vor 13976). Der Nachbau oeffnet dafuer
denselben Container (gr.Column mit einer gr.Row) und ruft daraus
_attach_word_fields() auf - die beiden Wort-Regler wandern damit aus der
Knopfreihe in den Tab.

Das Skript gibt den Komponentenbaum, die Zahl der Klick-Eingaben und die URL
der Vorschau aus. Die Vorschau laeuft, bis der Prozess beendet wird.

Aufruf (aus dem WanGP-Ordner, mit dessen venv):

    ./.wan2gp/bin/python ~/git/wan2gp-local-enhance/dev/ui_preview.py [port]
    # http://127.0.0.1:7899/?__theme=dark

PREVIEW_MIN/PREVIEW_MAX setzen die Startwerte der Wortgrenze (Default 0/1500).

Screenshot ohne Browserfenster (aus dem Plugin-Ordner):

    env -u DISPLAY chromium --headless=new --no-sandbox --disable-gpu \
      --disable-dev-shm-usage --hide-scrollbars --user-data-dir=.ui-shots/prof \
      --force-device-scale-factor=2 --virtual-time-budget=9000 \
      --window-size=780,300 \
      --screenshot=.ui-shots/minmax.png "http://127.0.0.1:7899/?__theme=dark"

Das Bild zeigt nur die Zeile in einem Nahbau der Umgebung: die Knopfreihe wird
hier von .btn_centered-Regeln aus WanGPs eigenem CSS gestuetzt, die WanGP-Theme
selbst (Farben, Abstaende) fehlt.
"""
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
WAN2GP = Path("~/git/Wan2GP").expanduser()

sys.path.insert(0, str(WAN2GP))
sys.path.insert(0, str(REPO))

import gradio as gr  # noqa: E402
import plugin as P  # noqa: E402

# _word_range() liest die Grenzen aus __main__.server_config; hier stehen
# Beispielwerte (0 = keine Untergrenze).
server_config = {
    "local_enhance_min_words": int(os.environ.get("PREVIEW_MIN", 0)),
    "local_enhance_max_words": int(os.environ.get("PREVIEW_MAX", 1500)),
}

port = int(sys.argv[1]) if len(sys.argv) > 1 else 7899

p = P.LocalEnhancePlugin()

with gr.Blocks(title="Enhancer-Zeile") as demo:
    state = gr.State()
    prompt = gr.Textbox(label="Prompt", value="a cat sitting on a windowsill", lines=3)
    p.state = state
    p.prompt = prompt

    with gr.Row() as parent:
        builtin = gr.Button(
            "Enhance Prompt", visible=False, size="lg", scale=1,
            elem_classes="btn_centered",
        )
        hidden = gr.Text(value="T", visible=False, elem_id="prompt_enhancer")
        # show_label=False wie WanGP im On-Demand-Modus (wgp.py:12176) - nur so
        # zeigt die Vorschau denselben Versatz, den das Plugin ausgleicht.
        dropdown = gr.Dropdown(
            choices=["Based on Text Prompt", "Based on Image"],
            value="Based on Text Prompt",
            label="Enhance Prompt using a LLM",
            show_label=False,
            scale=5,
        )
        think = gr.Checkbox(
            label="Think", value=False, scale=1, elem_classes="cbx_centered",
        )

    # Der PluginManager setzt die angefragten Komponenten VOR der
    # Insert-Verarbeitung (shared/utils/plugins.py:1626-1627 vor 1649-1660).
    # Genau diese Reihenfolge hier: request_component() wie in setup_ui(), dann
    # das setattr, erst danach create_inline_button(). Nur so kann
    # _mode_components() beim Verdrahten schon etwas liefern.
    components = {
        "state": state,
        "prompt": prompt,
        "prompt_enhancer_btn": builtin,
        "prompt_enhancer": hidden,
    }
    p.request_component("prompt_enhancer")
    for comp_id in p.component_requests:
        if comp_id in components and getattr(p, comp_id, None) is None:
            setattr(p, comp_id, components[comp_id])

    # Wird gemessen, weil _mode_components() beim Verdrahten schon greifen muss:
    # der PluginManager setzt die Komponenten vor der Insert-Verarbeitung
    # (shared/utils/plugins.py:1626-1627 vor 1649-1660). Der Zaehler wird direkt
    # vor create_inline_button() genommen und muss 1 sein.
    mode_components_at_wiring = len(p._mode_components())
    with parent:
        p.create_inline_button()

    # insert_after: das zuletzt erzeugte Kind hinter den Zielknopf schieben
    target_index = parent.children.index(builtin)
    button_row = parent.children.pop(-1)
    parent.children.insert(target_index + 1, button_row)

    # Der Plugin-Tab. create_ui() laeuft beim Host erst nach
    # create_inline_button() (wgp.py:13628 vor 13976); genau dort holt
    # _attach_word_fields() die beiden Wort-Regler aus der Knopfreihe hierher.
    # Darunter folgt der Modell-Check-Block (Hinweis, eingeklappter
    # Detailbereich, Knopf). Der Klick wird hier NICHT ausgeloest - er wuerde
    # den Zwischenspeicher schreiben; geprueft wird nur die Verdrahtung.
    with gr.Column() as tab:
        with gr.Row() as word_row:
            p._attach_word_fields(word_row)
        check_btn, model_list, model_status = p._build_model_check_section()

    css = getattr(P, "_UI_CSS", "")
    # WanGP haelt .btn_centered in shared/gradio/ui_studio.css schmal; ohne diese
    # zwei Regeln zerdruecken die Knoepfe in Zeile 1 das Bild.
    css += (
        "#local_enhance_row .btn_centered{"
        "flex:0 0 auto !important;min-width:0 !important;width:max-content !important;}"
        "#local_enhance_row .cbx_centered{"
        "flex:0 0 auto !important;min-width:0 !important;width:max-content !important;}"
    )
    gr.HTML("<style>" + css + "</style>")

    def _types(container):
        return [
            type(child).__name__
            for child in (getattr(container, "children", None) or [])
        ]

    def _numbers(container):
        """Alle gr.Number-Felder unterhalb eines Containers, auch durch Gradios
        eigenen gr.Form-Wrapper hindurch (der entsteht beim Schliessen des
        Row-Kontexts aus aufeinanderfolgenden Formularfeldern)."""
        found = []
        for child in getattr(container, "children", None) or []:
            if isinstance(child, gr.Number):
                found.append(child)
            else:
                found.extend(_numbers(child))
        return found

    def _dump(component, depth=0):
        classes = getattr(component, "elem_classes", None) or []
        if isinstance(classes, str):
            classes = [classes]
        print(
            "  " * depth
            + f"{type(component).__name__} "
            f"id={getattr(component, 'elem_id', None) or ''!r} "
            f"classes={list(classes)} label={getattr(component, 'label', None)!r} "
            f"show_label={getattr(component, 'show_label', None)!r}"
        )
        for child in getattr(component, "children", None) or []:
            _dump(child, depth + 1)

    def _walk(component, seen, duplicates):
        key = id(component)
        if key in seen:
            duplicates.append(component)
            return
        seen.add(key)
        for child in getattr(component, "children", None) or []:
            _walk(child, seen, duplicates)

    print("=== Komponentenbaum (fremde Zeile) ===")
    _dump(parent)
    print("=== Komponentenbaum (Plugin-Tab) ===")
    _dump(tab)

    # Die fremde Formularzeile ist der gr.Form, in dem WanGPs versteckter
    # Modus-Text liegt. Darin darf jetzt nur noch das Modus-Dropdown stehen.
    form_row = next(
        (
            child
            for child in (getattr(parent, "children", None) or [])
            if child is not hidden
            and any(
                item is hidden
                for item in (getattr(child, "children", None) or [])
            )
        ),
        None,
    )
    mode_dropdown = next(
        (
            child
            for child in (getattr(form_row, "children", None) or [])
            if isinstance(child, gr.Dropdown)
        ),
        None,
    )

    print("=== Aufbau ===")
    print("Zeile 1:", _types(button_row))
    print(
        "Fremde Formularzeile:",
        _types(form_row) if form_row is not None else "nicht gefunden",
    )
    print("Tab-Wortzeile:", _types(word_row))
    print(
        "Wort-Regler im Tab:",
        [
            f"{type(field).__name__}({getattr(field, 'label', None)!r})"
            for field in _numbers(word_row)
        ],
    )
    print(
        "Modus-Dropdown show_label:",
        getattr(mode_dropdown, "show_label", None),
        "(erwartet True)",
    )

    # --- Modell-Check-Block -------------------------------------------------
    # Der Hinweis-Text steht wortgetreu als eigener Markdown-Block im Tab. Der
    # Vergleichswert ist hier absichtlich noch einmal als Literal hinterlegt (und
    # nicht aus dem Plugin geholt), damit die Vorschau den Wortlaut wirklich
    # prueft.
    expected_hint = (
        "*These limits are applied by rewriting the enhancer instructions this plugin supplies. "
        "Models that ship their own enhancer instructions ignore them.*"
    )

    def _descendants(container):
        for child in getattr(container, "children", None) or []:
            yield child
            yield from _descendants(child)

    nodes = list(_descendants(tab))
    accordions = [item for item in nodes if isinstance(item, gr.Accordion)]
    accordion = next(
        (item for item in accordions if item.label == "Which models ignore Min/Max?"),
        None,
    )
    markdown_values = [
        str(getattr(item, "value", "") or "")
        for item in nodes
        if isinstance(item, gr.Markdown)
    ]

    # Die Ziele des Knopf-Klicks kommen aus der Konfiguration, nicht aus dem
    # Objektbaum - der Klick selbst wird nicht ausgeloest (er wuerde den
    # Zwischenspeicher schreiben).
    config = demo.get_config_file()
    button_id = getattr(check_btn, "_id", None)
    click_deps = [
        dependency
        for dependency in config.get("dependencies", [])
        if any(
            isinstance(target, (list, tuple))
            and len(target) > 1
            and target[0] == button_id
            and target[1] == "click"
            for target in (dependency.get("targets") or [])
        )
    ]
    registry = getattr(demo, "blocks", None) or {}

    def _output_name(component_id):
        component = registry.get(component_id)
        if component is model_list:
            return "Liste"
        if component is model_status:
            return "Statuszeile"
        return type(component).__name__ if component is not None else "unbekannt"

    accordion_config = next(
        (
            entry
            for entry in config.get("components", [])
            if entry.get("id") == getattr(accordion, "_id", None)
        ),
        None,
    )
    accordion_props = (accordion_config or {}).get("props", {})

    print("=== Modell-Check ===")
    print("Hinweis-Text vorhanden:", expected_hint in markdown_values)
    print(
        "Detailbereich:",
        getattr(accordion, "label", None) if accordion is not None else "nicht gefunden",
        "| open:", getattr(accordion, "open", None),
        "| Konfiguration open:", accordion_props.get("open"),
        "(erwartet False)",
    )
    for dependency in click_deps:
        print(
            "Knopf-Klick:",
            [f"{component_id}:{_output_name(component_id)}"
             for component_id in dependency.get("outputs", [])],
            "| inputs:", dependency.get("inputs"),
            "(erwartet Liste, Statuszeile)",
        )
    if not click_deps:
        print("Knopf-Klick: nicht verdrahtet")
    print("Liste beim Aufbau:", repr(getattr(model_list, "value", None)))
    print("Status beim Aufbau:", repr(getattr(model_status, "value", None)))

    seen, duplicates = set(), []
    _walk(demo, seen, duplicates)
    print("=== Layout-Check ===")
    print("Komponenten im Baum:", len(seen))
    if duplicates:
        print(
            "DUPLIKATE:",
            [
                f"{type(c).__name__} id={getattr(c, 'elem_id', None)!r}"
                for c in duplicates
            ],
        )
    else:
        print("Duplikate: keine")

    mode_components = p._mode_components()
    controls = mode_components + p._control_components()
    image_components = p._image_components()
    print("=== Regler ===")
    print("mode:", [type(c).__name__ for c in mode_components])
    print(
        "controls:", [type(c).__name__ for c in controls],
        "-> click-inputs:", 2 + len(controls),
    )
    print(
        "image-inputs:", len(image_components),
        "-> local click-inputs:", 2 + len(controls) + len(image_components),
    )
    # Erwartung: Zeile 1 = [HTML, Button, Button, Checkbox], die fremde
    # Formularzeile = [Textbox(Modus), Dropdown], die Regler = [Textbox(Modus),
    # Checkbox, Number, Number], also 6 Klick-Eingaben fuer den Remote-Knopf und
    # 6 + Anzahl der Bild-Eingaben fuer den lokalen.
    print(
        "=== Erwartung ===",
        f"mode-components-at-wiring={mode_components_at_wiring} (erwartet 1),",
        f"remote={2 + len(controls)} (erwartet 6),",
        f"local={2 + len(controls) + len(image_components)}"
        f" (erwartet 6 + {len(image_components)} Bild-Eingaben)",
    )

    if duplicates:
        sys.exit(2)

demo.launch(
    server_name="127.0.0.1", server_port=port, quiet=True, prevent_thread_lock=True,
)
print(f"[dev/ui_preview] http://127.0.0.1:{port}/?__theme=dark", flush=True)
while True:
    time.sleep(1)
