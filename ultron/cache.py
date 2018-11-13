import os
from pathlib import Path

from ultron import const
from ultron import core
from ultron.file_watcher import Ignorer


class CacheElement:
    def __init__(self, callback):
        self.callback = callback
        self.content = None

    def update(self, file_path):
        content = ''
        try:
            with open(file_path, 'rb') as fdd:
                content = fdd.read()
            if self.callback is not None:
                self.content = self.callback(content)
            else:
                self.content = content
            if (self.content is not None and
                    self.content.__class__.__name__ == 'str'):
                self.content = self.content.encode()
        except Exception as ex:
            core.LOGS.error('CacheElement.update failed on "{}": {}'
                            .format(ex), ex)


class Cache:
    def __init__(self):
        self.caches = {}

    def add_file(self, file_path, callback=None):
        file_path = os.path.abspath(file_path)
        if file_path in self.caches:
            return True
        path = Path(file_path)
        if not path.is_file():
            return False
        try:
            elem = CacheElement(callback)
            elem.update(file_path)
            self.caches[file_path] = elem
        except Exception as e:
            core.LOGS.error('Couldn\'t add "{}" in cache: {}'
                            .format(file_path, e), e)
            return False
        core.FILE_WATCHER.watch(file_path, self._update_cache)
        return True

    def _update_cache(self, event, file_path):
        if event == const.MODIFIED:
            core.FILE_WATCHER.add_ignorer(Ignorer(file_path, [const.MODIFIED,
                                                              const.CREATED]))
            entry = self.caches.get(file_path, None)
            if entry is None:
                return
            entry.update(file_path)

    def get(self, file_path):
        file_path = os.path.abspath(file_path)
        entry = self.caches.get(file_path, None)
        if entry is None:
            return None
        return entry.content
