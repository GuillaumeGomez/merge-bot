#!/usr/bin/env python3

import http.cookies
import html
import json
import os
# pip3 install requests
import requests
import signal
import subprocess
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

try:
    from ultron import ci
    from ultron import const
    from ultron import github_event
    from ultron import core
    from ultron import my_github
    from ultron import utils
    from ultron import scheduler
    from ultron.session import Session
except Exception:
    if __name__ == '__main__':
        if os.environ.get('PYTHONPATH') != os.getcwd():
            child = subprocess.Popen(['bash', '-c',
                                      'PYTHONPATH="{}" python3 ultron/index.py'
                                      .format(os.getcwd())])
            try:
                child.communicate()
            except Exception:
                pass
            os._exit(0)
    else:
        # Do you like imports in the middle of nowhere? Because I do!
        import sys
        sys.stderr.write("We can't import modules so we leaving now.\n")
        os._exit(0)


def signal_handler(sig, frame):
    core.LOGS.info('Received Ctrl+C, exiting!')
    os._exit(0)


#
# Utilities to write a bit of HTML.
#

def create_link(url, title, classname="", style=None):
    if style is None:
        return '<a href="{}" class="{}">{}</a>'.format(url, classname, title)
    return '<a href="{}" class="{}" style="{}">{}</a>'.format(url, classname,
                                                              style, title)


def create_table_cell(content, classname='', elem='td'):
    if len(classname) > 0:
        return '<{0} class="{1}">{2}</{0}>'.format(elem, classname, content)
    return '<{0}>{1}</{0}>'.format(elem, content)


def create_table_line(elements, classname=''):
    content = '<tr>'
    if len(classname) > 0:
        content = '<tr class="{}">'.format(classname)
    for elem in elements:
        content += elem
    return content + '</tr>'


def create_select_option(element, classname=''):
    content = '<option'
    if len(classname) > 0:
        content += ' class="{}"'.format(classname)
    return '{0} value="{1}">{1}</option>'.format(content, element)


def create_button(button_label, js_function, args):
    length = 0
    content = ''
    if type(args).__name__ == 'str':
        length = len(args)
        content += ("['{}']".format(args)) if length > 0 else '[]'
    elif type(args).__name__ == 'list':
        length = len(args)
        content += (("['{}']".format("','".join([str(elem) for elem in args])))
                    if length > 0 else '[]')
    elif type(args).__name__ == 'dict':
        length = len(args.keys())
        content += (
            ("{{{}}}".format(",".join([("'{}':'{}'".format(key, value))
                                       for key, value in args.items()])))
            if length > 0 else '[]')
    else:
        return ''
    return '<button class="{}" onclick="{}({})">{}</button>'.format(
            "popup" if length > 0 else "disabled",
            js_function,
            content,
            button_label)


def is_forbidden(filepath):
    for forbidden_entry in const.FORBIDDEN_FILES:
        if filepath.endswith(forbidden_entry):
            return True
    return False


def make_pr_status(pr):
    if pr.status == const.PENDING:
        return create_link(pr.get_ci_url(), pr.status)
    return pr.status


def make_log_type_to_css_class(log_type):
    return "err_entry" if log_type == core.LOGS.ERROR else "other_entry"


def get_access(code):
    if code is None:
        core.LOGS.error('get_access failed: no code received')
        return None
    try:
        req = requests.post('https://github.com/login/oauth/access_token',
                            headers={'Content-type': 'application/json',
                                     'Accept': 'application/json'},
                            data=json.dumps(
                                     {'client_id': core.CLIENT_ID,
                                      'client_secret': core.CLIENT_SECRET,
                                      'code': code}))
        return ci.get_requests_json(req)
    except Exception as ex:
        core.LOGS.error('get_access failed: {}'.format(ex))
    return None


def get_username(token):
    try:
        r = my_github.get_all_contents('{}/user'.format(const.GH_API_URL),
                                       token=token)
    except Exception:
        return None
    return r.get('login', None)


# #
# # Web server.
# #

