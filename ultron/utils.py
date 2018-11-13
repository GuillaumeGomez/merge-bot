import json
import re
import subprocess
import tempfile
# pip3 install py-gfm
import markdown
from mdx_gfm import GithubFlavoredMarkdownExtension

from ultron import const
from ultron import core
from ultron.comments import CommentDescription


SHA_PATTERN = re.compile(r'\b[0-9a-f]{7,40}\b')


def gh_json(dic):
    """Generates github flavored markdown json codeblock"""
    return "\n```json\n{}\n```".format(
        json.dumps(dic, indent=4, separators=(',', ': '))
    )


def is_valid_hash(sha):
    return re.match(SHA_PATTERN, sha) is not None


def markdown_converter(content):
    if content.__class__.__name__ == 'bytes':
        content = convert_to_string(content)
    try:
        return markdown.markdown(content,
                                 extensions=[
                                    GithubFlavoredMarkdownExtension()])
    except Exception as e:
        core.LOGS.error('markdown_converter failed: {}'.format(e), e)
    return None


# Transforms some github url into plain url:
#
# * #pr_number -> https://github.com/same_owner/same_project/pull/pr_number
# * project_owner/project#pr_number ->
#   https://github.com/project_owner/project/pull/pr_number
#
# Otherwise return the url.
def transform_github_url(url, current_url):
    if url.startswith(const.GH_URL) or '#' not in url:
        return url
    if url.startswith('#'):
        try:
            int(url[1:])  # To check if the last part is indeed a number.
            new_url = current_url.split('/pull/')
            new_url[-1] = url[1:]
            return '/pull/'.join(new_url)
        except Exception:
            return None
    parts = url.split('/')
    if len(parts) != 2:
        return url
    sub_parts = parts[1].split('#')
    if len(sub_parts) != 2:
        return url
    try:
        int(sub_parts[1])  # To check if the last part is indeed a number.
        return '{}/{}/{}/pull/{}'.format(const.GH_URL, parts[0],
                                         sub_parts[0], sub_parts[1])
    except Exception:
        pass
    return None


# Check if the url is a PR's url and return the PR if it is.
def check_github_url(url):
    if not url.startswith('{}/'.format(const.GH_URL)):
        raise Exception("Not a github url")
    parts = url.split('{}/'.format(const.GH_URL))
    if len(parts) != 2:
        raise Exception('Not a pull request URL')
    parts = parts[1].split("/")
    if len(parts) != 4 or parts[2] != 'pull':
        raise Exception('Not a pull request URL')
    pr_number = 0
    try:
        pr_number = int(parts[3])
    except Exception:
        raise Exception('Not a valid pull request number')
    try:
        # TODO/idea: write url cache to avoid performing useless GETs
        return core.GITHUB.get_pull(parts[1], parts[0], url,
                                    True, pr_number)
    except Exception as e:
        core.LOGS.error('check_github_url error: get_pull call failed: {}'
                        .format(e))
        raise Exception('No pull request found')


def is_x_branch(branch):
    return (branch == 'master' or branch.startswith("rel/")
            or branch.startswith("target/"))


def get_integration_branch(branch):
    return ("ultron/{}".format(branch)) if is_x_branch(branch) else branch


def get_mirror_branch(branch):
    return ("ultron/{}".format(branch)) if is_x_branch(branch) else ""


def comment_launched_build(payload, build_url, ci_message):
    if ci_message != '':
        ci_message = '\n\nCI message: "{}"\n\n'.format(ci_message)
    return ('Starting end to end procedure using the following payload:\n'
            '{}\n{}Please follow {} for CI status.'
            .format(gh_json(payload['build_parameters']),
                    ci_message,
                    build_url))


# Convert a bytes variable into an UTF-8 string.
def convert_to_string(s):
    if s.__class__.__name__ == 'bytes':
        return s.decode('utf-8')
    return s


def exec_command(command, timeout=30):
    child = subprocess.Popen(command, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE)
    stdout, stderr = child.communicate(timeout=timeout)
    return (child.returncode == 0,
            convert_to_string(stdout),
            convert_to_string(stderr))


