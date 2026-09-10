"""Kit preparation UI over the shared USD acoustic-scene service."""

from __future__ import annotations

import json

from isaac_audio_sensors.core.acoustics.materials import known_material_ids
from isaac_audio_sensors.isaac.acoustic_scene import AcousticSceneSession
from isaac_audio_sensors.isaac.acoustic_scene.session import DYNAMIC, INCLUDE, PARTITION
from isaac_audio_sensors.isaac.acoustic_scene.steam import converted_material


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

            with Usd.EditContext(self.session.stage, self.target):
                return self.session.edit(self.paths, self.values)

        def undo(self):
            with Sdf.ChangeBlock():
                for prop, exists in self.saved.items():
                    if exists:
                        Sdf.CopySpec(self.before, prop, self.layer, prop)
                    elif self.layer.GetPropertyAtPath(prop):
                        edit = Sdf.BatchNamespaceEdit()
                        edit.Add(prop, Sdf.Path.emptyPath)
                        self.layer.Apply(edit)
            self.session.refresh()

    # Kit owns command instances on the undo stack, independently of panel refreshes.
    omni.kit.commands.register(AcousticSceneEditCommand)
    return omni.kit.commands.execute(
        "AcousticSceneEdit", session=session, paths=tuple(paths), values=dict(values)
    )


