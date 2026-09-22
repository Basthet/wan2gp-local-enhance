"""Local Enhance - lokaler Prompt-Enhancer, unabhaengig von der Deepy-Engine.

Hintergrund
-----------
WanGP koppelt den Prompt Enhancer fest an die Deepy-Engine:

    # shared/remote_llm/config.py:397
    def resolve_role_engine(server_config, role):
        return str(normalize_llm_config(server_config)["deepy"])   # role wird ignoriert

    # shared/remote_llm/config.py:381
    normalized["prompt_enhancer"] = ENGINE_SAME_AS_DEEPY

    # wgp.py:6505
    local_runtime = not is_remote_engine(resolve_role_engine(server_config, "prompt_enhancer"))

Laeuft Deepy also ueber OpenCode, nutzt auch der Enhance-Prompt-Knopf OpenCode.

Dieses Plugin umgeht das, ohne die Engine umzustellen. Der lokale Enhancer ist
namlich unabhaengig ladbar: ``ensure_prompt_enhancer_loaded()`` entscheidet allein
anhand von ``enhancer_enabled`` (ein Integer: 3/4/5 = 4B/9B/27B), nicht anhand der
Engine. Das Plugin ruft deshalb den lokalen Pfad direkt auf:

    ensure_prompt_enhancer_loaded()   -> laedt das lokale Qwen-Modell
    process_prompt_enhancer(...)      -> verbessert den Prompt
    unload_prompt_enhancer_runtime()  -> gibt den VRAM wieder frei

Voraussetzung: ``enhancer_enabled`` muss ungleich 0 sein (Config -> Prompt Enhancer /
Deepy -> LLM Engine auf ein lokales Qwen-Modell zeigen lassen). Der Wert bestimmt,
welches lokale Modell geladen wird.
"""

import sys
import time

import gradio as gr

from shared.utils.plugins import WAN2GPPlugin
from shared.utils.process_locks import acquire_GPU_ressources, release_GPU_ressources
from shared.utils.prompt_parser import serialize_prompt_blocks_with_prefix
from shared.remote_llm.config import engine_from_legacy_enhancer, is_remote_engine

PlugIn_Name = "Local Enhance"
PlugIn_Id = "LocalEnhance"

# Wie lange der lokale Enhancer im VRAM bleiben darf, bevor er wieder freigegeben
# wird. Innerhalb dieses Fensters ist ein zweiter Klick sofort schnell.
_GPU_HOLD_SECONDS = 0


def _main(name, default=None):
    """Live-Zugriff auf Globals des Hauptmoduls (nicht die eingefrorene Kopie)."""
    module = sys.modules.get("__main__")
    return getattr(module, name, default) if module is not None else default


