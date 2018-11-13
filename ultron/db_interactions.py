import json
import sqlite3

from ultron import core


class DBInteractions:
    def __init__(self, db_name):
        self.db_name = db_name
        self.table_name = 'pendings_prs'  # just for code clarity
        fields = ('pull_request text primary key not null,'
                  'branch text not null,'
                  'ci_url text not null,'
                  'priority text not null,'
                  'env_args text not null,'
                  'sha text not null')
        db = self.connect_to_db()
        self.execute('CREATE TABLE IF NOT EXISTS {} ({})'.format(
                        self.table_name, fields), db)

    def _create_id(self, repo_name, pr_number):
        return "'{}/{}'".format(repo_name, pr_number)

    # This method creates a new Connection object. It has been created because
    # the Connection object cannot be shared between thread and the FileWatcher
    # seems to spawn new threads.
    def connect_to_db(self):
        return sqlite3.connect(self.db_name)

    def insert_pending_pr(self, repo_name, pr_number, target_branch, ci_url,
                          priority, env_args, sha):
        values = []
        _id = self._create_id(repo_name, pr_number)
        if len(_id.split('/')) != 2:
            core.LOGS.error("insert_pending_db failed: invalid id: '{}'"
                            .format(_id))
            return False
        if sha is None:
            sha = ""
        values.append(_id)
        values.append("'{}'".format(target_branch))
        values.append("'{}'".format(ci_url))
        values.append("'{}'".format(priority))
        values.append("'{}'".format(json.dumps(env_args)))
        values.append("'{}'".format(sha))
        req = ("INSERT INTO {} VALUES({})".format(
                  self.table_name, ",".join(values)))
        try:
            db = self.connect_to_db()
            self.execute(req, db)
        except Exception as e:
            core.LOGS.error('DBInteractions.insert_pending_pr error on '
                            'request "{}": {}'.format(req, e))
            return False
        return True

    def update_pending_pr(self, repo_name, pr_number, new_ci_url):
        _id = self._create_id(repo_name, pr_number)
        req = 'UPDATE {} SET ci_url="{}" WHERE pull_request="{}"'.format(
                  self.table_name, new_ci_url, _id)
        try:
            db = self.connect_to_db()
            self.execute(req, db)
        except Exception as e:
            core.LOGS.error('DBInteractions.update_pending_pr error on '
                            'request "{}": {}'.format(req, e))
            return False
        return True

    def get_pending_prs(self, repo_name):
        prs = {}
        garbages = []
        try:
            db = self.connect_to_db()
            for row in self.execute('SELECT * FROM {}'.format(
                                    self.table_name), db).fetchall():
                pr = row[0].split('/')
                if len(pr) != 2:
                    garbages.append(row[0])
                    continue
                if pr[0] == repo_name:
                    try:
                        pr_number = int(pr[1])
                        prs[pr_number] = {
                            'target_branch': row[1],
                            'ci_url': row[2],
                            'priority': row[3],
                            'env_args': row[4],
                            'sha': row[5],
                        }
                    except Exception:
                        garbages.append(row[0])
                        continue
        except Exception as e:
            core.LOGS.error('get_pending_prs failed: {}'.format(e))
        # remove all garbage prs
        for garbage in garbages:
            self._delete_entry(garbage)
        return prs

    def _delete_entry(self, _id, db):
        return self.execute("DELETE FROM {} WHERE pull_request={}".format(
                            self.table_name, _id), db).rowcount

    def delete_pending_pr(self, repo_name, pr_number):
        try:
            db = self.connect_to_db()
            if self._delete_entry(self._create_id(repo_name, pr_number),
                                  db) < 1:
                core.LOGS.info("delete_pending_pr: nothing has been "
                               "removed. Strange things happen...")
        except Exception as e:
            # It's not really a problem if a removal failed but better log it.
            core.LOGS.error("delete_pending_pr failed: {}".format(e))

    def execute(self, request, db):
        try:
            cursor = db.cursor()
            cursor.execute(request)
            db.commit()
        except sqlite3.Error as e:
            db.rollback()
            raise Exception('Error for request "{}": "{}"'.format(
                            request, e.args[0]))
        return cursor
