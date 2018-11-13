from ultron import ci
from ultron import const
from ultron import core
from ultron import queue_mod
from ultron import utils
from ultron.parse_status import ParseStatus


def arguments_inspector(func):
    def wrapper(*args, **kwargs):
        # Since this is a function with a given number of positional arguments,
        # it might be a problem if too much arguments were given.
        args = args[:func.__code__.co_argcount]
        return func(*args, **kwargs)
    return wrapper


@arguments_inspector
def _parse_priority(parts, pull, queue):
    command = '{}={}'.format(parts[0], parts[1])
    ret = ""
    if len(parts[1]) == 0:
        parts[1] = '0'
    if parts[1].lower() == const.ROLLUP:
        return ParseStatus(queue.update_priority(pull, const.ROLLUP),
                           command=command)
    try:
        priority = int(parts[1])
        if priority < 0:
            return ParseStatus(False,
                               command=command,
                               message="Priority cannot be less than 0.")
        return ParseStatus(queue.update_priority(pull, priority),
                           command=command)
    except Exception:
        return ParseStatus(False,
                           command=command,
                           message="Invalid priority value")
    return ParseStatus(ret, command=command)


def all_url_check(pull, url_to_check):
    if len(url_to_check) != 0:
        url = url_to_check
        try:
            url = utils.transform_github_url(url, pull.get_url())
            if url is None:
                return (False, url_to_check,
                        'Invalid PR url: "{}"'.format(url_to_check))
            utils.check_github_url(url)
        except Exception as e:
            return (False, url_to_check, '"{}": {}'.format(url, e))
        return (True, url, '')
    return (True, '', '')


@arguments_inspector
def _parse_after(parts, pull, queue, last_r):
    if '[' in parts[1]:
        # The "[...]" arguments have already been concatenated into a
        # string, no "white characters" (such as whitespace, tabulation or
        # backlines) is remaining.
        pull.afters = []
        l = list(filter(None, parts[1][1:-1].split(',')))
        if last_r is not None:
            # no need to check, we just want the last array
            last_r['prs_to_check'] = l
            return ParseStatus(True, command=parts[0])
        return queue_mod.check_after_urls(l, pull)
    command = '{}={}'.format(parts[0], parts[1])
    status, url, message = all_url_check(pull, parts[1])
    if status is False:
        return ParseStatus(False, command=command, message=message)
    if len(url) > 0:
        if last_r is not None:
            # no need to check, we just want the last array
            last_r['prs_to_check'] = [url]
            return ParseStatus(True, command=command)
        pull.afters = [url]
    else:
        if last_r is not None:
            # no need to check, we just want the last array
            last_r['prs_to_check'] = []
        pull.afters = []
    return ParseStatus(True, command=command)


@arguments_inspector
def _parse_needed_review(parts):
    # if len(parts[1]) < 1:
    #     parts[1] = '0'
    # try:
    #     return queue.update_needed_review(pull, int(parts[1]))
    # except Exception:
    #     pass
    # TODO: https://developer.github.com/v3/activity/events/types/
    #       #pullrequestreviewevent
    return ParseStatus(False,
                       command=parts[0],
                       message="Github API doesn't allow this for "
                               "the moment... :sob:")


@arguments_inspector
def _parse_env_var(parts, pull):
    # TODO: upper it and then save it as env variable
    # after (branch) == ORGA_{PROJ}_BRANCH (is a branch) -> ok
    # after (branch) != ORGA_{PROJ}_BRANCH (branch) -> not ok
    #
    # if len(parts[1]) == 0 -> unset var
    if len(parts[0]) < 1:
        return ParseStatus(False,
                           command=parts[0],
                           message="An environment variable name cannot be "
                                   "empty!")
    if len(parts[1]) < 1:
        if parts[0] in pull.env_args:
            del pull.env_args[parts[0]]
    else:
        pull.env_args[parts[0]] = parts[1]
    return ParseStatus(True, command="{}={}".format(parts[0], parts[1]))