def join_outputs(stdout, stderr):
    return '===== STDOUT =====\n{}\n\n===== STDERR =====\n{}'.format(stdout,
                                                                     stderr)


# This function try to find useful error from the stdout/stderr passed as
# arguments.
#
# First it looks for merge conflicts. If none found, it then look for github
# push error.
def extract_error(out, err):
    r = '\n'.join([line for line in out.split('\n')
                   if 'Merge conflict in' in line])
    if len(r) != 0:
        return '\n```\n{}\n```'.format(r)
    r = '\n'.join([line for line in err.split('\n')
                   if 'remote: error:' in line])
    if len(r) != 0:
        return '\n```\n{}\n```'.format(r)
    return None


def exec_commands(commands, func_name, logs=False):
    for command in commands:
        try:
            ret, stdout, stderr = exec_command(command)
            if not ret:
                core.LOGS.error('exec_commands["{}"] command failed "{}":\n'
                                '{}\n\n=> Full commands:\n> {}'
                                .format(func_name, command,
                                        join_outputs(stdout, stderr),
                                        '\n> '.join([' '.join(y)
                                                     for y in commands])))
                return (False, extract_error(stdout, stderr))
        except subprocess.TimeoutExpired:
            core.LOGS.error('exec_commands["{}"] failed: "{}" command timed '
                            'out\n\n=> Full commands:\n> {}'
                            .format(func_name, command,
                                    '\n> '.join([' '.join(y)
                                                 for y in commands])))
            return (False, 'Command timed out')
        except Exception as ex:
            core.LOGS.error('exec_commands["{}"] failed on "{}": {}\n\n'
                            '=> Full commands:\n> {}'
                            .format(func_name, command, ex,
                                    '\n> '.join([' '.join(y)
                                                 for y in commands])))
    if logs is True:
        core.LOGS.info('exec_commands["{}"] successfully ran on:\n> {}'
                       .format(func_name,
                               '\n> '.join([' '.join(y) for y in commands])))
    return (True, None)


def create_comment(pull, comment, poster=''):
    message = ('Hello @{}\n\n'.format(poster)) if poster != '' else ''
    return CommentDescription('{}{}'.format(message, comment), pull)


def check_if_branch_exists(github_event, branch_name):
    repo_name = github_event['repository']['name']
    owner = github_event['repository']['owner']['name']

    try:
        core.GITHUB.get_repo_branch(branch_name, repo_name, owner)
    except Exception:
        return False
    return True


def add_key_repo_url(url):
    return url.replace("://github.", '://{}@github.'.format(
                        core.GITHUB_TOKEN))


def join_outs(stdout, stderr):
    if len(stdout) > 0 and len(stderr) > 0:
        return '{}\n{}'.format(stdout, stderr)
    return '{}{}'.format(stdout, stderr)


def is_forward_port(folder):
    try:
        ret1, stdout1, stderr1 = exec_command(['bash', '-c',
                                               'cd {} && git log -1 '
                                               '--format=%H'.format(folder)])
        out1 = join_outs(stdout1, stderr1)
        ret, stdout, stderr = exec_command(['bash', '-c',
                                            'cd {} && git log -1 --no-merges '
                                            '--format=%H'.format(folder)])
        out2 = join_outs(stdout, stderr)
        return ret1 is True and ret is True and len(out1) != 0 and out1 != out2
    except Exception as err:
        core.LOGS.error('is_forward_port failed: {}'.format(err))
        return False