class AcousticScenePanel:
    def __init__(self, ui):
        self.ui = ui
        self.session = None
        self.closed = False
        self._subscription = None
        self._elapsed = 0.0
        self._selection_subscription = None
        self._render_signature = None

    def build(self):
        ui = self.ui
        with ui.VStack(spacing=4):
            ui.Label(
                "Prepare the open USD scene. Audio propagation is implemented in 08.2.",
                word_wrap=True,
            )
            ui.Label("Roots (blank = entire composed stage)")
            self.roots = ui.StringField().model
            with ui.HStack(height=26):
                ui.Button("Import / Update", clicked_fn=self.import_scene)
                ui.Button("Undo", clicked_fn=self.undo)
                ui.Button("Redo", clicked_fn=self.redo)
            self.status = ui.Label("Scene not prepared", word_wrap=True)
            ui.Label("Filter objects")
            self.filter = ui.StringField().model
            self.filter.add_value_changed_fn(lambda _: self._render())
            with ui.ScrollingFrame(height=150):
                self.rows = ui.Frame()
            ui.Label(
                "Edits apply to the selected USD objects "
                "(multiple selection supported)",
                word_wrap=True,
            )
            with ui.HStack(height=26):
                for label, value in (
                    ("Include", True),
                    ("Exclude", False),
                    ("Automatic", None),
                ):
                    ui.Button(label, clicked_fn=lambda v=value: self.edit({INCLUDE: v}))
            with ui.HStack(height=26):
                for value in ("auto", "static", "dynamic"):
                    ui.Button(
                        value.title(),
                        clicked_fn=lambda v=value: self.edit({DYNAMIC: v}),
                    )
            self.presets = known_material_ids()
            self.material = ui.ComboBox(0, *self.presets).model
            ui.Button("Assign material to selection", clicked_fn=self.assign_material)
            self.coefficient_fields = {}
            for label, key, default in (
                (
                    "Absorption (0-1; one value or one per frequency)",
                    "ias:absorption",
                    "0.2",
                ),
                ("Scattering (0-1)", "ias:scattering", "0.05"),
                (
                    "Transmission loss (dB; blank = inherited/default)",
                    "ias:transmission_loss_db",
                    "",
                ),
            ):
                ui.Label(label, word_wrap=True)
                field = ui.StringField().model
                field.set_value(default)
                self.coefficient_fields[key] = field
            ui.Label("Frequency centers (Hz; used for banded coefficients)")
            self.frequencies = ui.StringField().model
            self.frequencies.set_value("125 250 500 1000 2000 4000")
            ui.Button("Apply coefficients", clicked_fn=self.apply_coefficients)
            ui.Label("Structure ID")
            self.partition = ui.StringField().model
            with ui.HStack(height=26):
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
            ui.Button("Restore automatic material", clicked_fn=self.clear_material)
            with ui.CollapsableFrame(
                "Scene defaults and name associations", collapsed=True
            ):
                ui.Label("Fallback absorption material")
                self.fallback_material = ui.ComboBox(
                    self.presets.index("pra.hard_surface"), *self.presets
                ).model
                ui.Label("Fallback scattering")
                self.fallback_scattering = ui.FloatDrag(
                    min=0.0, max=1.0, step=0.01
                ).model
                self.fallback_scattering.set_value(0.05)
                ui.Label(
                    "Name associations (label = material ID, one per line)",
                    word_wrap=True,
                )
                self.associations = ui.StringField(multiline=True, height=65).model
                from isaac_audio_sensors.isaac.acoustic_scene.materials import (
                    DEFAULT_ASSOCIATIONS,
                )

                self.associations.set_value(
                    "\n".join(f"{k} = {v}" for k, v in DEFAULT_ASSOCIATIONS.items())
                )
                ui.Button("Apply scene defaults", clicked_fn=self.apply_defaults)
            ui.Label(
                "Qualified Steam library path (optional native scene verification)",
                word_wrap=True,
            )
            self.library = ui.StringField().model
            ui.Button("Verify native scene", clicked_fn=self.verify)
            with ui.CollapsableFrame(
                "Selection: material sources and Steam coefficients", collapsed=False
            ):
                self.details = ui.Label("Select an imported object", word_wrap=True)
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
        return context

    def _run(self, operation):
        try:
            operation()
            self._render()
        except Exception as exc:
            self.status.text = f"Preparation error: {exc}"

    def import_scene(self):
        def run():
            self._context()
            self.session.refresh()

        self._run(run)

    def edit(self, values):
        def run():
            context = self._context()
            paths = context.get_selection().get_selected_prim_paths()
            if not paths:
                raise ValueError("Select one or more stage objects")
            if PARTITION in values and values[PARTITION] == "":
                raise ValueError("Enter a nonempty structure ID")
            edit_with_undo(self.session, paths, values)

        self._run(run)

    def assign_material(self):
        index = self.material.get_item_value_model().get_value_as_int()
        values = self._material_overrides()
        values["ias:acoustic_material_id"] = self.presets[index]
        self.edit(values)

    def apply_coefficients(self):
        def run():
            values = {}
            frequencies = tuple(
                float(v) for v in self.frequencies.get_value_as_string().split()
            )
            for key, model in self.coefficient_fields.items():
                numbers = tuple(float(v) for v in model.get_value_as_string().split())
                values[key] = numbers[0] if len(numbers) == 1 else None
                values[key + "_bands"] = numbers if len(numbers) > 1 else None
                values[key + "_frequencies_hz"] = (
                    frequencies if len(numbers) > 1 else None
                )
            context = self._context()
            paths = context.get_selection().get_selected_prim_paths()
            if not paths:
                raise ValueError("Select objects first")
            edit_with_undo(self.session, paths, values)

        self._run(run)

    @staticmethod
    def _material_overrides():
        names = ["ias:acoustic_material_id", "ias:material"]
        for name in ("ias:absorption", "ias:scattering", "ias:transmission_loss_db"):
            names.extend((name, name + "_bands", name + "_frequencies_hz"))
        return dict.fromkeys(names)

    def clear_material(self):
        self.edit(self._material_overrides())

    def apply_defaults(self):
        def run():
            self._context()
            from isaac_audio_sensors.isaac.acoustic_scene.session import SETTINGS

            associations = dict(
                line.split("=", 1)
                for line in self.associations.get_value_as_string().splitlines()
                if line.strip()
            )
            associations = {k.strip(): v.strip() for k, v in associations.items()}
            from isaac_audio_sensors.core.acoustics.materials import resolve_material

            for value in associations.values():
                resolve_material(value)
            self.session.stage.DefinePrim(SETTINGS, "Scope")
            index = self.fallback_material.get_item_value_model().get_value_as_int()
            edit_with_undo(
                self.session,
                [SETTINGS],
                {
                    "ias:material_associations": json.dumps(associations),
                    "ias:fallback_material": self.presets[index],
                    "ias:fallback_scattering": (
                        self.fallback_scattering.get_value_as_float()
                    ),
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

        self._run(omni.kit.undo.undo)

    def redo(self):
        import omni.kit.undo

        self._run(omni.kit.undo.redo)

    def _select(self, path):
        import omni.usd

        selection = omni.usd.get_context().get_selection()
        paths = selection.get_selected_prim_paths()
        if path in paths:
            paths.remove(path)
        else:
            paths.append(path)
        selection.set_selected_prim_paths(paths, False)
        self._render()

    def _render(self):
        if not self.session or self.closed:
            return
        import omni.usd

        summary = self.session.summary()
        self.status.text = (
            f"{summary['state']} | {summary['objects']} objects | "
            f"{summary['triangles']} triangles | {summary['partitions']} structures | "
            f"{summary['dynamic']} dynamic | "
            f"{summary['fallback_materials']} material defaults\n"
            + "\n".join(summary["issues"] + summary["warnings"])
        )
        selected = omni.usd.get_context().get_selection().get_selected_prim_paths()
        query = self.filter.get_value_as_string().lower()
        with self.rows, self.ui.VStack(spacing=2):
            for path, obj in self.session.objects.items():
                if query not in path.lower():
                    continue
                self.ui.Button(
                    f"{'[x]' if path in selected else '[ ]'} {path} | "
                    f"{'dynamic' if obj.dynamic else 'static'}",
                    height=24,
                    clicked_fn=lambda p=path: self._select(p),
                )
            for path, reason in self.session.excluded.items():
                if query in path.lower():
                    self.ui.Button(
                        f"Excluded: {path} ({reason})",
                        height=24,
                        clicked_fn=lambda p=path: self._select(p),
                    )
        details = []
        for path in selected:
            obj = self.session.objects.get(path)
            if obj is None:
                continue
            details.append(
                f"{path}\nStructure: {obj.partition}; planar transmission: {obj.planar}"
            )
            for material in obj.materials:
                for family in ("absorption", "scattering", "transmission_db"):
                    curve = getattr(material, family)
                    if curve is None:
                        details.append("Transmission: opaque fallback")
                    else:
                        details.append(
                            f"{family}: {curve.values} at {curve.frequencies} Hz"
                        )
                        details.append(
                            f"Origin: {curve.origin}; evidence: {curve.evidence}"
                        )
                        if curve.citation:
                            details.append(curve.citation)
                details.append(
                    "Steam 400/2500/15000 Hz: "
                    f"{converted_material(material, obj.planar)}; "
                    "log-frequency interpolation, endpoint hold"
                )
        self.details.text = "\n".join(details) or "Select an imported object"

    def _stage_event(self, event):
        import omni.usd

        if event.type == int(omni.usd.StageEventType.CLOSING):
            if self.session:
                self.session.close()
                self.session = None
            self.status.text = "Scene not prepared"
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
                bool(self.session.provider and self.session.provider.verified),
            )
            if signature != self._render_signature:
                self._render_signature = signature
                self._render()
        except Exception as exc:
            self.status.text = f"Preparation update error: {exc}"

    def close(self):
        self.closed = True
        self._subscription = None
        self._selection_subscription = None
        if self.session:
            self.session.close()
