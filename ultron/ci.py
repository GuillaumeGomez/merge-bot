import json
# pip3 install requests
import requests

from ultron import const
from ultron import core
from ultron import utils


def get_requests_json(req):
    try:
        req.raise_for_status()
    except Exception:
        raise Exception('request failed with status code: '
                        '{}'.format(req.status_code))
    return json.loads(utils.convert_to_string(req.content))


def get_build_num(path):
    path_split = path.split('/')
    if len(path_split) < 2:
        return None
    try:
        return int(path_split[-1])
    except Exception:
        return None


def get_tester(build_parameters, target_repo, from_repo, repo_workflow,
               target_branch, from_branch):
    # First, get easy information:
    # - repository name
    # - associated workflow
    # - environment variable name
    tester_repo = repo_workflow.get_tester_repository()
    if tester_repo is None:
        if (target_repo.get_name() != from_repo.get_name() or
                target_repo.get_owner() != from_repo.get_owner()):
            tester_repo = from_repo
        else:
            tester_repo = target_repo
    tester_workflow = core.QUEUES.get_workflow(tester_repo.get_name())
    tester_repo_envvar = utils.compute_repo_envvar(tester_repo.get_name())

    # Getting the branch is slightly more complex, due to the following
    # bits of logic/features:
    # - Mirror-branch mechanism over special branches (master, rel/*, target/*)
    # - Branch mapping: Triggering repo ( RealBranch -> MappedBranch )
    # - Branch mapping: Bystander+Tester repo ( MappedBranch -> RealBranch )
    tester_branch = build_parameters.get(tester_repo_envvar, None)
    if tester_branch is None:
        # In order to trigger the right branch for the tester repo,
        # we need to first get the "virtual" branch for the repo, ie:
        # map the branch for the triggering repo.
        # Then we can check our conditions, and finally trigger the "real"
        # unmapped branch for the tester repo
        mapped_target = repo_workflow.branch_map(target_branch)
        tester_unmapped = tester_workflow.branch_unmap(mapped_target,
                                                       default=mapped_target)
        if (target_repo.get_name() != tester_repo.get_name() and
            (mapped_target == 'master'
             or mapped_target.startswith('rel/')
             or mapped_target.startswith('target/'))):
            tester_branch = 'ultron/{}'.format(tester_unmapped)
        else:
            tester_branch = from_branch

    return {
        'name': tester_repo.get_name(),
        'owner': tester_repo.get_owner(),
        'envvar': tester_repo_envvar,
        'branch': tester_branch,
    }


def trigger_ci_build(build_parameters, target_repo, from_repo, target_branch,
                     from_branch):
    repo_name = target_repo.get_name()
    workflow = core.QUEUES.get_workflow(repo_name)
    repo_envvar = utils.compute_repo_envvar(repo_name)
    tester = get_tester(build_parameters, target_repo, from_repo, workflow,
                        target_branch, from_branch)

    payload = {
        'build_parameters': build_parameters,
    }
    # Here, ensure that the DEFAULT_BRANCH is properly set,
    # taking into account:
    # - The target branch of the PR
    # - The Branch Mapping of the trigerring project
    if 'DEFAULT_BRANCH' not in payload['build_parameters']:
        payload['build_parameters']['DEFAULT_BRANCH'] = \
            workflow.branch_map(target_branch)
    # Then, ensure that we're triggering the right branches for all project,
    # we update the dict of branches taking into account:
    # - The DEFAULT_BRANCH previously set
    # - The Branch Mapping of all other projects
    payload['build_parameters'].update(
        workflow.unmap_branches(
            payload['build_parameters']['DEFAULT_BRANCH'],
            payload['build_parameters']))

    payload['build_parameters'][tester['envvar']] = tester['branch']
    payload['build_parameters']['REPO_NAME'] = repo_name
    if repo_name != tester['name']:
        payload['build_parameters'][repo_envvar] = from_branch

    path = ('/api/v1/project/{}/{}/tree/{}?circle-token={}'.format(
             tester['owner'],
             tester['name'],
             # target_branch,
             tester['branch'],
             core.CIRCLE_TOKEN))
    req = None
    try:
        req = requests.post('{}{}'.format(const.CI_URL, path),
                            headers={'Content-type': 'application/json',
                                     'Accept': 'application/json'},
                            data=json.dumps(payload))
        data = get_requests_json(req)
        build_url = data.get('build_url', None)
        core.LOGS.info('trigger_ci_build: Received CI answer for PR in {}'
                       .format(repo_name))
        comment = utils.comment_launched_build(
            payload, build_url,
            str(data['message']) if 'message' in data else '')
        req.close()
        return build_url, comment
    except Exception as e:
        err = 'trigger_ci_build error: {}'.format(e)
        core.LOGS.error(err, e)
        out = 'Attempted request to "path={}"'.format(path)
        if req is not None and hasattr(req, 'content'):
            out += ' and got "content={}"'.format(req.content)
        core.LOGS.error(out)
        return None, err


