#!/usr/bin/env python3
import http.cookies
import json
import random
import time
from datetime import date

from ultron import core
from ultron import const

AUTHENTIFIED_USERS_FILE = "sessions.json"


# Used to handle web sessions and authentication stuff.
class Session:
    def __init__(self, pseudo, access_token, has_rights):
        self.expire_time = time.time() + const.ONE_DAY * 30
        self.pseudo = pseudo
        self.access_token = access_token
        self.has_rights = has_rights

    def create_cookie(self, _id):
        cookie = http.cookies.SimpleCookie()
        cookie["session"] = _id
        cookie["session"]["domain"] = ".ironmann.io"
        cookie["session"]["expires"] = \
            date.fromtimestamp(self.expire_time).strftime("%a, %d-%b-%Y %H:"
                                                          "%M:%S PST")
        return cookie

    def is_allowed(self):
        return self.has_rights

    def __str__(self):
        return ('{{"pseudo":"{}","expire_time":"{}","access_token":"{}",'
                '"has_rights":{}}}'
                .format(self.pseudo, self.expire_time, self.access_token,
                        'true' if self.has_rights else 'false'))


class Sessions:
    def __init__(self):
        self.sessions = {}
        self.next_update = time.time() + const.ONE_DAY
        try:
            data = ''
            with open(AUTHENTIFIED_USERS_FILE, 'r') as fdd:
                data = fdd.read()
            data = json.loads(data)
            for entry in data:
                if (entry.isdigit() and
                        'pseudo' in data[entry] and
                        'expire_time' in data[entry] and
                        'access_token' in data[entry] and
                        'has_rights' in data[entry]):
                    new_session = Session(data[entry]['pseudo'],
                                          data[entry]['access_token'],
                                          data[entry]['has_rights'])
                    try:
                        new_session.expire_time = \
                            float(data[entry]['expire_time'])
                        self.sessions[int(entry)] = new_session
                    except Exception:
                        continue
        except Exception as e:
            core.LOGS.error("Couldn't load old sessions: {}".format(e))

    def save_to_file(self):
        out = []
        for entry in self.sessions:
            out.append('"{}":{}'.format(entry, self.sessions[entry]))
        try:
            with open(AUTHENTIFIED_USERS_FILE, 'w') as fdd:
                fdd.write('{{{}}}'.format(','.join(out)))
        except Exception as e:
            core.LOGS.error("Couldn't save sessions: {}".format(e))

    def get_from_id(self, _id):
        if self.next_update <= time.time():
            self.remove_all_expired()
        session = self.sessions.get(_id, None)
        if session is None:
            return None
        if session.expire_time <= time.time():
            self.remove_id(_id)
            session = None
        return session

    def remove_id(self, _id):
        if _id in self.sessions:
            del self.sessions[_id]

    def remove_all_expired(self):
        current_time = time.time()
        ids_to_remove = [entry for entry in self.sessions
                         if self.sessions[entry].expire_time <= current_time]
        for entry in ids_to_remove:
            self.remove_id(entry)
        self.next_update = current_time + const.ONE_DAY

    def add(self, session):
        # This way of generating an unique id is quite... Bad/ugly?
        _id = random.randint(1, 1000000000)
        while _id in self.sessions:
            _id = random.randint(1, 1000000000)
        self.sessions[_id] = session
        self.save_to_file()
        return _id
