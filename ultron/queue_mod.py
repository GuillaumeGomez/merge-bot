# This file is very different from 'my_github.py': it uses classes of
# 'my_github.py' to interact with github so classes' names here are very
# close to 'my_github.py' ones. Please keep in mind that this file represents
# Ultron's queue whereas 'my_github.py' represents Github's view.
import copy
import json

from ultron import ci
from ultron import const
from ultron import core
from ultron import parse
from ultron import scheduler
from ultron import utils
from ultron.parse_status import ParseStatus

# /!\ WARNING /!\ Dark magic in here! Stupid hack for stupid Python.
# You can find a similar issue here:
# http://stackoverflow.com/questions/15161843/python-module-empty-after-import
if 'get_ci_status' not in dir(ci):
    from importlib import reload
    ci = reload(ci)


# Class used to make PRQueueItem's priority handling more easy and intuitive.
class Priority:
    def __init__(self, priority=0):
        self.priority = priority
        self.cmp_priority = self._convert()

    def update(self, new_priority):
        self.priority = new_priority
        self.cmp_priority = self._convert()

    def _convert(self):
        if self.priority == const.ROLLUP:
            return -1
        return int(self.priority)

    def __str__(self):
        return str(self.priority)

    def __lt__(self, other):
        if other.__class__.__name__ != 'Priority':
            return self < Priority(other)
        return self.cmp_priority < other.cmp_priority

    def __le__(self, other):
        if other.__class__.__name__ != 'Priority':
            return self <= Priority(other)
        return self.cmp_priority <= other.cmp_priority

    def __gt__(self, other):
        if other.__class__.__name__ != 'Priority':
            return self > Priority(other)
        return self.cmp_priority > other.cmp_priority

    def __ge__(self, other):
        if other.__class__.__name__ != 'Priority':
            return self >= Priority(other)
        return self.cmp_priority >= other.cmp_priority

    def __eq__(self, other):
        if other.__class__.__name__ != 'Priority':
            return self.priority == other
        return self.cmp_priority == other.cmp_priority

    def __ne__(self, other):
        if other.__class__.__name__ == 'Priority':
            return self.priority != other
        return self.cmp_priority != other.cmp_priority