def _pre_parse_review_hash(command, parts, pull, queue, last_r):
    if utils.is_valid_hash(parts[1]) is False:
        return ParseStatus(False,
                           command=command,
                           message='"{}" is an invalid hash.'.format(parts[1]))
    if last_r is not None:
        last_r['last'] = parts[1]
        return ParseStatus(True, command=command)
    if pull.status == const.PENDING:
        return ParseStatus(False,
                           command=command,
                           message='The PR is already being tested at '
                                   '"{}".'.format(pull.ci_url))
    if len(parts[1]) == 0:
        if pull.status != const.APPROVED:
            return r_plus_command(pull, queue, None, "", [])
        old_sha = pull.sha
        pull.sha = None
        return ParseStatus(True,
                           command=command,
                           message='SHA "{}" has been removed, PR is still '
                                   '__approved__.'.format(old_sha))
    return ParseStatus(True, command=command)


@arguments_inspector
def _parse_r_equal(parts, pull, queue, last_r):
    command = "{}={}".format(parts[0], parts[1])
    ret = _pre_parse_review_hash(command, parts, pull, queue, last_r)
    if ret is not None and ret.is_full_success() is False:
        return ret
    try:
        commits = core.GITHUB.get_commits_from_pull(pull.repo_name(),
                                                    pull.repo_owner(),
                                                    pull.number())
        for commit in commits:
            if commit.sha.startswith(parts[1]):
                if pull.sha is not None and pull.sha.startswith(parts[1]):
                    return ParseStatus(False,
                                       command=command,
                                       message='The PR is already approved '
                                               'with this SHA.')
                pull.sha = commit.sha
                if pull.status != const.APPROVED:
                    return ParseStatus(queue.update_status(pull,
                                                           const.APPROVED),
                                       command=command)
                return ParseStatus(True, command=command)
        return ParseStatus(False,
                           command=command,
                           message='No commit corresponds to this SHA: '
                                   '"{}".'.format(parts[1]))
    except Exception as e:
        return ParseStatus(False,
                           command=command,
                           message="_parse_r_equal() failed: {}.".format(e))


NEED_ACCESS_COMMANDS = ['r+', 'r-', 'clean', 'p', 'r', 'needed_review']
SECOND_LEVEL_COMMANDS = ['after']


# Part of the parse_comment logic. Handles commands like:
#
# * 'key=value'
# * 'key=[value1,value2,value3,...]'
#
# In here, the `last_r` argument is only used during the initialization step.
# It stores the last r+/r- command and the last afters command.
def _get_equal_param(queue, parts, pull, last_r, poster, workflow):
    if len(parts) != 2:
        return ParseStatus(False)
    funcs = {
        'p': _parse_priority,
        'r': _parse_r_equal,
        'after': _parse_after,
        'needed_review': _parse_needed_review,
    }
    if funcs.get(parts[0], None) is not None:
        if (parts[0] in NEED_ACCESS_COMMANDS
                and workflow.has_permission(poster) is False):
            return ParseStatus(False,
                               message='You don\'t have permission to do '
                                       'this.',
                               command=parts[0])
        if (parts[0] in SECOND_LEVEL_COMMANDS and
                workflow.check_permission_second_level(poster, pull) is False):
            return ParseStatus(False,
                               message='You don\'t have permission to do '
                                       'after the PR has been approved.',
                               command=parts[0])
    return funcs.get(parts[0], _parse_env_var)(parts, pull, queue, last_r)


def initialization_step_check(cmd):
    def sub_wrapper(func):
        def wrapper(*args, **kwargs):
            workflow = args[-1]
            poster = args[-2]
            if (cmd in NEED_ACCESS_COMMANDS and
                    workflow.has_permission(poster) is False):
                return ParseStatus(False,
                                   command=cmd,
                                   message='You don\'t have permission to '
                                           'do this.')
            if args[3] is None:
                # TODO: We do the same thing is another decorator. Could be
                # interesting to decorate the decorator.

                # Since this is a function with a given number of positional
                # arguments, it might be a problem if too much arguments were
                # given.
                args = args[:func.__code__.co_argcount]
                return func(*args, **kwargs)
            if cmd == 'r+' or cmd == 'r-':
                args[3]['last'] = cmd
            return ParseStatus(True, command=cmd[0])
        return wrapper
    return sub_wrapper


