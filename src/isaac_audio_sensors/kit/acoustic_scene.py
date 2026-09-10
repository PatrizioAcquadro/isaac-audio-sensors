"""Kit preparation UI over the shared USD acoustic-scene service."""

from __future__ import annotations

import json

from isaac_audio_sensors.core.acoustics.materials import (
    MATERIAL_TABLE,
    resolve_material,
)
from isaac_audio_sensors.isaac.acoustic_scene import AcousticSceneSession
from isaac_audio_sensors.isaac.acoustic_scene.session import (
    DYNAMIC,
    INCLUDE,
    PARTITION,
    REPRESENTATION,
    SETTINGS,
)
from isaac_audio_sensors.isaac.acoustic_scene.steam import converted_material

from .acoustic_scene_editor import (
    coefficient_changes,
    coefficient_reset,
    selected_objects,
    selection_curves,
)


def edit_with_undo(session, paths, values):
    """One Kit undo command restores only the authored acoustic properties."""
    import omni.kit.commands
    from pxr import Sdf

    class AcousticSceneEditCommand(omni.kit.commands.Command):
        def __init__(self, session, paths, values):
            self.session, self.paths, self.values = session, paths, values
            self.layer = session.stage.GetEditTarget().GetLayer()
            self.target = session.stage.GetEditTarget()
            self.before = Sdf.Layer.CreateAnonymous()
            self.saved = {}
            for path in paths:
                for name in values:
                    prop = self.target.MapToSpecPath(
                        Sdf.Path(path).AppendProperty(name)
                    )
                    exists = self.layer.GetPropertyAtPath(prop) is not None
                    self.saved[prop] = exists
                    if exists:
                        Sdf.CreatePrimInLayer(self.before, prop.GetPrimPath())
                        Sdf.CopySpec(self.layer, prop, self.before, prop)

        def do(self):
            from pxr import Usd

            session = self.session
            temporary = session.closed
            if temporary:
                session = AcousticSceneSession(session.stage, session.roots)
            try:
                with Usd.EditContext(session.stage, self.target):
                    return session.edit(self.paths, self.values)
            finally:
                if temporary:
                    session.close()

        def undo(self):
            with Sdf.ChangeBlock():
                for prop, exists in self.saved.items():
                    if exists:
                        Sdf.CopySpec(self.before, prop, self.layer, prop)
                    elif self.layer.GetPropertyAtPath(prop):
                        edit = Sdf.BatchNamespaceEdit()
                        edit.Add(prop, Sdf.Path.emptyPath)
                        self.layer.Apply(edit)
            if not self.session.closed:
                self.session.refresh()

    # Kit owns command instances on the undo stack, independently of panel refreshes.
    omni.kit.commands.register(AcousticSceneEditCommand)
    return omni.kit.commands.execute(
        "AcousticSceneEdit", session=session, paths=tuple(paths), values=dict(values)
    )