# Represents a PullRequest inside a queue.
#
# For more comfort, most of the needed my_github.PullRequest variable have
# a method in here to get them.
class PRQueueItem:
    def __init__(self, priority, afters, status, pr,
                 ci_url='', env_args={}, sha=None):
        # Represents the pending build's url. If it succeeds, PR gets merged.
        self.ci_url = ci_url
        # Represents the "try" build's url. If it succeeds, it just prints the
        # build status on the PR and it doesn't do anything else.
        self.try_ci_url = ''
        # Represents the priority of the PR is queue. The higher the priority,
        # the quicker the PR will be tested.
        self.priority = Priority(priority)
        # Represents dependencies of the PR. A PR won't be tested as long as
        # not all of afters' dependencies have been merged/closed.
        self.afters = afters
        # Current status of the PR in the queue. Here are the possible values:
        #
        # * ''             : Default. Nothing particular.
        # * 'approved'     : The PR has been approved and is waiting its turn
        #                    to get tested and merged (if tests succeeded).
        # * 'pending'      : The PR is currently being tested.
        # * 'failed'       : If the pending build failed, it gets this status.
        # * 'not mergeable': If the PR isn't mergeable.
        self.status = status
        # It is my_github.PullRequest class.
        self.pr = pr
        # Not implemented for now.
        #
        # 0 means that the review needed system is disabled.
        self.needed_review = 0
        # Not implemented for now.
        #
        # Represents the number of approval for a PR.
        self.reviews = 0
        # Represents the environment arguments.
        self.env_args = copy.deepcopy(env_args)
        # Commit from which the PR should be merged.
        self.sha = sha
        if self.sha is not None and sha == "":
            self.sha = None
        # Last error displayed to avoid giving out the same information twice
        self.last_error = None

    # not very useful on its own but it provides an equivalent of:
    # `pr = new_pr` (but instead we use `.update()`)
    def update(self, other):
        self.ci_url = other.ci_url
        self.try_ci_url = other.try_ci_url
        self.priority = other.priority
        self.afters = other.afters
        self.status = other.status
        self.pr = other.pr
        self.needed_review = other.needed_review
        self.reviews = other.reviews
        self.env_args = copy.deepcopy(other.env_args)
        self.sha = other.sha

    def number(self):
        return self.pr.number

    def create_issue_comment(self, message):
        return self.pr.create_issue_comment(message)

    def get_url(self):
        return self.pr.get_url()

    def get_target_branch_url(self):
        return self.pr.get_target_branch_url()

    def get_repo_url(self):
        return self.pr.get_repo_url()

    def target_branch(self):
        return self.pr.target_branch

    def from_branch(self):
        return self.pr.from_branch

    def repo_name(self):
        return self.pr.get_target_repo().get_name()

    def repo_owner(self):
        return self.pr.get_target_repo().get_owner()

    def title(self):
        return self.pr.title

    def head_commit(self):
        return self.pr.head_commit

    def get_from_repo_url(self):
        return self.pr.get_from_repo_url()

    def get_from_repo(self):
        return self.pr.get_from_repo()

    def get_target_repo(self):
        return self.pr.get_target_repo()

    def get_mergeable_status(self):
        return self.pr.get_mergeable_status()

    def _get_pr(self):
        return self.pr

    def get_number_of_commits(self):
        return self._get_pr().get_number_of_commits()

    def get_ci_url(self):
        return self.ci_url

    def get_github_pr(self):
        return core.GITHUB.get_pull(self.repo_name(), self.repo_owner(),
                                    self.get_url(), True, self.number())

    def set_last_error(self, last_error):
        self.last_error = last_error

    def can_print_message(self, err_msg):
        return (err_msg is not None and len(err_msg) > 0 and
                self.last_error != err_msg)

    def has_external_after(self):
        if core.QUEUES is None:
            return False
        for after in self.afters:
            for queue in core.QUEUES:
                repo_url = core.QUEUES.repos[queue['name']].get_url()
                if after.startswith(repo_url):
                    continue
                return True
        return False

    def update_status(self, status):
        self.status = status
        self.set_last_error(None)


# An iterator utility to loop through PRQueue.
class PRIterator:
    def __init__(self, prs):
        self.prs = prs
        self.current = 0
        self.sub_current = 0

    def __next__(self):
        if len(self.prs) < 1:
            raise StopIteration
        while (self.current < len(self.prs) and
               self.sub_current >= len(self.prs[self.current])):
            self.sub_current = 0
            self.current += 1
        if self.current >= len(self.prs):
            raise StopIteration
        self.sub_current += 1
        return self.prs[self.current][self.sub_current - 1]


# Check if all dependencies have been merged/closed.
#
# TODO: It's possible that someone enters a cyclic after thing. Might be nice
# and useful to check it.
# However it's possible that they might want a cyclic stuff in order to block
# the queue.
def check_after_urls(urls_to_check, pull):
    ret = []
    for url in urls_to_check:
        new_url = utils.transform_github_url(url, pull.get_url())
        if new_url is None:
            ret.append(ParseStatus(False,
                                   command=url,
                                   message='Invalid PR url: "{}"'.format(url)))
            continue
        if new_url in pull.afters:
            ret.append(ParseStatus(False,
                                   command=url,
                                   message="'{}': duplicate".format(new_url)))
            continue
        try:
            utils.check_github_url(new_url)
            pull.afters.append(new_url)
            ret.append(ParseStatus(True, command=url))
        except Exception as e:
            ret.append(ParseStatus(False,
                                   command=url,
                                   message='"{}": {}'.format(url, e)))
    return ParseStatus.from_list(ret, 'after')


# corresponds to PRQueue.all_prs
EQS = {
    const.PENDING: 0,
    const.FAILED: 1,
    const.NOT_MERGEABLE: 2,
    const.APPROVED: 3,
    '': 4,
}


