import json
import logging
import os
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Iterator
from time import sleep

from ulauncher.api.client.Extension import Extension
from ulauncher.api.client.EventListener import EventListener
from ulauncher.api.shared.event import KeywordQueryEvent, ItemEnterEvent
from ulauncher.api.shared.item.ExtensionResultItem import ExtensionResultItem
from ulauncher.api.shared.action.RenderResultListAction import RenderResultListAction
from ulauncher.api.shared.action.ExtensionCustomAction import ExtensionCustomAction
from ulauncher.api.shared.action.HideWindowAction import HideWindowAction

logger = logging.getLogger(__name__)

def fast_scandir(path: str, search_term: str, max_results: int = 5) -> Iterator[Path]:
    """Efficiently scan directory for matching subdirs, limiting results and skipping hidden dirs."""
    try:
        count = 0
        with os.scandir(path) as it:
            for entry in it:
                # Skip hidden directories and non-directories
                if entry.name.startswith('.') or not entry.is_dir():
                    continue
                
                # Check if name matches search term
                if search_term.lower() in entry.name.lower():
                    yield Path(entry.path)
                    count += 1
                    if count >= max_results:
                        break
    except PermissionError:
        # Skip directories we can't access
        pass

class DockerCommandExtension(Extension):

    def __init__(self):
        super().__init__()
        self.subscribe(KeywordQueryEvent, KeywordQueryEventListener())
        self.subscribe(ItemEnterEvent, ItemEnterEventListener())


class KeywordQueryEventListener(EventListener):

    def on_event(self, event: KeywordQueryEvent, extension: Extension) -> RenderResultListAction:
        items: List[ExtensionResultItem] = []
        query = event.get_argument() or ""
        home_dir = os.path.expanduser("~")

        # Start search from home directory
        search_path = Path(home_dir)
        if query:
            # If query contains path separators, use it as a relative path
            if "/" in query:
                base_dir = str(search_path / os.path.dirname(query))
                search_term = os.path.basename(query)
            else:
                base_dir = str(search_path)
                search_term = query

            try:
                # Get matching directories efficiently
                matching_dirs = list(fast_scandir(base_dir, search_term))

                # Add existing directories
                for dir_path in matching_dirs:  # Already limited to 5 in fast_scandir
                    rel_path = os.path.relpath(str(dir_path), home_dir)
                    data = {"path": str(dir_path), "create": False}
                    items.append(ExtensionResultItem(
                        icon="images/icon.png",
                        name=dir_path.name,
                        description=f"Use {rel_path} as workspace",
                        on_enter=ExtensionCustomAction(data, keep_app_open=False)
                    ))

                # Add option to create new directory if query is valid path and no exact match exists
                if query and not any(d.name.lower() == search_term.lower() for d in matching_dirs):
                    new_dir = Path(base_dir) / search_term
                    if not new_dir.exists():
                        data = {"path": str(new_dir), "create": True}
                        items.append(ExtensionResultItem(
                            icon="images/icon.png",
                            name=f"Create: {search_term}",
                            description=f"Create and use new directory: {os.path.relpath(str(new_dir), home_dir)}",
                            on_enter=ExtensionCustomAction(data, keep_app_open=False)
                        ))

            except Exception as e:
                logger.error(f"Error while searching directories: {e}")
                items.append(ExtensionResultItem(
                    icon="images/icon.png",
                    name="Error",
                    description=str(e),
                    on_enter=HideWindowAction()
                ))

        if not items:
            items.append(ExtensionResultItem(
                icon="images/icon.png",
                name="Start typing...",
                description="Enter directory name to search or create (hidden directories are excluded)",
                on_enter=HideWindowAction()
            ))

        return RenderResultListAction(items)


class ItemEnterEventListener(EventListener):

    def on_event(self, event: ItemEnterEvent, extension: Extension) -> HideWindowAction:
        data: Dict[str, Any] = event.get_data()
        workspace_path = data["path"]
        
        if data.get("create", False):
            try:
                os.makedirs(workspace_path, exist_ok=True)
            except Exception as e:
                logger.error(f"Failed to create directory {workspace_path}: {e}")
                return HideWindowAction()

        try:
            # Get the Docker command template from preferences
            docker_cmd = extension.preferences["docker_command"]
            
            # Replace $WORKSPACE_BASE with the selected path
            docker_cmd = docker_cmd.replace("$WORKSPACE_BASE", workspace_path)
            
            # Replace $(id -u) with actual user ID
            user_id = subprocess.check_output(["id", "-u"]).decode().strip()
            docker_cmd = docker_cmd.replace("$(id -u)", user_id)
            
            # Create the terminal command
            terminal_cmd = f"kitty -e bash -c '{docker_cmd}'"
            
            # Execute the command
            subprocess.Popen(terminal_cmd, shell=True)
            
        except Exception as e:
            logger.error(f"Failed to execute Docker command: {e}")
            
        return HideWindowAction()


if __name__ == '__main__':
    DockerCommandExtension().run()