def clean_commands_pre_check(cmd, pull):
    if pull.status == const.APPROVED:
        return ParseStatus(False,
                           command=cmd,
                           message='PR is already approved. If you really want'
                                   ' to run `clean`, use `r-` before doing so.'
                                   ' :dizzy:')
    if pull.status == const.PENDING:
        return ParseStatus(False,
                           command=cmd,
                           message='PR is pending, cannot update it. '
                                   ':grimacing:')
    return None


@initialization_step_check("clean")
def clean_command(cmd, pull):
    ret = clean_commands_pre_check(cmd, pull)
    if ret is not None:
        return ret
    pull.env_args = {}
    pull.afters = []
    return ParseStatus(True, command=cmd)


@initialization_step_check("clean_env")
def clean_env_command(cmd, pull):
    ret = clean_commands_pre_check(cmd, pull)
    if ret is not None:
        return ret
    pull.env_args = {}
    return ParseStatus(True,
                       command=cmd,
                       message='Environment variables and after dependencies '
                               'have been removed.')


@initialization_step_check("r+")
def r_plus_command(cmd, pull, queue):
    if pull.status == const.APPROVED:
        if pull.sha is None:
            return ParseStatus(False,
                               command=cmd,
                               message='The PR has already been approved.')
        old_sha = pull.sha
        pull.sha = None
        return ParseStatus(False,
                           command=cmd,
                           message='SHA "{}" has been removed, PR is still '
                                   '__approved__.'.format(old_sha))
    elif pull.status == const.PENDING:
        ci_status = ci.get_ci_status(pull.repo_name(), pull.repo_owner(),
                                     pull.try_ci_url)
        if ci_status == 'running':
            return ParseStatus(False,
                               command=cmd,
                               message='The PR is already being tested at '
                                       '"{}".'.format(pull.ci_url))
        status, message = queue.try_update_to_pending(pull, insert_db=False)
        return ParseStatus(status,
                           command=cmd,
                           message=message)
    return ParseStatus(queue.update_status(pull, const.APPROVED),
                       command=cmd)


@initialization_step_check("r-")
def r_minus_command(cmd, pull, queue):
    pull.sha = None
    return ParseStatus(queue.update_status(pull, ''), command=cmd)


@initialization_step_check("try")
def try_command(cmd, pull, queue):
    if len(pull.try_ci_url) > 0:
        ci_status = ci.get_ci_status(pull.repo_name(), pull.repo_owner(),
                                     pull.try_ci_url)
        if ci_status == 'running':
            return ParseStatus(False,
                               command=cmd,
                               message='A try build is already running at '
                                       '"{}".'.format(pull.try_ci_url))
        pull.try_ci_url = ''
    try_ci_url, comment = ci.trigger_ci_build(pull.env_args,
                                              pull.get_target_repo(),
                                              pull.get_from_repo(),
                                              pull.target_branch(),
                                              pull.from_branch())
    if try_ci_url is not None:
        pull.try_ci_url = try_ci_url
        return ParseStatus(True,
                           command=cmd,
                           message="Try build successfully launched on '{}' "
                                   "with the following env. args:{}".format(
                                       try_ci_url,
                                       utils.gh_json(pull.env_args)))
    return ParseStatus(False, command=cmd, message=comment)


# Part of the parse_comment logic. Handles actions (so nothing like
# 'key=value' or any '=' thing).
def _get_command_param(queue, cmd, pull, last_r, poster, workflow):
    funcs = {
        'clean': clean_command,
        'clean_env': clean_env_command,
        'r+': r_plus_command,
        'r-': r_minus_command,
        'try': try_command,
    }
    call = funcs.get(cmd, None)

    if call is None:
        return ParseStatus(False, command=cmd, message='Unknown command')
    return call(cmd, pull, queue, last_r, poster, workflow)


# Part of the parse_comment logic. It returns current queue where this PR
# is.
def _get_queue(queue, type_of_queue):
    out = ''
    for pr in queue:
        out += '[#{}]({}),'.format(pr.number(), pr.get_url())
    if len(out) > 0:
        return '{} PRs: [{}]'.format(type_of_queue, out[:-1])
    return '{} PRs: []'.format(type_of_queue)