# Represents a queue. Contains only PRQueueItem elements.
#
# It is the class which handles how PRs are handled (testing order, merge and
# stuff...).
class PRQueue:
    def __init__(self):
        self.pending_prs = []
        self.failed_prs = []
        self.not_mergeable_prs = []
        self.approved_prs = []
        self.other_prs = []
        self.all_prs = [self.pending_prs, self.failed_prs,
                        self.not_mergeable_prs, self.approved_prs,
                        self.other_prs]

    # TODO: when there is only rollup PRs in the approved queue, we could try
    # merging all at once.
    #
    # No check is done in this method, be careful (the point is to be fast).
    def add_pr(self, pr):
        if pr.status == const.APPROVED:
            if pr.priority == const.ROLLUP:
                self.approved_prs.append(pr)
                return
            i = 0
            # We add the new approved PR at the end of the approved queue.
            while i < len(self.approved_prs):
                if self.approved_prs[i].priority < pr.priority:
                    break
                i += 1
            # However, if the PR has dependency, it must block other PRs of the
            # same of lower priority level.
            if len(pr.afters) > 0:
                while (i > 0
                       and self.approved_prs[i - 1].priority == pr.priority
                       and len(self.approved_prs[i - 1].afters) < 1):
                    i -= 1
            if i >= len(self.approved_prs):
                self.approved_prs.append(pr)
            else:
                self.approved_prs.insert(i, pr)
        else:
            self.all_prs[EQS[pr.status]].append(pr)

    # Update a PRQueueItem with another's values.
    def update_pr_values(self, updated_pr):
        if updated_pr.status not in EQS:
            core.LOGS.error('Unknown PR status: "{}"'.format(
                                      updated_pr.status))
            return
        # I can't use self.get_pr here because I need more information than it
        # provides.
        for elem in self.all_prs:
            i = 0
            for pr in elem:
                if pr.number() == updated_pr.number():
                    self._update_pr_values(elem, updated_pr, i)
                    return
                i += 1
        # The PR doesn't exist, we add it.
        self.add_pr(updated_pr)

    def _update_pr_values(self, pr_list, updated_pr, pos):
        pr_list.pop(pos)
        if updated_pr.is_merged:
            return
        self.add_pr(updated_pr)

    def get_pr(self, pr_number):
        for prs in self.all_prs:
            for pr in prs:
                if pr.number() == pr_number:
                    return pr
        return None

    def _check_afters(self, pr):
        if len(pr.afters) != 0:
            for after in pr.afters:
                try:
                    other = utils.check_github_url(after)
                    if other is not None and other.is_open is True:
                        # Since the "parent" PR is open, we can't do anything.
                        return (False, "One dependency hasn't been merged yet")
                except Exception as e:
                    core.LOGS.error('try_update_to_pending error: {}'
                                    .format(e), e)
                    return (False,
                            "Unexpected error occurred. Take a look to the "
                            "logs")
        if self.update_status(pr, const.PENDING) is False:
            return (False, "Couldn't update to pending")
        return (True, "")

    def _pre_checks(self, pr):
        if pr.status != const.APPROVED:
            return (False, "Pull request isn't approved")
        # First, we check if there is already a pending pr on the same branch.
        for pull in self.pending_prs:
            if pr.target_branch() == pull.target_branch():
                return (False,
                        "There is already a pending pull request on "
                        "the same branch")
        ret, msg = self.is_next_on_branch(pr)
        if ret is False:
            return (ret, msg)
        if pr.get_mergeable_status() is not True:
                ret, msg = utils.check_if_mergeable(pr)
                if ret is False:
                    self.update_status(pr, const.NOT_MERGEABLE)
                    if msg is not None:
                        return (False,
                                "This pull request isn't mergeable:\n{}"
                                .format(msg))
                    return (False, "This pull request isn't mergeable.")
        return self._check_afters(pr)

    def try_update_to_pending(self, pr, insert_db=True):
        status, message = self._pre_checks(pr)
        if status is False:
            return (False, message)
        ci_url, comment = ci.trigger_ci_build(pr.env_args,
                                              pr.get_target_repo(),
                                              pr.get_from_repo(),
                                              pr.target_branch(),
                                              pr.from_branch())
        if ci_url is None:
            self.update_status(pr, const.FAILED)
            return (False,
                    ':broken_heart: :umbrella: Cannot trigger CI: {}'.format(
                        comment))
        pr.ci_url = ci_url
        if insert_db is True:
            core.DB.insert_pending_pr(pr.repo_name(), pr.number(),
                                      pr.target_branch(), pr.ci_url,
                                      pr.priority, pr.env_args,
                                      pr.sha)
        else:
            core.DB.update_pending_pr(pr.repo_name(), pr.number(), ci_url)

        core.COMMENT_QUEUE.append(
            utils.create_comment(pr.pr,
                                 ':hourglass: PR is now __pending__. CI build'
                                 ' url: {}'.format(ci_url)))
        return (True, '')

    def is_next_on_branch(self, pr):
        # Check if the pr is the first in the approved queue.
        for pull in self.approved_prs:
            if pull.target_branch() == pr.target_branch():
                if pull.number() != pr.number():
                    return (False,
                            "Another pull requests (#{}) has a higher priority"
                            .format(pull.number))
                return (True, "")
        return (False, "The pull request hasn't been found...")

    def update_next_to_pending(self):
        # TODO: A potential improvement could be to stop once every branch has
        #       a pending PR. To see later.
        for pr in self.approved_prs:
            is_next_on_branch = self.is_next_on_branch(pr)[0]
            ret, err_msg = self.try_update_to_pending(pr)
            if ret is False:
                if is_next_on_branch is True:
                    if pr.can_print_message(err_msg):
                        core.COMMENT_QUEUE.append(
                            utils.create_comment(pr, err_msg))
                        pr.set_last_error(err_msg)
                    if pr.has_external_after() is True:
                        core.SCHEDULER.add(
                            scheduler.ScheduleInfo(
                                scheduler.try_update_pendings))

    def update_status(self, pr, new_status):
        if pr is None:
            return False
        if new_status not in EQS:
            core.LOGS.error('Unknown PR status: "{}"'.format(new_status))
            return False
        if new_status == pr.status:
            return True
        if new_status != const.APPROVED and new_status != const.PENDING:
            pr.sha = None
        pos = 0
        found = False
        for _pr in self.all_prs[EQS[pr.status]]:
            if _pr.number() == pr.number():
                self.all_prs[EQS[pr.status]].pop(pos)
                found = True
                break
            pos += 1
        if found is True:
            if pr.status == const.PENDING:
                ci.cancel_ci_build(pr.repo_name(), pr.ci_url)
                core.DB.delete_pending_pr(pr.repo_name(), pr.number())
                pr.ci_url = ''
            pr.update_status(new_status)
            self.add_pr(pr)
        return found

    def update_priority(self, pr, new_priority):
        if pr is None:
            return False
        if pr.status not in EQS:
            core.LOGS.error('Unknown PR status: "{}"'.format(pr.status))
            return False
        if pr.priority == new_priority:
            # No need to update
            return True
        pr.priority.update(new_priority)
        pos = 0
        for _pr in self.all_prs[EQS[pr.status]]:
            if _pr.number() == pr.number():
                self.all_prs[EQS[pr.status]].pop(pos)
                self.add_pr(pr)
                return True
            pos += 1
        # PR not found? What the hell?!
        return False

    def parse_comment(self, poster, pull, comment, workflow,
                      last_r=None):
        parse.parse_comment(self, poster, pull, comment, workflow, last_r)

    # Not used for the moment.
    def update_needed_review(self, pr, needed_review):
        if pr is None or needed_review < 0:
            return False
        if needed_review == 0:
            pr.needed_review = 0
            pr.reviews = 0
        else:
            pr.needed_review = needed_review
            if pr.reviews > pr.needed_review:
                # TODO: Trigger approved
                pass
        return True

    def remove_closed(self, pr_number):
        for prs in self.all_prs:
            pos = 0
            for pr in prs:
                if pr.number() == pr_number:
                    prs.pop(pos)
                    return True
                pos += 1
        return False

    # In here, the returned value doesn't indicate if a PR has been updated
    # but if the queue needs to be computed again.
    def update_pr(self, pr_number, title, target_branch, old_target_branch,
                  default_branch, number_of_commits):
        for prs in self.all_prs:
            for pr in prs:
                if pr.number() == pr_number:
                    if pr.title() != title:
                        pr._get_pr().title = title
                    pr._get_pr().number_of_commits = number_of_commits
                    if (pr.target_branch() != target_branch or
                            old_target_branch == target_branch):
                        # github doesn't return the new targetted branch
                        # when the new target is the default branch it seems...
                        if old_target_branch == target_branch:
                            pr._get_pr().target_branch = default_branch
                        else:
                            pr._get_pr().target_branch = target_branch
                        # We do this to be sure the PR will be moved according
                        # to its new target branch.
                        if pr.status == '':
                            self.update_status(pr, const.FAILED)
                        self.update_status(pr, '')
                        return True
                    break
        return False

    def merge_pr(self, pr):
        if pr.status != const.PENDING:
            core.LOGS.error('merge_pr failed: PR {}/#{} isn\'t '
                            'pending.'.format(pr.repo_name(),
                                              pr.number()))
            return (False, 'This pull request isn\'t pending')
        found = False
        for _pr in self.pending_prs:
            if _pr.number() == pr.number():
                found = True
                break
        if found is False:
            core.LOGS.error('merge_pr failed: PR {}/#{} not in this '
                            'queue.'.format(pr.repo_name(),
                                            pr.number()))
            return (False, None)
        ret, stdout = utils.merge_pr(pr)
        if ret is False:
            self.update_status(pr, const.NOT_MERGEABLE)
            return (ret, stdout)
        self.remove_closed(pr.number())
        core.DB.delete_pending_pr(pr.repo_name(), pr.number())
        return (True, None)

    def __iter__(self):
        return PRIterator(self.all_prs)