def make_pr_commands(pr, do_push, function_name, logs=False):
    from_repo_url = add_key_repo_url(pr.get_from_repo_url())
    target_repo_url = add_key_repo_url(pr.get_repo_url())
    with tempfile.TemporaryDirectory() as tmpdirname:
        commands = [
            ['git', 'clone', from_repo_url, '--depth',
             str(pr.get_number_of_commits() + 1), '-b', pr.from_branch(),
             tmpdirname],
            ['bash', '-c', 'cd {} && git remote add upstream "{}"'.format(
                tmpdirname, target_repo_url)],
            # TODO: Would be nice to fetch only one branch
            ['bash',
             '-c', 'cd {} && git fetch upstream'.format(
                tmpdirname)]]
        ret, stdout = exec_commands(commands, function_name, logs=True)
        if ret is False:
            return (False, stdout)
        if is_forward_port(tmpdirname):
            commands = [['bash', '-c', 'cd {} && git checkout upstream/{}'
                        .format(tmpdirname, pr.target_branch())]]
            if pr.sha is None:
                commands.append(
                    ['bash', '-c', 'cd {} && git merge --no-ff --no-edit '
                     '--no-commit origin/{}'.format(tmpdirname,
                                                    pr.from_branch())])
            else:
                commands.append(
                    ['bash', '-c', 'cd {} && git merge --no-ff --no-edit '
                     '--no-commit origin/{} HEAD {}'.format(
                        tmpdirname, pr.from_branch(), pr.sha)])
        else:
            commands = [
                # To group all remote branch's commits, we rebase first and
                # then we merge.
                ['bash', '-c', 'cd {} && git rebase upstream/{}'.format(
                    tmpdirname, pr.target_branch())],
                ['bash', '-c', 'cd {} && git checkout upstream/{}'.format(
                    tmpdirname, pr.target_branch())],
                ['bash', '-c', 'cd {} && git merge --no-ff --no-edit '
                 '--no-commit {}'
                 .format(tmpdirname, pr.from_branch())]]
            if pr.sha is not None:
                commands[2] = [
                    'bash', '-c', 'cd {} && git merge --no-ff --no-edit '
                    '--no-commit origin/{} HEAD {}'.format(
                        tmpdirname, pr.from_branch(), pr.sha)
                ]
        if do_push:
            commands.append(['bash', '-c',
                             'cd {0} && git commit -m "merge #{1}" '
                             '--author="{2} <{2}@orga.com>"'
                             .format(tmpdirname, pr.number(), core.USERNAME)])
            commands.append(['bash', '-c',
                             'cd {} && git push upstream HEAD:{}'.format(
                                 tmpdirname, pr.target_branch())])
            # If the from branch is on the target repo, then we delete it.
            if pr.get_from_repo_url() == pr.get_repo_url():
                commands.append([
                    'bash', '-c', 'cd {} && git push upstream --delete {}'
                        .format(tmpdirname, pr.from_branch())])
        return exec_commands(commands, function_name, logs=logs)


# Checking if a PR is mergeable through a rebase instead of a merge seemed
# easier for me.
def check_if_mergeable(pr):
    core.LOGS.info('Checking if {}#{} from {} into {} is mergeable.'
                   .format(pr.repo_name(), pr.number(), pr.from_branch(),
                           pr.target_branch()))
    try:
        return make_pr_commands(pr, False, 'check_if_mergeable', logs=True)
    except Exception as e:
        core.LOGS.error('check_if_mergeable failed: (PR #{} from {} to {})\n{}'
                        .format(pr.number(), pr.from_branch(),
                                pr.target_branch(), e))
    return (False, None)


# Takes in a PRQueueItem as parameter.
def merge_pr(pr):
    core.LOGS.info('Trying to merge {}#{} from {} into {}.'
                   .format(pr.repo_name(), pr.number(), pr.from_branch(),
                           pr.target_branch()))
    try:
        ret, stdout = make_pr_commands(pr, True, 'merge_pr')
        if ret is True:
            core.LOGS.info('PR "{}" has been successfully merged into {}.'
                           .format(pr.get_url(), pr.target_branch()))
        return (ret, stdout)
    except Exception as e:
        core.LOGS.error('merge_pr failed: {}'.format(e))
    return (False, None)


# Takes a dictionary as first argument and then keys.
def safe_get(*args):
    c = args[0].get(args[1], None)
    if c is None:
        return None
    if len(args) > 2:
        return safe_get(*(c,) + args[2:])
    return c


def compute_repo_envvar(repo_name):
    return 'ORGA_{}_BRANCH'.format(repo_name.upper().replace('-', '_'))
