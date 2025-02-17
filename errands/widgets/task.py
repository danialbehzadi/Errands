# Copyright 2023 Vlad Krupinskii <mrvladus@yandex.ru>
# SPDX-License-Identifier: MIT

from __future__ import annotations
from re import T
from typing import Any, Self, TYPE_CHECKING

if TYPE_CHECKING:
    from errands.widgets.task_list import TaskList
    from errands.widgets.window import Window

from errands.widgets.components import Box
from gi.repository import Gtk, Adw, Gdk, GObject
from errands.lib.sync.sync import Sync
from errands.lib.logging import Log
from errands.utils.data import UserData
from errands.utils.markup import Markup
from errands.utils.functions import get_children
from errands.lib.gsettings import GSettings


class TaskTopDropArea(Gtk.Revealer):
    def __init__(self, task: Task):
        super().__init__()
        self.task: Task = task
        self._build_ui()

    def _build_ui(self):
        self.set_transition_type(5)

        # Drop Image
        top_drop_img: Gtk.Image = Gtk.Image(
            icon_name="list-add-symbolic",
            hexpand=True,
            css_classes=["dim-label", "task-drop-area"],
        )
        top_drop_img_target: Gtk.DropTarget = Gtk.DropTarget.new(
            actions=Gdk.DragAction.MOVE, type=Task
        )
        top_drop_img_target.connect("drop", self._on_drop)
        top_drop_img.add_controller(top_drop_img_target)
        self.set_child(top_drop_img)

        # Drop controller
        drop_ctrl: Gtk.DropControllerMotion = Gtk.DropControllerMotion.new()
        drop_ctrl.bind_property(
            "contains-pointer", self, "reveal-child", GObject.BindingFlags.SYNC_CREATE
        )
        self.task.add_controller(drop_ctrl)

    def _on_drop(self, _drop, task: Task, _x, _y) -> bool:
        """
        When task is dropped on "+" area on top of task
        """

        # Return if task is itself
        if task == self.task:
            return False

        # Move data
        UserData.run_sql("CREATE TABLE tmp AS SELECT * FROM tasks WHERE 0")
        ids: list[str] = UserData.get_tasks()
        ids.insert(ids.index(self.task.uid), ids.pop(ids.index(task.uid)))
        for id in ids:
            UserData.run_sql(f"INSERT INTO tmp SELECT * FROM tasks WHERE uid = '{id}'")
        UserData.run_sql("DROP TABLE tasks", "ALTER TABLE tmp RENAME TO tasks")
        # If task has the same parent
        if task.parent == self.task.parent:
            # Move widget
            self.task.parent.tasks_list.reorder_child_after(task, self.task)
            self.task.parent.tasks_list.reorder_child_after(self.task, task)
            return True
        # Change parent if different parents
        task.update_props(["parent", "synced"], [self.task.get_prop("parent"), False])
        task.purge()
        # Add new task widget
        new_task: Task = Task(
            task.uid,
            self.task.list_uid,
            self.task.window,
            self.task.task_list,
            self.task.parent,
            self.task.get_prop("parent") != None,
        )
        self.task.parent.tasks_list.append(new_task)
        self.task.parent.tasks_list.reorder_child_after(new_task, self.task)
        self.task.parent.tasks_list.reorder_child_after(self.task, new_task)
        new_task.toggle_visibility(True)
        self.task.details.update_info(new_task)
        # Update status
        self.task.parent.update_status()
        task.parent.update_status()
        # Sync
        Sync.sync()

        return True