# Represents a queue repository (as its name states it). To better understand
# the usage of this class, here is a nice little scheme:
#
#                 Queues                   (Queues)
#                   |
#       ---------------------------
#       |                         |
#     Repo1                     Repo2      (QueueRepository)
#       |                         |
#    PrQueue1                  PrQueue2    (PRQueue)
#       |                         |
#   ----------                ---------
#   |        |                |       |
#  Pr1      Pr2              Pr3     Pr4   (PRQueueItem)
#
# In basic logic, this class is mainly useless and we could move the handling
# of the repository directly into the PRQueue class. However, for more
# clarity, I *strongly* prefer/advise to keep it.
class QueueRepository:
    def __init__(self, repo, q, workflow):
        self.repo = repo
        self.q = q
        self.workflow = workflow

    def __iter__(self):
        return PRIterator(self.q.all_prs)

    def get_pr(self, pr_number):
        return self.q.get_pr(pr_number)

    def add_pr(self, pr):
        return self.q.add_pr(pr)

    def remove_closed(self, pr_number):
        self.q.remove_closed(pr_number)
        self.update_next_to_pending()

    def update_pr(self, pr_number, title, target_branch, old_target_branch,
                  default_branch, number_of_commits):
        if self.q.update_pr(pr_number, title, target_branch,
                            old_target_branch, default_branch,
                            number_of_commits):
            self.update_next_to_pending()

    def update_next_to_pending(self):
        return self.q.update_next_to_pending()

    def get_pr_from_head_commit(self, head_commit):
        for pr in self:
            if pr.head_commit() == head_commit:
                return pr
        return None

    def merge_pr(self, pr):
        return self.q.merge_pr(pr)

    def parse_comment(self, pr_number, poster, comment):
        pull = self.get_pr(pr_number)
        if pull is None:
            core.LOGS.error('Unknown PR: {}/#{}'.format(
                            self.repo.name, pr_number))
            return
        self.q.parse_comment(poster, pull, comment, self.workflow)
        if pull.status == const.APPROVED:
            self.q.try_update_to_pending(pull)

    # This method isn't very useful as if but at least it allows to easily
    # find where it's modified.
    def set_workflow(self, workflow):
        self.workflow = workflow

    def update_status(self, pr, new_status):
        return self.q.update_status(pr, new_status)

    def get_url(self):
        return self.repo.get_url()


