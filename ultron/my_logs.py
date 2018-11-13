import datetime
import sys
import traceback

from ultron import const


def _get_current_time():
    return datetime.datetime.now().strftime('%H:%M:%S %d/%m/%y')


class Logs:
    def __init__(self):
        self.logs = {}
        self.ERROR = 0
        self.OTHER = 1
        self.current_id = 0
        self.ids = []

    def _append(self, kind, msg):
        current_time = _get_current_time()
        new_id = '{}-{}'.format(current_time, self.current_id)
        self.logs[new_id] = [kind, current_time, msg]
        self.ids.append(new_id)
        self.current_id += 1
        if self.current_id >= const.MAX_LOGS:
            self.current_id = 0
        if len(self.ids) > const.MAX_LOGS:
            _id = self.ids.pop(0)
            del self.logs[_id]

    def error(self, msg, exception=None):
        if exception is not None:
            msg += '\n{}'.format(
                ''.join(traceback.format_tb(exception.__traceback__)))
        self._append(self.ERROR, msg)
        sys.stderr.write('{}\n'.format(msg.encode('utf-8')))

    def info(self, msg):
        self._append(self.OTHER, msg)
        sys.stdout.write('{}\n'.format(msg.encode('utf-8')))

    # can be useful if we add a button to clear logs
    def clear(self):
        self.logs = []
        self.start_id = 0

    def get_from_id(self, _id):
        return self.logs.get(_id, None)