class TaskTitleRow(Gtk.Overlay):
    def __init__(self, task: Task):
        super().__init__()
        self.task: Task = task
        self._build_ui()

    def add_rm_crossline(self, add: bool) -> None:
        if add:
            self.task_row.add_css_class("task-completed")
        else:
            self.task_row.remove_css_class("task-completed")

    def _build_ui(self):
        # Task Title Row
        self.task_row = Adw.ActionRow(
            title=Markup.find_url(Markup.escape(self.task.get_prop("text"))),
            css_classes=["rounded-corners", "transparent"],
            height_request=60,
            accessible_role=Gtk.AccessibleRole.ROW,
            cursor=Gdk.Cursor.new_from_name("pointer"),
            use_markup=True,
        )
        self.add_rm_crossline(self.task.get_prop("completed"))

        # Drag controller
        task_row_drag_source: Gtk.DragSource = Gtk.DragSource.new()
        task_row_drag_source.set_actions(Gdk.DragAction.MOVE)
        task_row_drag_source.connect("prepare", self._on_drag_prepare)
        task_row_drag_source.connect("drag-begin", self._on_drag_begin)
        task_row_drag_source.connect("drag-cancel", self._on_drag_end)
        task_row_drag_source.connect("drag-end", self._on_drag_end)
        self.task_row.add_controller(task_row_drag_source)

        # Drop controller
        task_row_drop_target = Gtk.DropTarget.new(
            actions=Gdk.DragAction.MOVE, type=Task
        )
        task_row_drop_target.connect("drop", self._on_drop)
        self.task_row.add_controller(task_row_drop_target)

        # Click controller
        task_row_click_ctrl = Gtk.GestureClick.new()
        task_row_click_ctrl.connect("released", self._on_row_clicked)
        self.task_row.add_controller(task_row_click_ctrl)

        # Prefix
        self.complete_btn = TaskCompleteButton(self.task, self.task_row)
        self.task_row.add_prefix(self.complete_btn)

        # Suffix
        self.details_btn = TaskDetailsButton(self.task)
        self.expand_btn = TaskExpandButton(self.task)
        self.task_row.add_suffix(Box(children=[self.expand_btn, self.details_btn]))

        self.expand_indicator = Gtk.Image(
            icon_name="errands-up-symbolic",
            css_classes=["expand-indicator"],
            halign=Gtk.Align.END,
            margin_end=23,
            margin_top=45,
        )
        expand_indicator_rev = Gtk.Revealer(
            child=self.expand_indicator,
            transition_type=1,
            reveal_child=False,
            can_target=False,
        )
        GSettings.bind("primary-action-show-sub-tasks", expand_indicator_rev, "visible")
        self.add_overlay(expand_indicator_rev)

        # Expand indicator hover controller
        hover_ctrl = Gtk.EventControllerMotion()
        hover_ctrl.bind_property(
            "contains-pointer",
            expand_indicator_rev,
            "reveal-child",
            GObject.BindingFlags.SYNC_CREATE,
        )
        self.task_row.add_controller(hover_ctrl)

        box = Gtk.ListBox(
            selection_mode=Gtk.SelectionMode.NONE,
            css_classes=["rounded-corners", "transparent"],
            accessible_role=Gtk.AccessibleRole.PRESENTATION,
        )
        box.append(self.task_row)

        self.set_child(box)

    def _on_row_clicked(self, *args) -> None:
        # Show sub-tasks if this is primary action
        if GSettings.get("primary-action-show-sub-tasks"):
            self.task.expand(not self.task.sub_tasks_revealer.get_child_revealed())
        else:
            self.task.task_row.details_btn.do_clicked()

    def _on_drag_prepare(self, *_) -> Gdk.ContentProvider:
        # Bug workaround when task is not sensitive after short dnd
        for task in self.task.task_list.get_all_tasks():
            task.set_sensitive(True)
        self.task.set_sensitive(False)
        value: GObject.Value = GObject.Value(Task)
        value.set_object(self.task)
        return Gdk.ContentProvider.new_for_value(value)

    def _on_drag_begin(self, _, drag) -> bool:
        text: str = self.task.get_prop("text")
        icon: Gtk.DragIcon = Gtk.DragIcon.get_for_drag(drag)
        icon.set_child(Gtk.Button(label=text if len(text) < 20 else f"{text[0:20]}..."))

    def _on_drag_end(self, *_) -> bool:
        self.task.set_sensitive(True)
        # KDE dnd bug workaround for issue #111
        for task in self.task.task_list.get_all_tasks():
            task.top_drop_area.set_reveal_child(False)
            task.set_sensitive(True)

    def _on_drop(self, _drop, task: Task, _x, _y) -> None:
        """
        When task is dropped on task and becomes sub-task
        """

        if task == self.task or task.parent == self.task:
            return

        # Change parent
        task.update_props(["parent", "synced"], [self.task.get_prop("uid"), False])
        # Move data
        uids: list[str] = UserData.get_tasks()
        last_sub_uid: str = UserData.get_tasks_uids(self.task.list_uid, self.task.uid)[
            -1
        ]
        uids.insert(
            uids.index(self.task.uid) + uids.index(last_sub_uid),
            uids.pop(uids.index(task.uid)),
        )
        UserData.run_sql("CREATE TABLE tmp AS SELECT * FROM tasks WHERE 0")
        for id in uids:
            UserData.run_sql(f"INSERT INTO tmp SELECT * FROM tasks WHERE uid = '{id}'")
        UserData.run_sql("DROP TABLE tasks", "ALTER TABLE tmp RENAME TO tasks")
        # Remove old task
        task.purge()
        # Add new sub-task
        new_task: Task = self.task.tasks_list.add_sub_task(task.uid)
        self.task.details.update_info(new_task)
        self.task.update_props(["completed"], [False])
        self.just_added = True
        self.task.task_row.complete_btn.set_active(False)
        self.task.just_added = False
        # Update status
        task.parent.update_status()
        self.task.update_status()
        self.task.parent.update_status()
        # Sync
        Sync.sync()

        return True


