from ultron import const
from ultron import core
from ultron import utils


def create_command_list(clone_url, original_branch, branch, forced, hash_):
    return [['git', 'clone', utils.add_key_repo_url(clone_url), '-b',
             original_branch, hash_],
            ['bash', '-c', 'cd {} && git push {} origin HEAD:{}'.format(
              hash_, forced, branch)],
            ['rm', '-rf', hash_]]


def handle_mirroring(github_event, original_branch):
    branch_name = utils.get_mirror_branch(original_branch)
    if len(branch_name) < 1:
        return

    forced = "-f" if github_event['forced'] is True else ""

    if not utils.check_if_branch_exists(github_event, branch_name):
        return

    core.LOGS.info('Attempting to mirror into "{}"'.format(branch_name))

    commands = create_command_list(
        github_event['repository']['clone_url'],
        original_branch,
        branch_name,
        forced,
        # `after` is the last id's commit of
        # the push, used as temp dir's name.
        github_event['after']
    )

    try:
        if utils.exec_commands(commands, 'handle_mirroring'):
            core.LOGS.info('Commands exited successfully')
    except Exception as e:
        core.LOGS.error('handle_mirroring failed: {}'.format(e), e)


def handle_push(github_event):
    try:
        original_branch = github_event['ref'].replace("refs/heads/", "")

        pr = core.QUEUES.get_pr_from_head_commit(
            github_event['repository']['name'], github_event['before'])
        if pr is not None and pr.from_branch() == original_branch:
            core.LOGS.info('PR {}/#{} has been updated'.format(
                            pr.repo_name(), pr.number()))
            q = core.QUEUES.get_queue(
                github_event['repository']['name'])
            if q is not None:
                pr.set_last_error(None)
                try:
                    pull = pr.get_github_pr()
                    reviews = None
                    if pull is not None:
                        reviews = pull.get_reviews()
                    if reviews is not None:
                        for review in reviews:
                            if review.state == "APPROVED":
                                try:
                                    review.dismiss('Do it again human slave!'
                                                   ':point_right: :runner: '
                                                   '(Oh and the pull request '
                                                   'has been updated, by the '
                                                   'way.)')
                                except Exception as e:
                                    core.LOGS.error(
                                        "handle_push: couldn't dismiss review"
                                        ' "{}": {}'.format(review.body, e))
                                    pass
                except Exception as e:
                    core.LOGS.error("handle_push: couldn't dismiss reviews: {}"
                                    .format(e))
                ci_url = pr.ci_url
                old_status = pr.status
                # TODO: should we cancel try builds as well when an update
                # happens?
                mergeable, err_msg = utils.check_if_mergeable(pr)
                if mergeable is False:
                    if err_msg is not None and pr.can_print_message(err_msg):
                        core.COMMENT_QUEUE.append(
                            utils.create_comment(pr, err_msg))
                        pr.set_last_error(err_msg)
                    q.update_status(pr, const.NOT_MERGEABLE)
                else:
                    q.update_status(pr, '')
                if old_status == 'pending':
                    core.COMMENT_QUEUE.prepend(
                        utils.create_comment(pr,
                                             "PR has been updated. Build {} "
                                             "has been canceled. New review "
                                             "required.".format(ci_url)))
                elif old_status == 'approved':
                    core.COMMENT_QUEUE.prepend(
                        utils.create_comment(pr,
                                             "PR has been updated. It has lost"
                                             " its 'approved' status. New "
                                             " review required."))
                else:
                    core.COMMENT_QUEUE.prepend(
                        utils.create_comment(pr,
                                             "PR has been updated. Reviewers, "
                                             "please be cautious."))
                core.COMMENT_QUEUE.flush()
                # since it was a PR work, we don't want to mirror it.
                return

        #
        # Mirroring part
        #
        handle_mirroring(github_event, original_branch)
    except Exception as ex:
        core.LOGS.error('handle_push failed: {}'.format(ex), ex)


def handle_comment(github_event):
    try:
        if ('comment' not in github_event
                or 'body' not in github_event['comment']
                or 'issue' not in github_event
                or 'pull_request' not in github_event['issue']):
            return

        poster = github_event['comment']['user']['login']
        if (poster == core.USERNAME or
                ('@{}'.format(core.USERNAME)) not in
                github_event['comment']['body'] or
                github_event['action'] != 'created' or
                github_event['issue']['state'] != 'open'):
            return

        pr_number = github_event['issue']['number']
        repo_name = github_event['repository']['name']
        # is_private = github_event['repository']['private']
        owner = github_event['repository']['owner']['login']

        if poster == core.USERNAME:
            return
        core.LOGS.info('received PR comment: '
                       'owner: {} / '
                       'repo: {} / '
                       'PR number: {}'.format(
                        owner,
                        repo_name,
                        pr_number))

        core.QUEUES.parse_comment(
            repo_name, poster, pr_number,
            github_event['comment']['body'])
        core.COMMENT_QUEUE.flush()
    except Exception as ex:
        core.LOGS.error('handle_comment failed: {}'.format(ex), ex)


def handle_pr_event(github_event):
    if (github_event['action'] == 'opened'
            or github_event['action'] == 'reopened'):
        pr_event = github_event['pull_request']
        core.QUEUES.add_pr(
            core.GITHUB.create_pull(pr_event))
    elif github_event['action'] == 'closed':
        # If the following condition is true, it hasn't been merged.
        # if github_event['base']['merged'] is False:
        core.QUEUES.remove_closed(
            github_event['pull_request']['base']['repo']['name'],
            github_event['pull_request']['number'])
    elif (github_event['action'] == 'edited'
          and github_event['pull_request']['state'] == 'open'):
        pr_event = github_event['pull_request']
        target_branch = pr_event['base']['ref']
        old_target_branch = utils.safe_get(github_event,
                                           'changes', 'base', 'ref', 'from')
        nb_commits = 250
        try:
            nb_commits = int(pr_event['commits'])
        except Exception as ex:
            core.LOGS.error('handle_pr_event: int("{}") failed'
                            .format(pr_event['commits']), ex)
        core.QUEUES.update_pr(
            pr_event['base']['repo']['name'],
            pr_event['number'],
            pr_event['title'],
            target_branch,
            old_target_branch,
            utils.safe_get(github_event, 'repository', 'default_branch'),
            nb_commits)


def handle_event(github_event):
    if ('pusher' in github_event
            and github_event['created'] is False
            and github_event['deleted'] is False):
        handle_push(github_event)
    elif 'action' in github_event and 'pull_request' in github_event:
        handle_pr_event(github_event)
    else:
        handle_comment(github_event)
