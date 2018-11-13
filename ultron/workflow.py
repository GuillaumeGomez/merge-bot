from ultron import const
from ultron.my_github import Github
from ultron.utils import compute_repo_envvar


class RepositoryWorkflow:
    def __init__(self, reviewers, branch_mappings, workflow):
        self.workflow = workflow
        # This list corresponds to the users who have the rights to call some
        # specific commands like 'r+', 'r-' or 'clean' or any command modifying
        # the current status of the pull request in the queue.
        #
        # /!\ WARNING: if this list is empty, every users can do any command!
        self.reviewers = [r.lower() for r in reviewers]
        self.mapping = branch_mappings
        self.reverse_mapping = {v: k for k, v in self.mapping.items()}

    def has_permission(self, user):
        if len(self.reviewers) == 0:
            # If no authorized user is set, all users have all permissions.
            return True
        user = user.lower()
        # Check first for global reviewers.
        if self.workflow.has_permission(user) is True:
            return True
        # Then check for "local" reviewers.
        return user in self.reviewers

    def get_id(self):
        return self.workflow.gh_id

    def check_permission_second_level(self, user, pull):
        return (self.has_permission(user) is True or
                pull.status == const.APPROVED or
                pull.status == const.PENDING)

    def get_tester_repository(self):
        return self.workflow.get_tester_repository()

    def branch_map(self, branch_name):
        """ Maps a branch name according to the workflow's mappings.
            As this function is intended to be used to map the DEFAULT_BRANCH,
            the default value returned is the unmapped branch_name if no
            mapping could be found.
        """
        return self.mapping.get(branch_name, branch_name)

    def branch_unmap(self, branch_name, default=None):
        """ Maps a branch name according to the workflow's reverse mappings.
            As this function is used in multiple contexts, the returned default
            is configurable and None if not set.
        """
        return self.reverse_mapping.get(branch_name, default)

    def unmap_branches(self, target_branch, parameters):
        """ Thunk function to call up on the complete workflow definition
            This allows us not to expose the "parent" workflow to the user of
            this object
        """
        return self.workflow.unmap_branches(target_branch, parameters)


class Workflow:
    def __init__(self, repos, tester_repo, global_reviewers):
        self.global_reviewers = [r.lower() for r in global_reviewers]
        # If none, then no special tester repo is set and the caller repo
        # should be used.
        self.tester_repo = None
        self.tmp_tester_repo = tester_repo
        self.repositories_workflow = {}
        self.gh_token = None
        for repo in repos:
            self.repositories_workflow[repo['name']] = \
                RepositoryWorkflow(repo['reviewers'],
                                   repo['branch_mapping'],
                                   self)

    def load(self, gh_token):
        self.gh_token = gh_token
        if self.tmp_tester_repo is not None:
            tmp = self.tmp_tester_repo.split('/')
            self.tester_repo = Github(gh_token).get_repo(tmp[1], tmp[0])

    def has_permission(self, user):
        return user in self.global_reviewers

    def get_repo(self, repo_name):
        return self.repositories_workflow.get(repo_name, None)

    def update_gh_id(self, new_gh_token):
        self.gh_token = new_gh_token

    def get_repos_name(self):
        return self.repositories_workflow.keys()

    def get_tester_repository(self):
        return self.tester_repo

    def unmap_branches(self, target_branch, build_parameters):
        """ Returns a dictionary of additional parameters to augment the
            provided build_parameters, to use the proper branches in the build
            for each project providing a mapping toward the target_branch.
        """
        additional_parameters = {}
        for name, wkflow in self.repositories_workflow.items():
            envname = compute_repo_envvar(name)
            if envname in build_parameters:
                # No auto-mapping required if the branch was specified
                continue
            unmapped = wkflow.branch_unmap(target_branch)
            if unmapped is None:
                # Let's not set the envvar if not needed
                continue
            additional_parameters[envname] = unmapped
        return additional_parameters
