# pip3 install requests
import requests
import sched
import time
from threading import Thread

from ultron import const
from ultron import core


scheduler = sched.scheduler(time.time, time.sleep)


def try_update_pendings():
    for queue in core.QUEUES:
        queue['prs'].update_next_to_pending()


def sched_callback():
    ret = core.SCHEDULER.get_next()
    if ret is not None:
        callback = ret.callback
        core.SCHEDULER.remove_current()
        callback()
        core.SCHEDULER.run_task()


def send_message():
    try:
        requests.put('http://127.0.0.1:{}/{}'.format(core.PORT,
                                                     const.SCHEDULER_PATH))
    except Exception as e:
        core.LOGS.error('scheduler::send_message failed: {}'.format(e), e)


class SchedulerHandler:
    def __init__(self, owner):
        self.owner = owner

    def run(self):
        scheduler.run()
        # Thanks to GIL, no data racing! :D
        self.owner.current_task = None


# Represents the schedule information.
class ScheduleInfo:
    def __init__(self, callback):
        self.callback = callback

    def __eq__(self, other):
        return self.callback == other.callback


# This class is used when an after dependency is set on a PR from another
# repository.
#
# Once an event has been set, the timer is started into a Thread.
# When the event is fired, we're still in the Thread and in order to make
# everything work synchronously, we need to get out of it. So in order to
# achieve this, we send an http event to our server which will then call
# the function sched_callback (which then handles the callback and stuff).
class Scheduler:
    def __init__(self):
        self.tasks = []
        self.current_task = None
        # This just allows to have only one event queued at a time.
        self.next_schedule = False
        self.start = time.time()

    def add(self, schedule_info):
        if len([task for task in self.tasks
                if task == schedule_info]) == 0:
            self.tasks.append(schedule_info)
            if self.next_schedule is False:
                self.run_task()

    def remove_current(self):
        if len(self.tasks) > 0:
            del self.tasks[0]
        self.next_schedule = False

    def run_task(self):
        if len(self.tasks) > 0 and self.next_schedule is False:
            if self.current_task is None:
                self.start = time.time()
            scheduler.enter(const.SCHEDULE_DELAY + (time.time() - self.start),
                            1, send_message, ())
            self.next_schedule = True
            if self.current_task is None:
                self.current_task = Thread(target=SchedulerHandler(self).run)
                self.current_task.start()

    def get_next(self):
        if len(self.tasks) > 0:
            return self.tasks[0]
        return None

    def remove(self, schedule):
        for pos, task in enumerate(self.tasks):
            if task == schedule:
                del self.tasks[pos]
                return