# An iterator to loop through PRQueues.
#
# Each element returned is a dictionary containing:
#
# * 'name': Repository name.
# * 'prs': PRQueue class.
class QueuesIterator:
    def __init__(self, queues):
        self.queues = queues
        self.current = 0
        self.keys = list(self.queues.keys())

    def __next__(self):
        if self.current >= len(self.keys):
            raise StopIteration
        self.current += 1
        key = self.keys[self.current - 1]
        return {'name': key, 'prs': self.queues[key]}


def repo_name_checker(func):
    def wrapper(*args, **kwargs):
        tmp = args[1]
        if args[1].__class__.__name__ != 'str':
            tmp = args[1].get_target_repo().get_name()
        if tmp not in args[0].repos:
            return None
        return func(*args, **kwargs)
    return wrapper


# Global class. (refer to the scheme in QueueRepository to understand its
# position)
#
# This class should be instantiated *once* and ONLY ONCE. It contains all
# queues and needed stuff to run Ultron.
class Queues:
    def __init__(self, org, repo_list, workflows):
        self.repos = {}
        self.org = org
        self.workflows = workflows
        get_all_prs(self.repos, repo_list, workflows)

    def __iter__(self):
        return QueuesIterator(self.repos)

    @repo_name_checker
    def get_pr(self, repo_name, pr_number):
        return self.repos[repo_name].get_pr(pr_number)

    @repo_name_checker
    def get_pr_from_head_commit(self, repo_name, head_commit):
        return self.repos[repo_name].get_pr_from_head_commit(head_commit)

    @repo_name_checker
    def get_queue(self, repo_name):
        return self.repos[repo_name].q

    @repo_name_checker
    def parse_comment(self, repo_name, poster, pr_number, comment):
        self.repos[repo_name].parse_comment(pr_number, poster, comment)

    @repo_name_checker
    def add_pr(self, pr):
        return self.repos[pr.get_target_repo().get_name()].add_pr(
            PRQueueItem(0, [], "", pr))

    @repo_name_checker
    def remove_closed(self, repo_name, pr_number):
        return self.repos[repo_name].remove_closed(pr_number)

    @repo_name_checker
    def update_pr(self, repo_name, pr_number, title, target_branch,
                  old_target_branch, default_branch, number_of_commits):
        return self.repos[repo_name].update_pr(pr_number,
                                               title,
                                               target_branch,
                                               old_target_branch,
                                               default_branch,
                                               number_of_commits)

    @repo_name_checker
    def get_workflow(self, repo_name):
        return self.repos[repo_name].workflow

    def update_workflows(self, workflows):
        if workflows is None:
            return
        self.workflows = workflows
        not_updated = self.repos
        updated = {}

        for workflow in workflows:
            for repo_name in workflow.get_repos_name():
                repo_workflow = workflow.get_repo(repo_name)
                repo = not_updated.get(repo_name, None)
                if repo is None:
                    try:
                        repo = core.GITHUB.get_repo(repo_name, self.org)
                    except Exception:
                        core.LOGS.error('Repository "{}" doesn\'t exist in '
                                        '"{}" organization.'
                                        .format(repo_name, self.org))
                        continue
                    if get_prs(repo, updated,
                               core.DB.get_pending_prs(repo.name),
                               repo_workflow):
                        core.LOGS.info('Repository "{}" is now being watched.'
                                       .format(repo_name))
                else:
                    repo.set_workflow(repo_workflow)
                    updated[repo_name] = repo
                    del not_updated[repo_name]
                    core.LOGS.info('Authorizations of repository "{}" have '
                                   'been updated.'.format(repo_name))
        for repo_name in not_updated:
            core.LOGS.info('Repository "{}" isn\'t watched anymore.'
                           .format(repo_name))
        self.repos = updated

    def update_all_to_pending(self):
        for value in self.repos.values():
            value.update_next_to_pending()