def cancel_ci_build(project, ci_url):
    build_num = get_build_num(ci_url)
    if build_num is None:
        return False
    path = ('/api/v1/project/{}/{}/{}/cancel?circle-token={}'.format(
            # In the v1.1 version of the API, we have to pass 'github' in the
            # url.
            # 'github',
            core.ORGANIZATION,
            project,
            build_num,
            core.CIRCLE_TOKEN))
    try:
        data = get_requests_json(
            requests.post('{}{}'.format(const.CI_URL, path),
                          headers={'Content-type': 'application/json',
                                   'Accept': 'application/json'}))
        if 'canceled' in data:
            return data['canceled']
    except Exception as e:
        core.LOGS.error('cancel_ci_build error: {}'.format(e), e)
    return False


def get_ci_status(project, project_owner, ci_url):
    build_num = get_build_num(ci_url)
    if build_num is None:
        return False
    # https://circleci.com/docs/api/#build
    path = ('/api/v1/project/{}/{}/{}?circle-token={}'.format(
            # In the v1.1 version of the API, we have to pass 'github' in the
            # url.
            # 'github',
            project_owner,
            project,
            build_num,
            core.CIRCLE_TOKEN))
    try:
        data = get_requests_json(
            requests.get('{}{}'.format(const.CI_URL, path),
                         headers={'Accept': 'application/json'}))
        if 'status' in data:
            return data['status']
    except Exception as e:
        core.LOGS.error('get_ci_status error: {}'.format(e), e)
    return None


def handle_ci_response(ci_event):
    if 'payload' not in ci_event or 'build_url' not in ci_event['payload']:
        core.LOGS.info('Got CI message but ignored it: {}'.format(ci_event))
        return
    build_url = ci_event['payload']['build_url']
    outcome = ci_event['payload']['outcome']
    # TODO: check more statuses
    if (outcome == 'success' or
            outcome == 'failed' or
            outcome == 'timedout'):
        core.LOGS.info('Received circleCI message: {}'
                       .format(ci_event['payload']))
        messages = {
            'success': ':sunny: :+1: [circleCI test]({}) succeeded!',
            'failed': ':broken_heart: :umbrella: [circleCI test]({}) failed.',
            'timedout': ':broken_heart: :hourglass: [circleCI test]({}) '
                        'timed out...',
        }
        message = messages[outcome].format(build_url)

        for queue in core.QUEUES:
            for pr in queue['prs']:
                if pr.try_ci_url == build_url:
                    pr.try_ci_url = ''
                    core.COMMENT_QUEUE.prepend(
                        utils.create_comment(pr, message))
                    return
                elif pr.ci_url == build_url:
                    core.COMMENT_QUEUE.prepend(
                        utils.create_comment(pr, message))
                    pr.ci_url = ''
                    if outcome != 'success':
                        queue['prs'].update_status(pr, const.FAILED)
                    else:
                        ret, msg = queue['prs'].merge_pr(pr)
                        if ret is False:
                            if msg is None:
                                msg = (':broken_heart: :collision: Merge '
                                       'failed. Take a look at the logs for '
                                       'more information.')
                            else:
                                msg = (':broken_heart: :collision: Merge '
                                       'failed: {}'.format(msg))
                            core.COMMENT_QUEUE.prepend(
                                utils.create_comment(pr, msg))
                            pr.set_last_error(None)
                    queue['prs'].update_next_to_pending()
                    return
    else:
        core.LOGS.info('Got a CI event for "{}" with status "{}"'.format(
                        build_url, outcome))