class TaskCompleteButton(Gtk.Box):
    def __init__(self, task: Task, parent: Adw.ActionRow) -> None:
        super().__init__()
        self.task: Task = task
        self.parent: Adw.ActionRow = parent
        self._build_ui()

    def get_active(self) -> bool:
        return self.big_btn.get_active()

    def set_active(self, active: bool) -> None:
        self.big_btn.set_active(active)

    def _build_ui(self) -> None:
        # Big button
        self.big_btn = Gtk.CheckButton(
            valign=Gtk.Align.CENTER,
            tooltip_text=_("Mark as Completed"),
            active=self.task.get_prop("completed"),
            css_classes=["selection-mode"],
        )
        GSettings.bind("task-big-toggle", self.big_btn, "visible")
        self.big_btn.connect("toggled", self._on_toggle)
        self.append(self.big_btn)

        # Small button
        small_btn = Gtk.CheckButton(
            valign=Gtk.Align.CENTER,
            tooltip_text=_("Mark as Completed"),
            active=self.task.get_prop("completed"),
        )
        small_btn.bind_property(
            "active",
            self.big_btn,
            "active",
            GObject.BindingFlags.SYNC_CREATE | GObject.BindingFlags.BIDIRECTIONAL,
        )
        GSettings.bind("task-big-toggle", small_btn, "visible", True)
        self.append(small_btn)

    def _on_toggle(self, btn: Gtk.CheckButton) -> None:
        Log.debug(f"Task '{self.task.uid}': Set completed to '{self.get_active()}'")

        # If task is just added set crossline and return to avoid sync loop
        self.task.task_row.add_rm_crossline(self.get_active())
        if self.task.just_added:
            return

        self.task.update_props(["completed", "synced"], [self.get_active(), False])
        sub_tasks: list[Task] = self.task.tasks_list.get_all_sub_tasks()
        parents: list[Task] = self.task.get_parents_tree()

        if self.get_active():
            # Complete all sub-tasks
            for sub in sub_tasks:
                sub.just_added = True
                sub.task_row.complete_btn.set_active(True)
                sub.task_row.add_rm_crossline(True)
                sub.just_added = False
                sub.update_props(["completed", "synced"], [True, False])
        else:
            # Uncomplete parent if sub-task is uncompleted
            for parent in parents:
                parent.just_added = True
                parent.task_row.complete_btn.set_active(False)
                parent.task_row.add_rm_crossline(False)
                parent.just_added = False
                parent.update_props(["completed", "synced"], [False, False])

        # Calculate completion percent for parents
        for parent in parents:
            total, completed = parent.get_status()
            pc: int = (
                completed / total * 100
                if total > 0
                else parent.get_prop("percent_complete")
            )
            parent.update_props(["percent_complete", "synced"], [pc, False])
            parent.update_status()

        # Calculate completion percent for self
        total, completed = self.task.get_status()
        pc: int = (
            completed / total * 100
            if total > 0
            else (100 if self.task.get_prop("completed") else 0)
        )
        self.task.update_props(["percent_complete", "synced"], [pc, False])

        # Calculate completion percent for sub-tasks
        for sub in sub_tasks:
            total, completed = sub.get_status()
            pc: int = (
                completed / total * 100
                if total > 0
                else (100 if self.task.get_prop("completed") else 0)
            )
            sub.update_props(["percent_complete", "synced"], [pc, False])

        self.task.details.update_info(self.task.details.parent)
        self.task.parent.update_status()
        self.task.update_status()
        Sync.sync()