# For test only. It's cute and stuff. Don't mind it.
class TestQueues:
    def __init__(self, repos):
        self.repos = repos

    def __iter__(self):
        return QueuesIterator(self.repos)


# Called by Queues class at its initialization.
def get_all_prs(repos, repo_list, workflows):
    for repo in repo_list:
        for workflow in workflows:
            repo_workflow = workflow.get_repo(repo.name)
            if repo_workflow is None:
                # Since no rights have been set for this repo, we skip it.
                continue
            get_prs(repo, repos, core.DB.get_pending_prs(repo.name),
                    repo_workflow)
    core.COMMENT_QUEUE.empty()


def update_status(pendings, pr, q, repo):
    p = pendings[pr.number]
    # No need to parse comments.
    q_pr = PRQueueItem(p['priority'], [], const.PENDING, pr,
                       p['ci_url'], json.loads(p['env_args']), sha=p['sha'])
    ci_status = ci.get_ci_status(repo.name, repo.owner, q_pr.ci_url)
    res = False
    if ci_status == 'success':
        # If CI build succeeded, we merge it (since it's still open).
        res = utils.merge_pr(q_pr)[0]
        if res is False:
            q_pr.update_status(const.NOT_MERGEABLE)
    if res is False:
        q.add_pr(q_pr)
    del pendings[pr.number]