class RequestHandler(BaseHTTPRequestHandler):
    def get_content(self):
        content_len = int(self.headers['Content-Length'], 0)
        return utils.convert_to_string(self.rfile.read(content_len))

    # For now it's based on cookies.
    def get_session(self):
        sess = self.headers.get('Cookie', None)
        if sess is None:
            return None
        cookie = http.cookies.SimpleCookie(sess)
        session_id = cookie.get('session', None)
        if session_id is None:
            return None
        try:
            session_id = int(session_id.value)
        except Exception:
            core.LOGS.error('get_session got an invalid session id: {}'
                            .format(session_id))
            return None
        return core.SESSIONS.get_from_id(session_id)

    def send_not_found(self):
        self.send_data("<html><head><title>Unknown place</title></head>"
                       "<body><p>I think you're lost. Or maybe am I?</p>"
                       "</body></html>", response_code=404)

    def _get_file_content(self, file):
        if is_forbidden(self.path) is False:
            if os.path.isfile('html/{}'.format(file)):
                file = 'html/{}'.format(file)
            content = core.CACHE.get(file)
            if content is not None:
                return content
            try:
                with open(file, 'rb') as fdd:
                    return fdd.read()
            except Exception as e:
                core.LOGS.error("_get_file_content error: Couldn't serve GET "
                                "request: {}".format(e))
        self.send_not_found()
        return None

    def send_data(self, data, headers={"Content-type": "text/html"},
                  response_code=200, type_='text'):
        tmp = data
        if tmp.__class__.__name__ == 'str':
            tmp = tmp.encode('utf-8')
        if type_ == 'text':
            length = len(tmp.decode('utf-8'))
        else:
            length = len(tmp)
        self.send_response(response_code)
        for header in headers:
            self.send_header(header, headers[header])
        self.send_header("Content-length", "{}".format(length))
        self.end_headers()
        self.wfile.write(tmp)

    # Corresponds to IP/queue
    def get_queue(self):
        content = self._get_file_content('queue.html')
        if content is None:
            self.send_response(404)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            return

        select_options = create_select_option('')
        lines = ''
        for entry in core.QUEUES:
            select_options += create_select_option(
                entry['name'], "opt_{}".format(entry['name']))
            for pr in entry['prs']:
                lines += create_table_line(
                    [create_table_cell(
                        create_link(pr.get_url(), "#{}".format(pr.number()))),
                     create_table_cell(pr.priority),
                     create_table_cell(
                        create_link(pr.get_target_branch_url(),
                                    pr.target_branch())),
                     create_table_cell(pr.title()),
                     create_table_cell(
                        create_button('Env. args', 'display_env',
                                      pr.env_args)),
                     create_table_cell(
                        create_button('Dependencies', 'display_deps',
                                      pr.afters)),
                     create_table_cell(
                        make_pr_status(pr),
                        pr.status if pr.status != const.NOT_MERGEABLE
                        else 'not-mergeable')],
                    "line_{}".format(entry['name']))
        self.send_data(content.replace(b'[[content]]', lines.encode())
                              .replace(b'[[repositories]]',
                                       select_options.encode()))

    # Corresponds to IP/logs
    def get_logs(self):
        content = self._get_file_content('logs.html')
        if content is None:
            self.send_response(404)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            return
        c = ''
        for _id in reversed(core.LOGS.ids):
            l = core.LOGS.logs[_id]
            t = make_log_type_to_css_class(l[0])
            if len(l[2]) > 150:
                c += ('<div class="{0}" id="i{1}"><div class="read-more" '
                      'onclick="load_more(\'i{1}\');">Read '
                      'more...</div><div class="date">{2}</div>: '
                      '{3}...</div>'.format(t, _id.replace(' ', '_'), l[1],
                                            # To avoid html parsing failures,
                                            # we escape html characters.
                                            html.escape(l[2][:150])))
            else:
                c += ('<div class="{}"><div class="date">{}</div>: '
                      '{}</div>'.format(t, l[1], l[2]))
        self.send_data(content.replace(b'[[logs]]', c.encode()
                                                     .replace(b'\n', b'<br>')
                                                     .replace(b'\\n',
                                                              b'<br>')))

    # Made for AJAX requests
    #
    # Security issue: the cookie session should be sent as well.
    def get_log(self, path):
        if len(path) != 2:
            self.send_response(401)
            return
        _id = path[1].replace(',', '/').replace('_', ' ')
        log = core.LOGS.get_from_id(_id)
        if log is None:
            self.send_response(404)
            return
        c = ('<div class="read-more" onclick="show('
             '\'i{0}\');hide(\'i{0}-1\');">Read less...</div><div class='
             '"date">{1}</div>: {2}'
             # To avoid html parsing failures, we escape html characters.
             .format(_id.replace(' ', '_'), log[1],
                     html.escape(log[2])
                         .replace('\n', '<br>')
                         .replace('\\n', '<br>')))
        self.send_answer(c)

    def get_help(self):
        wrapper = self._get_file_content('help.html')
        if wrapper is None:
            self.send_response(404)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            return
        content = self._get_file_content('README.md')
        if content is None:
            self.send_response(404)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            return
        self.send_data(wrapper.replace(b'[[help]]', content))

    # If it doesn't correspond to "known" resource, we try to get corresponding
    # file.
    def try_rendering(self, filepath):
        file_extension = os.path.splitext(filepath)[1]
        if file_extension != '':
            return False
        filepath = ('{}.html'
                    .format('/'.join(list(filter(None, filepath.split('/'))))))
        if os.path.isfile('html/{}'.format(filepath)):
            filepath = 'html/{}'.format(filepath)
        if is_forbidden(filepath) is True:
            return False
        content = core.CACHE.get(filepath)
        if content is None:
            try:
                with open(filepath, 'rb') as fdd:
                    content = fdd.read()
            except Exception:
                return False
        type_ = 'text' if file_extension in ['css', 'js'] else 'image'
        self.send_data(content, type_=type_)
        return True

    # TODO: should be move into html/css files.
    def print_auth_error(self, error):
        self.send_data('<html><head><title>Authentication error</title><link '
                       'rel="stylesheet" href="https://code.cdn.mozilla.net/'
                       'fonts/fira.css"></head><body style="background-color:'
                       '#ffd2d2;font-family:\'Fira Sans\';"><h1>Authentication'
                       ' failed:</h1><h3 style="color:red;">{}</h3>'
                       '</body></html>'.format(error), response_code=403)

    # TODO: should be move into html/css files.
    def print_auth_page(self):
        self.send_data("<html><head><title>Authenticate yourself</title><link "
                       'rel="stylesheet" href="https://code.cdn.mozilla.net/'
                       'fonts/fira.css"></head><body style="font-family:\'Fira'
                       ' Sans\';background-color:#f7f7f7;"><div style="width:'
                       '100%;">{}</div></body></html>'.format(
                        create_link('https://github.com/login/oauth/authorize'
                                    '?scope=read:org&client_id={}'.format(
                                        core.CLIENT_ID),
                                    'Connect through Github',
                                    style='text-align:center;font-size:20px;'
                                          'border:1px solid;border-radius:3px;'
                                          'padding:3px;cursor:pointer;'
                                          'margin-right:auto;margin-left:auto;'
                                          'text-decoration:none;display:block;'
                                          'box-shadow: 0 0 7px 0 #656565;'
                                          'width:230px;')))

    def send_answer(self, content):
        extension = os.path.splitext(self.path)[1]
        if len(extension) < 1:
            extension = 'html'
        else:
            extension = extension[1:]
        type_ = 'text' if extension in ['css', 'js'] else 'image'
        self.send_data(content,
                       headers={'Content-type': 'text/{}'.format(extension)},
                       type_=type_)

    def authenticate(self):
        query_components = parse_qs(urlparse(self.path).query)
        code = query_components.get('code', None)
        if code is None or len(code) < 1:
            self.print_auth_error('No code received...')
            return
        # We get code argument sent by github
        access_token = get_access(code[0])
        if access_token is None:
            self.print_auth_error('Cannot get access token.')
            return
        if 'error_description' in access_token:
            self.print_auth_error('{}: {}'.format(
                access_token['error_description'], code[0]))
            return
        access_token = access_token.get('access_token', None)
        if access_token is None:
            self.print_auth_error('No access token received? Weird!')
            return

        login = get_username(access_token)
        if login is None:
            self.print_auth_error('Cannot get username.')
            return
        orgas = my_github.User(access_token, login).get_organizations()
        is_allowed = False
        for orga in orgas:
            if orga.name == core.ORGANIZATION:
                is_allowed = True
                break
        sess = Session(login, access_token, is_allowed)
        _id = core.SESSIONS.add(sess)
        self.send_response(302)
        self.send_header('Content-type', 'text/plain')
        out = sess.create_cookie(_id).output().split(': ')
        self.send_header(out[0], ''.join(out[1:]))
        self.send_header('Location', '/')
        self.end_headers()

    def check_session(self):
        session = self.get_session()
        if session is None:
            self.print_auth_page()
        elif session.is_allowed() is False:
            self.print_auth_error('You\'re not part of "{}".'
                                  .format(core.ORGANIZATION))
        else:
            return session
        return None

    def do_GET(self):
        path = self.path.split('?')[0]
        if len(path) == 0 or path == "/":
            if self.check_session() is not None:
                self.send_response(302)
                self.send_header('Location', '/queue')
                self.end_headers()
            return
        path = list(filter(None, path.split('/')))
        if len(path) > 0:
            if path[0] == 'gh-app':
                self.authenticate()
                return
            # In case we get a favicon request, we don't check the session.
            if path[0] != 'favicon.ico' and path[0] != 'log':
                session = self.check_session()
                if session is None:
                    return
                if path[0] == 'queue':
                    self.get_queue()
                    return
                elif path[0] == 'logs':
                    self.get_logs()
                    return
                elif path[0] == 'help':
                    self.get_help()
                    return
            if path[0] == 'log':
                self.get_log(path)
                return
            if self.try_rendering(self.path):
                return
            if '..' not in self.path:
                content = self._get_file_content("./{}".format(self.path))
                if content is None:
                    return
                self.send_answer(content)
                return
        self.send_not_found()

    def do_POST(self):
        try:
            data = json.loads(self.get_content())
            # Let's make path check case insensitive!
            path = self.path.lower()
            if path.endswith("github"):
                if 'zen' in data and 'hook_id' in data and 'hook' in data:
                    # github ping
                    pass
                else:
                    github_event.handle_event(data)
            elif path.endswith("circleci"):
                # circleCI event
                ci.handle_ci_response(data)
                core.COMMENT_QUEUE.flush()
            else:
                # The next line needs to be removed! We keep it for now for
                # compatibility.
                github_event.handle_event(data)
                core.LOGS.error('Unknown POST request received (should be '
                                '/[service]): {}'
                                .format(data))
                # Once updated, we should return 404 in here and uncomment the
                # next line.
                # return
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
        except Exception as ex:
            core.LOGS.error('do_POST failed: {}'.format(ex), ex)

    # The only thing we do when we receive a PUT request is using our
    # scheduler.
    def do_PUT(self):
        path = list(filter(None, self.path.split('/')))
        if len(path) == 0:
            pass
        elif path[0] == const.SCHEDULER_PATH:
            try:
                scheduler.sched_callback()
            except Exception as e:
                core.LOGS.error('do_PUT failed: {}'.format(e), e)
        elif path[0] == const.FILE_WATCHER_PATH:
            try:
                data = json.loads(self.get_content())
                if 'id' not in data:
                    core.LOGS.error('do_PUT failed on {}: missing "id" field'
                                    .format(const.FILE_WATCHER_PATH))
                else:
                    core.FILE_WATCHER.call_pending(data['id'])
            except Exception as e:
                core.LOGS.error('do_PUT failed on {}: {}'
                                .format(const.FILE_WATCHER_PATH, e), e)
        else:
            core.LOGS.error('do_PUT: invalid request: {}'.format(self.path))
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()


def start():
    core.init()

    httpd = HTTPServer(("", core.PORT), RequestHandler)
    signal.signal(signal.SIGINT, signal_handler)
    core.LOGS.info('Seems all good. Listening on port {}\n'
                   'If you want to quit, just press CTRL+C'.format(core.PORT))
    httpd.serve_forever()


if __name__ == '__main__':
    start()