class AcousticScenePanel:
    """Stage selection is the authoring target; edits remain pending until Apply."""

    def __init__(self, ui):
        self.ui = ui
        self.session = None
        self.closed = False
        self._subscription = self._selection_subscription = None
        self._elapsed = 0.0
        self._render_signature = self._selection_signature = None
        self._settings_signature = None
        self._syncing = False
        self._dirty = set()
        self._proxy_targets = ()
        self.section_frames = {}
        self.last_error = None

    def _section(self, title, collapsed=True):
        from contextlib import contextmanager

        @contextmanager
        def section():
            frame = self.ui.CollapsableFrame(title, collapsed=collapsed, height=0)
            self.section_frames[title] = frame
            with frame, self.ui.VStack(spacing=6, height=0):
                yield

        return section()

    def _field(self, label, *, changed=None):
        from .window import _FIELD_STYLES

        with self.ui.HStack(height=24, spacing=6):
            self.ui.Label(label, width=135)
            field = self.ui.StringField(style=_FIELD_STYLES["editable"])
        if changed:
            field.model.add_value_changed_fn(changed)
        return field.model

    def build(self):
        ui = self.ui
        self.presets = tuple(
            k for k, v in MATERIAL_TABLE.items() if v.absorption is not None
        )
        self.scatter_presets = tuple(
            k for k, v in MATERIAL_TABLE.items() if v.scattering_citation
        )
        with ui.VStack(spacing=8, height=0):
            self.status = ui.Label("Scene not prepared", height=24)
            self.counts = ui.Label(
                "Import the open stage to begin.", word_wrap=True, height=0
            )
            self.message = ui.Label("", word_wrap=True, height=0)
            with self._section("Scene", collapsed=False):
                self.scene_label = ui.Label("", word_wrap=True, height=0)
                self.roots = self._field("Roots (blank = all)")
                with ui.HStack(height=26, spacing=4):
                    ui.Button(
                        "Use selection as roots", clicked_fn=self.use_selection_roots
                    )
                    ui.Button("Entire stage", clicked_fn=self.use_entire_stage)
                with ui.HStack(height=28, spacing=4):
                    ui.Button("Import / Update", clicked_fn=self.import_scene)
                    ui.Button("Undo", width=65, clicked_fn=self.undo)
                    ui.Button("Redo", width=65, clicked_fn=self.redo)
            with self._section("Objects", collapsed=False):
                self.filter = self._field(
                    "Find name or path", changed=lambda _: self._render()
                )
                self.object_filter = ui.ComboBox(
                    0,
                    "All objects",
                    "Selected",
                    "Material defaults",
                    "Dynamic",
                    "Excluded",
                ).model
                self.object_filter.add_item_changed_fn(lambda *_: self._render())
                with ui.HStack(height=20):
                    ui.Label("Object / selection", width=ui.Fraction(2))
                    ui.Label("Included", width=75)
                    ui.Label("Motion", width=70)
                    ui.Label("Material source", width=ui.Fraction(1))
                with ui.ScrollingFrame(height=125):
                    self.rows = ui.Frame()
                ui.Label(
                    "Select in the viewport or Stage; use + / - to extend selection.",
                    word_wrap=True,
                    height=0,
                )
            with self._section("Selection", collapsed=False):
                self.selection_label = ui.Label(
                    "Select an object in the viewport or Stage.",
                    word_wrap=True,
                    height=0,
                )
                self.selection_state = ui.Label("", word_wrap=True, height=0)
                with ui.HStack(height=26, spacing=4):
                    for label, value in [
                        ("Include", True),
                        ("Exclude", False),
                        ("Automatic inclusion", None),
                    ]:
                        ui.Button(
                            label, clicked_fn=lambda v=value: self.edit({INCLUDE: v})
                        )
                with ui.HStack(height=26, spacing=4):
                    for value in ("auto", "static", "dynamic"):
                        ui.Button(
                            value.title() + " motion",
                            clicked_fn=lambda v=value: self.edit({DYNAMIC: v}),
                        )
            with self._section("Material", collapsed=False):
                labels = [self._preset_label(k) for k in self.presets]
                self.material = ui.ComboBox(
                    0, "Automatic / custom / mixed", *labels
                ).model
                self.material.add_item_changed_fn(lambda *_: self._describe_preset())
                self.material_description = ui.Label("", word_wrap=True, height=0)
                with ui.HStack(height=26, spacing=4):
                    ui.Button("Assign preset", clicked_fn=self.assign_material)
                    ui.Button(
                        "Restore automatic material", clicked_fn=self.clear_material
                    )
                with self._section("Coefficient overrides"):
                    ui.Label(
                        "Effective values below. Apply changes only edited families. "
                        "Reset removes the local override.",
                        word_wrap=True,
                        height=0,
                    )
                    self.coefficient_fields = {}
                    self.frequency_fields = {}
                    for label, key in [
                        ("Absorption (0-1)", "ias:absorption"),
                        ("Scattering (0-1)", "ias:scattering"),
                        ("Transmission loss (dB)", "ias:transmission_loss_db"),
                    ]:
                        self.coefficient_fields[key] = self._field(
                            label, changed=lambda _, k=key: self._mark_dirty(k)
                        )
                        self.frequency_fields[key] = self._field(
                            "Frequencies (Hz)",
                            changed=lambda _, k=key: self._mark_dirty(k),
                        )
                        ui.Button(
                            "Reset " + label.split(" (")[0].lower() + " override",
                            height=22,
                            clicked_fn=lambda k=key: self.edit(coefficient_reset(k)),
                        )
                    self.pending = ui.Label("No pending coefficient changes", height=0)
                    ui.Button(
                        "Apply edited coefficients",
                        height=28,
                        clicked_fn=self.apply_coefficients,
                    )
                with self._section("Documented scattering"):
                    self.scattering_preset = ui.ComboBox(
                        0, *[self._preset_label(k) for k in self.scatter_presets]
                    ).model
                    self.scattering_description = ui.Label("", word_wrap=True, height=0)
                    self.scattering_preset.add_item_changed_fn(
                        lambda *_: self._describe_scattering()
                    )
                    self._describe_scattering()
                    ui.Button(
                        "Assign scattering only",
                        height=26,
                        clicked_fn=self.assign_scattering,
                    )
                with self._section("Effective values and sources"):
                    self.details = ui.Label(
                        "Select an imported object", word_wrap=True, height=0
                    )
            with self._section("Structures and acoustic geometry"):
                self.structure_state = ui.Label("", word_wrap=True, height=0)
                self.partition = self._field("Structure ID")
                with ui.HStack(height=26, spacing=4):
                    ui.Button(
                        "Group selection",
                        clicked_fn=lambda: self.edit(
                            {PARTITION: self.partition.get_value_as_string().strip()}
                        ),
                    )
                    ui.Button(
                        "Separate selection",
                        clicked_fn=lambda: self.edit({PARTITION: None}),
                    )
                ui.Label(
                    "Remember the selected proxy, then select its owner and assign.",
                    word_wrap=True,
                    height=0,
                )
                self.proxy_label = ui.Label(
                    "No proxy remembered", word_wrap=True, height=0
                )
                with ui.HStack(height=26, spacing=4):
                    ui.Button("Remember selected proxy", clicked_fn=self.remember_proxy)
                    ui.Button("Assign to selection", clicked_fn=self.assign_proxy)
                ui.Button(
                    "Restore original geometry",
                    height=24,
                    clicked_fn=lambda: self.edit({REPRESENTATION: None}),
                )
            with self._section("Scene defaults and associations"):
                self.fallback_material = ui.ComboBox(
                    self.presets.index("pra.hard_surface"),
                    *[self._preset_label(k) for k in self.presets],
                ).model
                with ui.HStack(height=24):
                    ui.Label("Fallback scattering", width=135)
                    self.fallback_scattering = ui.FloatDrag(
                        min=0, max=1, step=0.01
                    ).model
                self.fallback_scattering.set_value(0.05)
                ui.Label(
                    "Construction label = preset ID, one per line. "
                    "Name matches are inferences, including documented presets.",
                    word_wrap=True,
                    height=0,
                )
                self.associations = ui.StringField(multiline=True, height=85).model
                ui.Button(
                    "Apply scene defaults", height=26, clicked_fn=self.apply_defaults
                )
            with self._section("Issues and provider"):
                self.issues_frame = ui.Frame()
                self.library = self._field("Steam library")
                ui.Button("Verify native scene", height=26, clicked_fn=self.verify)
                ui.Label(
                    "Verification checks geometry only. "
                    "Microphone audio is planned in 08.2. "
                    "Steam uses the qualified CPU / Embree library.",
                    word_wrap=True,
                    height=0,
                )
        try:
            import omni.kit.app
            import omni.usd
        except ImportError:
            return
        self._subscription = (
            omni.kit.app.get_app()
            .get_update_event_stream()
            .create_subscription_to_pop(self._tick, name="IAS acoustic preparation")
        )
        self._selection_subscription = (
            omni.usd.get_context()
            .get_stage_event_stream()
            .create_subscription_to_pop(
                self._stage_event, name="IAS acoustic preparation selection"
            )
        )

    @staticmethod
    def _preset_label(key):
        label = key.split(".", 1)[1].replace("_", " ")
        evidence = "Legacy nominal" if key.startswith("nominal.") else "Documented"
        return f"{label} [{evidence}]"

    def _describe_preset(self):
        index = self.material.get_item_value_model().get_value_as_int()
        self.material_description.text = (
            "No uniform preset selected. Inspect effective values below."
            if index == 0
            else MATERIAL_TABLE[self.presets[index - 1]].description
        )

    def _describe_scattering(self):
        index = self.scattering_preset.get_item_value_model().get_value_as_int()
        entry = MATERIAL_TABLE[self.scatter_presets[index]]
        self.scattering_description.text = (
            f"{entry.description}. Use only for this construction; "
            "not for individually modelled furniture or generic walls. "
            f"Source curve: {entry.scattering} "
            f"at {entry.scattering_band_centers_hz} Hz."
        )

    def _context(self):
        import omni.usd

        context = omni.usd.get_context()
        stage = context.get_stage()
        if stage is None:
            raise ValueError("Open a USD stage first")
        roots = tuple(self.roots.get_value_as_string().split()) or ("/",)
        if (
            self.session is None
            or self.session.stage != stage
            or self.session.roots != roots
        ):
            if self.session:
                self.session.close()
            self.session = AcousticSceneSession(stage, roots)
            self._selection_signature = self._settings_signature = None
        return context

    def _paths(self):
        paths = self._context().get_selection().get_selected_prim_paths()
        if not paths:
            raise ValueError("Select one or more objects in the viewport or Stage")
        return paths

    def _run(self, operation):
        try:
            operation()
            self.last_error = None
            self.message.text = ""
            self._render()
        except Exception as exc:
            self.last_error = str(exc)
            self.message.text = f"Cannot apply: {exc}"

    def use_selection_roots(self):
        def run():
            paths = self._paths()
            self.roots.set_value(" ".join(paths))
            self._context()
            self.session.refresh()

        self._run(run)

    def use_entire_stage(self):
        self.roots.set_value("")
        self.import_scene()

    def import_scene(self):
        def run():
            self._context()
            self.session.refresh()

        self._run(run)

    def edit(self, values):
        def run():
            paths = self._paths()
            if PARTITION in values and values[PARTITION] == "":
                raise ValueError("Enter a nonempty structure ID")
            edit_with_undo(self.session, paths, values)
            self._selection_signature = None

        self._run(run)

    @staticmethod
    def _material_overrides():
        result = {"ias:acoustic_material_id": None, "ias:material": None}
        for key in ("ias:absorption", "ias:scattering", "ias:transmission_loss_db"):
            result.update(coefficient_reset(key))
        return result

    def assign_material(self):
        index = self.material.get_item_value_model().get_value_as_int()
        if index == 0:
            self.message.text = (
                "Choose a preset first; Restore automatic material removes overrides."
            )
            return
        values = self._material_overrides()
        values["ias:acoustic_material_id"] = self.presets[index - 1]
        self.edit(values)

    def assign_scattering(self):
        index = self.scattering_preset.get_item_value_model().get_value_as_int()
        values = coefficient_reset("ias:scattering")
        values["ias:scattering_material_id"] = self.scatter_presets[index]
        self.edit(values)

    def clear_material(self):
        self.edit(self._material_overrides())

    def _mark_dirty(self, key):
        if not self._syncing:
            self._dirty.add(key)
            self.pending.text = "Pending: " + ", ".join(
                k.removeprefix("ias:") for k in sorted(self._dirty)
            )

    def apply_coefficients(self):
        def run():
            paths = self._paths()
            values = coefficient_changes(
                {
                    k: m.get_value_as_string()
                    for k, m in self.coefficient_fields.items()
                },
                {k: m.get_value_as_string() for k, m in self.frequency_fields.items()},
                self._dirty,
            )
            edit_with_undo(self.session, paths, values)
            self._selection_signature = None

        self._run(run)

    def remember_proxy(self):
        def run():
            self._proxy_targets = tuple(self._paths())
            self.proxy_label.text = "Proxy: " + ", ".join(self._proxy_targets)

        self._run(run)

    def assign_proxy(self):
        if not self._proxy_targets:
            self.message.text = "Select and remember the proxy geometry first."
            return
        self.edit({REPRESENTATION: self._proxy_targets})

    def apply_defaults(self):
        def run():
            self._context()
            associations = dict(
                line.split("=", 1)
                for line in self.associations.get_value_as_string().splitlines()
                if line.strip()
            )
            associations = {k.strip(): v.strip() for k, v in associations.items()}
            for key, value in associations.items():
                if not key:
                    raise ValueError("Association labels cannot be empty")
                resolve_material(value)
            scatter = self.fallback_scattering.get_value_as_float()
            if not 0 <= scatter <= 1:
                raise ValueError("Fallback scattering must be in [0, 1]")
            self.session.stage.DefinePrim(SETTINGS, "Scope")
            index = self.fallback_material.get_item_value_model().get_value_as_int()
            edit_with_undo(
                self.session,
                [SETTINGS],
                {
                    "ias:material_associations": json.dumps(associations),
                    "ias:fallback_material": self.presets[index],
                    "ias:fallback_scattering": scatter,
                },
            )

        self._run(run)

    def verify(self):
        def run():
            self._context()
            self.session.refresh()
            self.session.verify_provider(self.library.get_value_as_string())

        self._run(run)

    def undo(self):
        import omni.kit.undo

        self._history(omni.kit.undo.undo)

    def _history(self, operation):
        def run():
            operation()
            if self.session:
                self.session.refresh()

        self._run(run)

    def redo(self):
        import omni.kit.undo

        self._history(omni.kit.undo.redo)

    def _select(self, path, extend=False):
        import omni.usd

        selection = omni.usd.get_context().get_selection()
        paths = selection.get_selected_prim_paths() if extend else []
        if path in paths:
            paths.remove(path)
        else:
            paths.append(path)
        selection.set_selected_prim_paths(paths, False)
        self._render()

    def _sync_selection(self, selected, objects):
        signature = (
            tuple(selected),
            tuple(
                (o.path, o.materials, o.dynamic, o.partition, o.planar) for o in objects
            ),
        )
        if signature == self._selection_signature:
            return
        self._selection_signature = signature
        self._syncing = True
        try:
            curves = selection_curves(objects)
            for key, curve in curves.items():
                mixed = curve == "mixed"
                self.coefficient_fields[key].set_value(
                    "Mixed"
                    if mixed
                    else ""
                    if curve is None
                    else " ".join(f"{v:g}" for v in curve.values)
                )
                self.frequency_fields[key].set_value(
                    "Mixed"
                    if mixed
                    else ""
                    if curve is None
                    else " ".join(f"{v:g}" for v in curve.frequencies)
                )
            origins = {m.absorption.origin for o in objects for m in o.materials}
            preset = (
                next(iter(origins)).removeprefix("preset:")
                if len(origins) == 1
                else None
            )
            self.material.get_item_value_model().set_value(
                self.presets.index(preset) + 1 if preset in self.presets else 0
            )
            partitions = {o.partition for o in objects}
            self.partition.set_value(
                next(iter(partitions)) if len(partitions) == 1 else ""
            )
            self._dirty.clear()
            self.pending.text = "No pending coefficient changes"
            self._describe_preset()
        finally:
            self._syncing = False

    def _sync_defaults(self):
        from isaac_audio_sensors.isaac.acoustic_scene.materials import (
            DEFAULT_ASSOCIATIONS,
            attribute,
        )

        prim = self.session.stage.GetPrimAtPath(SETTINGS)
        signature = tuple(
            attribute(prim, key) if prim else None
            for key in (
                "ias:material_associations",
                "ias:fallback_material",
                "ias:fallback_scattering",
            )
        )
        if signature == self._settings_signature:
            return
        self._settings_signature = signature
        mapping, preset, scatter = signature
        mapping = json.loads(mapping) if mapping is not None else DEFAULT_ASSOCIATIONS
        self.associations.set_value("\n".join(f"{k} = {v}" for k, v in mapping.items()))
        self.fallback_material.get_item_value_model().set_value(
            self.presets.index(preset or "pra.hard_surface")
        )
        self.fallback_scattering.set_value(0.05 if scatter is None else scatter)

    def _render(self):
        if not self.session or self.closed:
            return
        import omni.usd

        summary = self.session.summary()
        state = summary["state"]
        self.status.text = state.capitalize()
        self.status.style = {"color": 0xFF5BB9E4 if summary["issues"] else 0xFF8FD1A1}
        self.counts.text = (
            f"{summary['objects']} objects | {len(summary['excluded'])} excluded | "
            f"{summary['triangles']} triangles | {summary['partitions']} structures | "
            f"{summary['dynamic']} dynamic | "
            f"{summary['fallback_materials']} material defaults"
        )
        self.scene_label.text = self.session.stage.GetRootLayer().GetDisplayName()
        selected = omni.usd.get_context().get_selection().get_selected_prim_paths()
        objects = selected_objects(self.session, selected)
        self.selection_label.text = (
            (
                f"{len(selected)} selected / {len(objects)} imported meshes: "
                + ", ".join(p.rsplit("/", 1)[-1] for p in selected)
            )
            if selected
            else "Select an object in the viewport or Stage."
        )
        self.selection_state.text = (
            "Edits are inherited by descendants. "
            "For instance proxies, select the instance root to edit."
            if selected
            else ""
        )
        self._sync_selection(selected, objects)
        self._sync_defaults()
        query = self.filter.get_value_as_string().lower()
        mode = self.object_filter.get_item_value_model().get_value_as_int()
        with self.rows, self.ui.VStack(spacing=2, height=0):
            for path in (*self.session.objects, *self.session.excluded):
                obj = self.session.objects.get(path)
                chosen = path in selected
                source = "Excluded"
                if obj:
                    origins = {m.absorption.origin.split(":")[0] for m in obj.materials}
                    source = ", ".join(sorted(origins))
                default = obj and any(
                    m.transmission_db is None
                    or any(
                        c.origin.startswith("fallback:")
                        for c in (m.absorption, m.scattering)
                    )
                    for m in obj.materials
                )
                if (
                    query not in path.lower()
                    or (mode == 1 and obj not in objects)
                    or (mode == 2 and not default)
                    or (mode == 3 and (not obj or not obj.dynamic))
                    or (mode == 4 and obj)
                ):
                    continue
                with self.ui.HStack(height=24, spacing=4):
                    self.ui.Button(
                        "-" if chosen else "+",
                        width=24,
                        clicked_fn=lambda p=path: self._select(p, True),
                    )
                    self.ui.Button(
                        path.rsplit("/", 1)[-1],
                        width=self.ui.Fraction(2),
                        tooltip=path,
                        clicked_fn=lambda p=path: self._select(p),
                    )
                    self.ui.Label("Yes" if obj else "No", width=75)
                    self.ui.Label(
                        ("Dynamic" if obj.dynamic else "Static") if obj else "-",
                        width=70,
                    )
                    self.ui.Label(source, width=self.ui.Fraction(1))
        self.structure_state.text = (
            "\n".join(
                f"{o.path}: {o.partition}; "
                + ("planar transmission eligible" if o.planar else "opaque / nonplanar")
                for o in objects
            )
            or "Select imported geometry to inspect its structure."
        )
        details = []
        for obj in objects:
            details.append(obj.path)
            for material in obj.materials:
                for family in ("absorption", "scattering", "transmission_db"):
                    curve = getattr(material, family)
                    details.append(
                        f"{family}: opaque fallback"
                        if curve is None
                        else f"{family}: {curve.values} at {curve.frequencies} Hz\n"
                        f"{curve.origin} | {curve.evidence}"
                        + (f"\n{curve.citation}" if curve.citation else "")
                    )
                details.append(
                    f"Steam 400 / 2500 / 15000 Hz: "
                    f"{converted_material(material, obj.planar)}\n"
                    "Log-frequency interpolation; endpoint hold outside source bands. "
                    "Scattering sampled at 1000 Hz."
                )
        self.details.text = (
            "\n".join(details) or "No imported surface in this selection."
        )
        with self.issues_frame, self.ui.VStack(spacing=4, height=0):
            for issue in summary["issues"] + summary["warnings"]:
                path = next(
                    (
                        p
                        for p in (*self.session.objects, *self.session.excluded)
                        if p in issue
                    ),
                    None,
                )
                if path:
                    self.ui.Button(
                        issue, height=24, clicked_fn=lambda p=path: self._select(p)
                    )
                else:
                    self.ui.Label(issue, word_wrap=True, height=0)
            self.ui.Label(
                "Containment: " + str(summary["containment"]), word_wrap=True, height=0
            )

    def _stage_event(self, event):
        import omni.usd

        if event.type == int(omni.usd.StageEventType.CLOSING):
            if self.session:
                self.session.close()
                self.session = None
            self._proxy_targets = ()
            self.status.text = "Scene not prepared"
            self.counts.text = "Open and import a stage."
            self.selection_label.text = "No stage"
            self.details.text = ""
            with self.rows:
                self.ui.Label("")
        elif event.type == int(omni.usd.StageEventType.SELECTION_CHANGED):
            self._render()

    def _tick(self, event):
        if not self.session or self.closed:
            return
        self._elapsed += event.payload.get("dt", 0.0)
        if self._elapsed < 0.1:
            return
        self._elapsed = 0.0
        try:
            import omni.timeline

            timeline = omni.timeline.get_timeline_interface()
            time = (
                timeline.get_current_time() * self.session.stage.GetTimeCodesPerSecond()
            )
            self.session.refresh(time)
            signature = (
                tuple(
                    (p, o.partition, o.materials, o.dynamic, o.planar)
                    for p, o in self.session.objects.items()
                ),
                tuple(self.session.excluded.items()),
                tuple(self.session.issues),
                tuple(self.session.warnings),
                repr(self.session.containment),
                bool(self.session.provider and self.session.provider.verified),
            )
            if signature != self._render_signature:
                self._render_signature = signature
                self._render()
        except Exception as exc:
            self.message.text = f"Preparation update error: {exc}"

    def close(self):
        self.closed = True
        self._subscription = self._selection_subscription = None
        if self.session:
            self.session.close()