# Called by get_all_prs.
def get_prs(repo, repos, pendings, workflow):
    try:
        core.LOGS.info("-> Getting PRs from {}".format(repo.name))
        q = PRQueue()
        pr_list = repo.get_pulls()
        for pr in pr_list:
            if pr.number in pendings:
                update_status(pendings, pr, q, repo)
                continue
            q_pr = PRQueueItem(0, [], "", pr)
            q.add_pr(q_pr)
            try:
                parse_comments(q, pr, q_pr, workflow)
            except Exception as e:
                core.LOGS.error('get_prs loop error: {}'.format(e), e)
                continue
        repos[repo.name] = QueueRepository(repo, q, workflow)
        # The remaining pendings haven't been found. The PR has been closed or
        # merged. Either way, we don't care, let's remove them from the db.
        for key in pendings.keys():
            core.DB.delete_pending_pr(repo.name, key)
        return True
    except Exception as e:
        core.LOGS.error('get_prs error: {}'.format(e), e)
    return False


# Light version of PRQueueItem.parse_comment.
#
# Some arguments/actions aren't executed (wouldn't make sense to run
# r+/r-/r=/try multiple times, right?).
def parse_comments(q, pr, q_pr, workflow):
    change = {'last': '', 'prs_to_check': []}
    for comment in pr.get_comments():
        if comment.author != core.USERNAME:
            q.parse_comment(comment.author, q_pr, comment.message,
                            workflow, last_r=change)
    if len(change['last']) != 0 and change['last'] != 'r-':
        if change['last'] == 'r+':
            # If last r+/r- command is r+, we need to set the PR as approved.
            q.update_status(q_pr, const.APPROVED)
        else:
            # We need to check if the hash is in the PR history and then set
            # approved status if it's ok.
            parse._parse_r_equal(['r', change['last']], q_pr, q, None)
    # To avoid checking every after url during startup, we only check last
    # ones.
    if len(change['prs_to_check']) > 0:
        check_after_urls(change['prs_to_check'], q_pr)
    # Would be problematic if all ultron's messages end up being sent now.
    core.COMMENT_QUEUE.empty()