class TaskExpandButton(Gtk.Button):
    def __init__(self, task: Task):
        super().__init__()
        self.task: Task = task
        self._build_ui()

    def _build_ui(self):
        self.set_icon_name("errands-up-symbolic")
        self.set_valign(Gtk.Align.CENTER)
        self.set_tooltip_text(_("Expand / Fold"))
        self.add_css_class("flat")
        self.add_css_class("circular")
        self.add_css_class("fade")
        self.add_css_class("rotate")
        GSettings.bind("primary-action-show-sub-tasks", self, "visible", True)

    def do_clicked(self):
        self.task.expand(not self.task.sub_tasks_revealer.get_child_revealed())


class TaskDetailsButton(Gtk.Button):
    def __init__(self, task: Task):
        super().__init__()
        self.task: Task = task
        self._build_ui()

    def _build_ui(self):
        self.set_icon_name("errands-info-symbolic")
        self.set_valign(Gtk.Align.CENTER)
        self.set_tooltip_text(_("Details"))
        self.add_css_class("flat")
        self.add_css_class("circular")
        GSettings.bind("primary-action-show-sub-tasks", self, "visible")

    def do_clicked(self):
        # Close details on second click
        if (
            self.task.details.parent == self.task
            and not self.task.details.status.get_visible()
            and self.task.task_list.split_view.get_show_sidebar()
        ):
            self.task.task_list.split_view.set_show_sidebar(False)
            return
        # Update details and show sidebar
        self.task.details.update_info(self.task)
        self.task.task_list.split_view.set_show_sidebar(True)


class TaskStatusBar(Gtk.Box):
    def __init__(self, task: Task):
        super().__init__()
        self.task: Task = task
        self._build_ui()

    def _build_ui(self):
        pass


class TaskSubTasksEntry(Gtk.Entry):
    def __init__(self, task: Task):
        super().__init__()
        self.task: Task = task
        self._build_ui()

    def _build_ui(self):
        self.set_hexpand(True)
        self.set_placeholder_text(_("Add new Sub-Task"))
        self.set_margin_start(12)
        self.set_margin_end(12)
        self.set_margin_bottom(6)

    def do_activate(self) -> None:
        """
        Add new Sub-Task
        """
        text: str = self.get_text()

        # Return if entry is empty
        if text.strip(" \n\t") == "":
            return

        # Add sub-task
        self.task.tasks_list.add_sub_task(
            UserData.add_task(
                list_uid=self.task.list_uid, text=text, parent=self.task.uid
            )
        )

        # Clear entry
        self.set_text("")

        # Update status
        self.task.update_props(["completed"], [False])
        self.task.just_added = True
        self.task.task_row.complete_btn.set_active(False)
        self.task.just_added = False
        self.task.update_status()

        # Sync
        Sync.sync()


class TaskSubTasks(Gtk.Box):
    def __init__(self, task: Task):
        super().__init__()
        self.task: Task = task
        self._build_ui()
        self._add_sub_tasks()

    def _build_ui(self):
        self.set_orientation(Gtk.Orientation.VERTICAL)
        self.add_css_class("sub-tasks")

    def _add_sub_tasks(self) -> None:
        subs: list[str] = UserData.get_tasks_uids(self.task.list_uid, self.task.uid)
        if len(subs) == 0:
            self.task.just_added = False
            return
        for uid in subs:
            self.add_sub_task(uid)
        self.task.parent.update_status()
        self.task.task_list.update_status()
        self.task.just_added = False

    def add_sub_task(self, uid: str) -> Task:
        new_task: Task = Task(
            uid,
            self.task.list_uid,
            self.task.window,
            self.task.task_list,
            self.task,
            True,
        )
        self.append(new_task)
        new_task.toggle_visibility(not new_task.get_prop("trash"))
        return new_task

    def get_sub_tasks(self) -> list[Task]:
        return get_children(self)

    def get_all_sub_tasks(self) -> list[Task]:
        """
        Get list of all tasks widgets including sub-tasks
        """

        tasks: list[Task] = []

        def append_tasks(sub_tasks: list[Task]) -> None:
            for task in sub_tasks:
                tasks.append(task)
                children: list[Task] = task.tasks_list.get_sub_tasks()
                if len(children) > 0:
                    append_tasks(children)

        append_tasks(self.get_sub_tasks())
        return tasks