# Put "[...]" arguments all in one.
def parse_list(args, pull):
    pos = 0
    parsed = []
    while pos < len(args):
        if '[' in args[pos]:
            start = pos
            full = []
            while pos < len(args) and not args[pos].endswith(']'):
                full.append(args[pos])
                pos += 1
            if pos >= len(args):
                core.COMMENT_QUEUE.prepend(
                    utils.create_comment(
                        pull,
                        'Parsing error starting at "{}:{}": missing "]"'
                        .format(args[start], start)))
                return None
            full.append(args[pos])
            parsed.append(''.join(full))
        else:
            parsed.append(args[pos])
        pos += 1
    return parsed


# removing potential duplicates
def args_checks(parsed, pull):
    if parsed is None:
        return None, ''
    no_dup = []
    comment = ''
    for elem in parsed:
        if elem not in no_dup:
            no_dup.append(elem)
    if 'try' in no_dup and 'r+' in no_dup:
        core.COMMENT_QUEUE.prepend(
            utils.create_comment(
                pull, "Wo! 'try' and 'r+' in a same command?"
                      " :squirrel: Are you crazy human?! :mask:"
                      " :skull:"))
        return None, comment
    if len(no_dup) != len(parsed):
        comment = ("You thought I didn't see your duplicates? :rage: "
                   "Better be careful in the future human. :innocent:"
                   "\n\n")
    return no_dup, comment


def parse_commands(poster, no_dup, queue, pull, workflow, last_r):
    results = []
    for arg in no_dup:
        if arg == 'status':
            results.append(
                ParseStatus(True,
                            command=arg,
                            message='Currently:\n{}\n{}\n\n'.format(
                                _get_queue(queue.pending_prs, 'Pending'),
                                _get_queue(queue.approved_prs, 'Approved'))))
        else:
            func = _get_command_param
            if '=' in arg:
                func = _get_equal_param
                arg = arg.split('=')
            results.append(
                func(queue, arg, pull, last_r, poster, workflow))
    return ParseStatus.from_list(results)


# This function does multiple things in this order:
#
# * Check if Ultron has been summoned.
# * Get Ultron's commands.
# * Concat "key=[...]" commands into one. For example, the following
#   ['key=[value,' 'value2,' 'value3]'] will become:
#   'key=[value,value2,value3]'
# * Remove duplicates. If you want to run a command before and after a
#   change, do it in two comments.
# * Loop through commands and execute them.
#
# It stores all commands' outcome into a comment which will be posted
# later.
def parse_comment(queue, poster, pull, comment, workflow, last_r):
    if pull is None:
        return
    ultron_part = comment.split('@{}'.format(core.USERNAME))
    if len(ultron_part) < 2:
        return
    comment = ''
    successes = 0
    failures = 0
    turn = 0
    for part in ultron_part[1:]:
        args = part.split()
        if len(args) > 0 and args[0] == ':':
            args = args[1:]
        no_dup, cmt = args_checks(parse_list(args, pull), pull)
        comment += cmt
        if no_dup is None:
            continue
        # Ok, now we can parse commands.
        result = parse_commands(poster, no_dup, queue, pull,
                                workflow, last_r)
        if result.is_full_failure():
            failures += 1
        else:
            successes += 1
        turn += 1
        if turn > 1 and comment != '':
            comment += '\n\n@{}\'s invocation number {}:\n'.format(
                           core.USERNAME, turn)
        comment += str(result)
    if comment == '':
        comment = (':cry: No command received... :disappointed:\n\n'
                   'Or maybe you just wanted to summon me? :smiling_imp: '
                   'How nice of you! :smile:')
    else:
        if turn > 1:
            comment = '@{}\'s invocation number 1:\n{}'.format(core.USERNAME,
                                                               comment)
        if successes == 0 and failures > 1:
            comment += ('\n\nNone of your command{} succeeded. :hushed: You '
                        'should maybe take a look to the manual... :notebook:'
                        ':running:'.format("s" if failures != 1 else ""))
    if last_r is None:
        queue.update_next_to_pending()
    core.COMMENT_QUEUE.prepend(
        utils.create_comment(pull, comment, poster))