class LocalEnhancePlugin(WAN2GPPlugin):
    def __init__(self):
        super().__init__()
        self.name = PlugIn_Name
        self.version = "1.0.0"
        self.description = (
            "Lokaler Prompt-Enhancer neben dem eingebauten Knopf - benutzt immer das "
            "lokale Qwen-Modell, auch wenn Deepy ueber eine Remote-Engine laeuft."
        )
        self.type = ["extension"]
        self._last_enhanced = ""
        self._last_source = ""

    # ------------------------------------------------------------------ Setup

    def setup_ui(self):
        self.request_component("state")
        self.request_component("refresh_form_trigger")
        self.request_component("prompt")
        self.request_global("get_current_model_settings")
        self.request_global("get_state_model_type")
        self.request_global("get_model_def")
        self.request_global("get_model_settings")
        self.request_global("get_prompt_enhancer_choices")
        self.add_tab(tab_id=PlugIn_Id, label=PlugIn_Name, component_constructor=self.create_ui)
        # Zweiter Knopf direkt neben "Enhance Prompt". Schlaegt das fehl, wird es
        # vom PluginManager geloggt und der Tab oben funktioniert trotzdem.
        try:
            self.insert_after("prompt_enhancer_btn", self.create_inline_button)
        except Exception as exc:  # noqa: BLE001
            print(f"[{PlugIn_Name}] Konnte den Inline-Knopf nicht anfordern: {exc}")

    # ------------------------------------------------------------- Hilfsmittel

    @staticmethod
    def _resolve_mode(model_def, audio_only, image_mode):
        """Standard-Enhancer-Modus fuer das aktuelle Modell ermitteln."""
        chooser = _main("get_prompt_enhancer_choices")
        if chooser is None:
            return "T"
        try:
            choices, default, _definition = chooser(
                model_def, audio_only, image_mode, include_disabled=False
            )
        except Exception:
            return "T"
        if default:
            return str(default)
        if choices:
            return str(choices[0][1])
        return "T"

    @staticmethod
    def _local_enhancer_ready():
        """Ist ein lokales Enhancer-Modell konfiguriert?"""
        config = _main("server_config") or {}
        try:
            return int(config.get("enhancer_enabled", 0) or 0) > 0
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _variant_label():
        """Welches lokale Modell antwortet? Macht die Herkunft eindeutig."""
        config = _main("server_config") or {}
        try:
            number = int(config.get("enhancer_enabled", 0) or 0)
        except (TypeError, ValueError):
            number = 0
        return {
            1: "Llama 3.2 3B",
            2: "Llama Joy 8B",
            3: "Qwen3.5-4B",
            4: "Qwen3.5-9B",
            5: "Qwen3.8-27B",
        }.get(number, f"Modell {number}")

    @staticmethod
    def _local_engine_name():
        """Engine-Name, der zu enhancer_enabled gehoert (3 -> qwen35_4b usw.)."""
        config = _main("server_config") or {}
        try:
            number = int(config.get("enhancer_enabled", 0) or 0)
        except (TypeError, ValueError):
            number = 0
        return engine_from_legacy_enhancer(number)

    # -------------------------------------------------------------- Kernlogik

    def enhance(self, state, text):
        """Lokalen Enhancer auf `text` anwenden. Laeuft im GPU-Kontext."""
        text = str(text or "").strip()
        if not text:
            return "", "Bitte zuerst einen Prompt eingeben."

        if not self._local_enhancer_ready():
            return "", (
                "**Kein lokales Enhancer-Modell konfiguriert.**\n\n"
                "*Configuration → Prompt Enhancer / Deepy → Prompt Enhancer / Deepy LLM Engine* "
                "auf ein lokales Qwen-Modell stellen (4B, 9B oder 27B) und speichern. "
                "Der Enhancer nutzt dann dieses Modell, auch wenn Deepy remote bleibt."
            )

        get_state_model_type = _main("get_state_model_type")
        get_model_def = _main("get_model_def")
        get_model_settings = _main("get_model_settings")
        ensure_loaded = _main("ensure_prompt_enhancer_loaded")
        process = _main("process_prompt_enhancer")
        unload_runtime = _main("unload_prompt_enhancer_runtime")
        wait_for_unload = _main("wait_for_model_unload")

        if not all((get_state_model_type, get_model_def, ensure_loaded, process)):
            return "", "**Interner Fehler:** WanGP-Funktionen nicht gefunden. Bitte melden."

        model_type = get_state_model_type(state)
        if not model_type:
            return "", "Kein Modell ausgewaehlt - bitte zuerst im Media Generator eines waehlen."

        model_def = get_model_def(model_type) or {}
        settings = get_model_settings(state, model_type) or {}
        audio_only = bool(model_def.get("audio_only", False))
        try:
            image_mode = int(settings.get("image_mode", 0) or 0)
        except (TypeError, ValueError):
            image_mode = 0
        is_image = image_mode > 0
        mode = self._resolve_mode(model_def, audio_only, image_mode)

        if callable(wait_for_unload):
            wait_for_unload()
        acquire_GPU_ressources(state, PlugIn_Id, PlugIn_Name, gr=gr)
        started = time.time()

        # Der lokale Pfad muss ERZWUNGEN werden. process_prompt_enhancer() prueft
        # selbst noch einmal resolve_role_engine(server_config, "prompt_enhancer")
        # und schickt die Anfrage sonst an die Remote-Engine (wgp.py:6409) - der
        # lokale Loader allein genuegt also nicht. Genau daran ist der erste
        # Versuch dieses Plugins gescheitert: die 9B wurde geladen, geantwortet
        # hat trotzdem OpenCode.
        config = _main("server_config") or {}
        llm_section = config.get("llm_engines")
        local_engine = self._local_engine_name()
        previous_engine = None
        flipped = False
        if isinstance(llm_section, dict) and llm_section.get("deepy") != local_engine:
            previous_engine = llm_section.get("deepy")
            llm_section["deepy"] = local_engine
            flipped = True

        try:
            ensure_loaded(override_profile=-1)
            prompts = process(
                model_type,
                model_def,
                mode,
                [text],
                None,      # image_start
                None,      # original_image_refs
                is_image,
                audio_only,
                -1,        # seed -> zufaellig
            )
        except Exception as exc:  # noqa: BLE001 - Fehler soll in der UI landen
            return "", f"**Enhancer fehlgeschlagen:** `{type(exc).__name__}: {exc}`"
        finally:
            # Engine sofort zurueckstellen - sie darf keinen Moment laenger
            # verstellt bleiben als der Aufruf dauert.
            if flipped and isinstance(llm_section, dict):
                llm_section["deepy"] = previous_engine
            # Modell sofort wieder freigeben: es teilt sich den VRAM mit dem
            # Generierungsmodell, und ein zweiter Klick laedt es in Sekunden neu.
            try:
                if callable(unload_runtime):
                    unload_runtime()
                offloadobj = _main("enhancer_offloadobj")
                if offloadobj is not None:
                    offloadobj.unload_all()
            except Exception:
                pass
            release_GPU_ressources(state, PlugIn_Id)

        if not prompts:
            return "", "Der Enhancer hat keinen Prompt zurueckgegeben."
        # process_prompt_enhancer() liefert pro Prompt eine Liste - WanGP liest
        # das Ergebnis ebenfalls als value[0] aus (siehe wgp.py:6696).
        first = prompts[0] if isinstance(prompts, (list, tuple)) else prompts
        while isinstance(first, (list, tuple)):
            first = first[0] if first else ""
        result = str(first or "").strip()
        if not result:
            return "", "Der Enhancer hat einen leeren Prompt zurueckgegeben."
        self._last_enhanced = result
        self._last_source = text
        seconds = time.time() - started
        return result, (
            f"Lokal verbessert mit **{self._variant_label()}** "
            f"(Modus `{mode}`) in {seconds:.1f}s. Nicht zufrieden? Nochmal klicken."
        )

    def _with_history(self, enhanced):
        """Historienzeile wie beim eingebauten Knopf voranstellen.

        Ergebnis::

            #!PROMPT!: der urspruengliche Prompt
            der verbesserte Prompt

        Dafuer wird WanGPs eigene Funktion benutzt, damit Format und
        Bereinigung (Zeilenumbrueche, Slash-Bloecke) identisch sind. Beim
        Generieren verwirft split_prompt_units() jede Zeile, die mit '#' beginnt,
        die Zeile ist also reine Information und stoert das Ergebnis nicht.
        """
        enhanced = str(enhanced or "").strip()
        source = str(self._last_source or "").strip()
        if not enhanced or not source or enhanced == source:
            return enhanced
        if enhanced.startswith("#!PROMPT!:"):
            return enhanced
        try:
            return serialize_prompt_blocks_with_prefix([enhanced], [source])
        except Exception:
            return enhanced

    def write_back(self, state, text):
        """Verbesserten Prompt in den Entwurf des Media Generators uebernehmen."""
        text = str(text or "").strip()
        if not text:
            return time.time(), "Nichts zu uebernehmen."
        get_settings = self.get_current_model_settings
        try:
            settings = get_settings(state)
            settings["prompt"] = self._with_history(text)
        except Exception as exc:  # noqa: BLE001
            return time.time(), f"**Uebernahme fehlgeschlagen:** `{exc}`"
        return time.time(), "In den Prompt des Media Generators uebernommen."

    # ------------------------------------------------- Knopf neben dem Original

    def create_inline_button(self):
        """Zweiter Knopf neben 'Enhance Prompt' - verbessert direkt im Feld."""
        prompt_component = getattr(self, "prompt", None)
        if prompt_component is None:
            # Ohne Zugriff auf das Prompfeld waere der Knopf nutzlos.
            return gr.Button("Lokal", visible=False)
        button = gr.Button(
            "Local",
            size="lg",
            scale=1,
            elem_classes="btn_centered",
        )
        button.click(
            fn=self.enhance_inline,
            inputs=[self.state, prompt_component],
            outputs=[prompt_component],
            show_progress="hidden",
        )
        return button

    def enhance_inline(self, state, text):
        """Wie enhance(), schreibt das Ergebnis aber direkt ins Prompfeld."""
        result, status = self.enhance(state, text)
        if not result:
            gr.Warning(str(status).replace("**", "").replace("`", ""))
            return gr.update()
        gr.Info(f"Local: verbessert mit {self._variant_label()}")
        return self._with_history(result)

    # ------------------------------------------------------------------- UI

    def create_ui(self, api_session):
        state = self.state
        refresh_trigger = getattr(self, "refresh_form_trigger", None)

        try:
            current_prompt = str(self.get_current_model_settings(state.value).get("prompt", "") or "")
        except Exception:
            current_prompt = ""

        with gr.Column():
            gr.HTML(
                "<b>Local Enhance</b><br>"
                "Verbessert einen Prompt mit dem <b>lokalen</b> Qwen-Modell - unabhaengig davon, "
                "welche Engine Deepy gerade benutzt. Die Engine wird dabei <b>nicht</b> umgestellt "
                "und es werden <b>keine</b> Remote-Tokens verbraucht."
            )
            text_in = gr.Textbox(
                label="Prompt",
                value=current_prompt,
                lines=5,
                placeholder="Prompt eingeben oder aus dem Media Generator uebernehmen lassen ...",
            )
            with gr.Row():
                enhance_btn = gr.Button("Lokal verbessern", variant="primary")
                copy_btn = gr.Button(
                    "Prompt aus Hauptformular holen",
                    visible=True,
                )
            text_out = gr.Textbox(label="Verbesserter Prompt", lines=5, interactive=True)
            with gr.Row():
                if refresh_trigger is not None:
                    apply_btn = gr.Button("In den Media Generator uebernehmen")
                else:
                    apply_btn = None
            status = gr.Markdown()

        self.on_tab_outputs = [text_in]

        enhance_btn.click(fn=self.enhance, inputs=[state, text_in], outputs=[text_out, status])

        def pull_from_form(state_value):
            try:
                return str(self.get_current_model_settings(state_value).get("prompt", "") or "")
            except Exception:
                return ""

        copy_btn.click(fn=pull_from_form, inputs=[state], outputs=[text_in], show_progress="hidden")

        if apply_btn is not None:
            apply_btn.click(
                fn=self.write_back,
                inputs=[state, text_out],
                outputs=[refresh_trigger, status],
            )

        return None

    # ------------------------------------------------------------ Tab-Wechsel

    def on_tab_select(self, state):
        """Beim Wechsel auf den Tab den aktuellen Prompt des Panels anzeigen."""
        try:
            return str(self.get_current_model_settings(state).get("prompt", "") or "")
        except Exception:
            return ""