class Task(Gtk.Revealer):
    just_added: bool = True
    can_sync: bool = True

    def __init__(
        self,
        uid: str,
        list_uid: str,
        window: Window,
        task_list: TaskList,
        parent: TaskList | Task,
        is_sub_task: bool,
    ) -> None:
        super().__init__()
        Log.info(f"Add task: {uid}")

        self.uid = uid
        self.list_uid = list_uid
        self.window = window
        self.task_list = task_list
        self.parent = parent
        self.is_sub_task = is_sub_task
        self.trash = window.trash
        self.details = task_list.details

        self._build_ui()
        # Add to trash if needed
        if self.get_prop("trash"):
            self.trash.trash_add(self)
        # Expand
        self.expand(self.get_prop("expanded"))
        self.update_status()

    def _build_ui(self) -> None:
        # Top drop area
        self.top_drop_area = TaskTopDropArea(self)

        # Task row
        self.task_row = TaskTitleRow(self)

        # Sub-tasks
        self.tasks_list = TaskSubTasks(self)

        # Sub-tasks revealer
        self.sub_tasks_revealer = Gtk.Revealer(
            child=Box(
                children=[TaskSubTasksEntry(self), self.tasks_list],
                orientation="vertical",
            )
        )

        # Task card
        self.main_box = Box(
            children=[self.task_row, self.sub_tasks_revealer],
            orientation="vertical",
            hexpand=True,
            css_classes=["fade", "card", f'task-{self.get_prop("color")}'],
        )

        self.set_child(
            Box(
                children=[self.top_drop_area, self.main_box],
                orientation="vertical",
                margin_start=12,
                margin_end=12,
                margin_bottom=6,
                margin_top=6,
            )
        )

    def get_parents_tree(self) -> list[Task]:
        """Get parent tasks chain"""

        parents: list[Task] = []

        def _add(task: Task):
            if isinstance(task.parent, Task):
                parents.append(task.parent)
                _add(task.parent)

        _add(self)

        return parents

    def get_prop(self, prop: str) -> Any:
        res: Any = UserData.get_prop(self.list_uid, self.uid, prop)
        if prop in "deleted completed expanded trash":
            res = bool(res)
        return res

    def get_status(self) -> tuple[int, int]:
        """Get total tasks and completed tasks tuple"""

        total: int = UserData.run_sql(
            f"""SELECT COUNT(*) FROM tasks
            WHERE list_uid = '{self.list_uid}'
            AND parent = '{self.uid}'
            AND trash = 0
            AND deleted = 0""",
            fetch=True,
        )[0][0]
        completed: int = UserData.run_sql(
            f"""SELECT COUNT(*) FROM tasks
            WHERE list_uid = '{self.list_uid}'
            AND parent = '{self.uid}'
            AND trash = 0
            AND deleted = 0
            AND completed = 1""",
            fetch=True,
        )[0][0]

        return total, completed

    def delete(self, *_) -> None:
        """Move task to trash"""

        Log.info(f"Task: Move to trash: '{self.uid}'")

        self.toggle_visibility(False)
        self.update_props(["trash"], [True])
        self.task_row.complete_btn.set_active(True)
        self.trash.trash_add(self)
        for task in self.tasks_list.get_sub_tasks():
            if not task.get_prop("trash"):
                task.delete()
        self.parent.update_status()

    def expand(self, expanded: bool) -> None:
        self.sub_tasks_revealer.set_reveal_child(expanded)
        self.update_props(["expanded"], [expanded])
        if expanded:
            self.task_row.expand_btn.remove_css_class("rotate")
            self.task_row.expand_indicator.remove_css_class("expand-indicator-expanded")
        else:
            self.task_row.expand_btn.add_css_class("rotate")
            self.task_row.expand_indicator.add_css_class("expand-indicator-expanded")

    def purge(self) -> None:
        """Completely remove widget"""

        self.parent.tasks_list.remove(self)
        self.run_dispose()

    def toggle_visibility(self, on: bool) -> None:
        self.set_reveal_child(on)

    def update_props(self, props: list[str], values: list[Any]) -> None:
        UserData.update_props(self.list_uid, self.uid, props, values)

    def update_status(self) -> None:
        total, completed = self.get_status()
        self.task_row.task_row.set_subtitle(
            _("Completed:") + f" {completed} / {total}" if total > 0 else ""
        )
