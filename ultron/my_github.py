import json
# pip3 install grequests
import grequests
# pip3 install requests
import requests

from ultron import const
from ultron import core


def get_page_number(url):
    parts = url.split('?')[-1].split('&')
    for part in parts:
        if part.startswith('page='):
            try:
                return int(part.split('=')[-1])
            except Exception:
                return 1
    return 1


# To have a better understanding of how this function works:
# https://developer.github.com/guides/traversing-with-pagination/
def get_next_pages_url(link):
    parts = link.split(',')
    subs = [part.split(';') for part in parts]
    next_page_url = ''
    last_page_url = ''
    for sub in subs:
        if len(sub) != 2:
            continue
        if sub[1].endswith('"next"'):
            next_page_url = sub[0][1:-1]
        elif sub[1].endswith('"last"'):
            last_page_url = sub[0][1:-1]
    return next_page_url, last_page_url


def create_headers(token):
    headers = {
        'User-Agent': core.USERNAME,
        'Accept': 'application/vnd.github.v3+json',
    }
    if token is not None:
        # Authentication to github.
        headers['Authorization'] = 'token {}'.format(token)
    return headers


def check_res(res):
    if res.status_code != 200:
        if res.status_code == 403:
            # We reached the rate limit.
            if ('X-RateLimit-Limit' in res.headers and
                    'X-RateLimit-Remaining' in res.headers and
                    'X-RateLimit-Reset' in res.headers):
                raise Exception("Github rate limit exceeded...\n"
                                "X-RateLimit-Limit: {}\n"
                                "X-RateLimit-Remaining: {}\n"
                                "X-RateLimit-Reset: {}".format(
                                 res.headers['X-RateLimit-Limit'],
                                 res.headers['X-RateLimit-Remaining'],
                                 res.headers['X-RateLimit-Reset']))
        raise Exception("Get request failed, got: [{}]: {}".format(
                        res.status_code, str(res.content)))


# This function tries to get as much github data as possible by running
# "parallel" requests.
def get_all_contents(url, token=None, header_extras={}):
    if 'per_page=' not in url:
        if '?' not in url:
            url += '?per_page=100'
        else:
            url += '&per_page=100'
    headers = create_headers(token)
    for extra in header_extras:
        headers[extra] = header_extras[extra]
    res = requests.get(url, headers=headers)
    check_res(res)
    content = res.json()
    if 'Link' not in res.headers:
        # If there are no other pages, we can return the current content.
        return content
    # There are other pages we need to get. To do it faster, we run "parallel"
    # requests.
    link = res.headers.get('Link', '')
    if link is None or len(link) < 1:
        return content

    next_page_url, last_page_url = get_next_pages_url(link)
    # 19 is a number which matches the length of "https://github.com/"
    if len(last_page_url) < 19 or len(next_page_url) < 19:
        return content
    next_page = get_page_number(next_page_url)
    last_page = get_page_number(last_page_url)

    urls = [next_page_url]
    to_replace = "page={}".format(next_page)
    next_page += 1
    while next_page <= last_page:
        urls.append(next_page_url.replace("&{}".format(to_replace),
                                          "&page={}".format(next_page))
                                 .replace("?{}".format(to_replace),
                                          "?page={}".format(next_page)))
        next_page += 1
    rs = (grequests.get(u, headers=headers) for u in urls)
    ret = grequests.map(rs)
    # Once we got all responses, we add them to content and then return it.
    for entry in ret:
        entry.raise_for_status()
        content.extend(entry.json())
    return content


def post_content(url, token, details, method='post', header_extras={}):
    headers = create_headers(token)
    for extra in header_extras:
        headers[extra] = header_extras[extra]
    if method == 'post':
        requests.post(url, data=json.dumps(details),
                      headers=headers).raise_for_status()
    else:
        requests.put(url, data=json.dumps(details),
                     headers=headers).raise_for_status()


# The point of this function is to try to improve a bit the github rate
# limit. Not sure if this is really useful...
def try_without_token(url):
    try:
        return get_all_contents(url)
    except Exception as e:
        if 'Github rate limit exceeded...' not in str(e):
            raise e
    return None


# Global Github class. If you need to make a Github api request, use it or
# one of the classes below.
class Github:
    def __init__(self, token):
        self.token = token

    def get_organization(self, organization_name):
        # get_all_contents raises an Exception if something fails, so no need
        # to check the returned value.
        get_all_contents('{}/orgs/{}'.format(
                         const.GH_API_URL, organization_name),
                         token=self.token)
        return Organization(self, organization_name)

    def get_pull(self, repo_name, repo_owner, html_url, is_private,
                 pull_number):
        return Repository(self, repo_name, repo_owner, html_url,
                          is_private).get_pull(pull_number)

    def create_pull(self, pr):
        target_repo_name = pr['base']['repo']['name']
        target_repo_owner = pr['base']['repo']['owner']['login']
        target_repo_url = pr['base']['repo']['html_url']
        return _create_pull(self, pr, Repository(self,
                                                 target_repo_name,
                                                 target_repo_owner,
                                                 target_repo_url,
                                                 True))

    def get_repo(self, repo_name, repo_owner):
        r = get_all_contents('{}/repos/{}/{}'.format(
                             const.GH_API_URL, repo_owner, repo_name),
                             token=self.token)
        return Repository(self, repo_name, repo_owner, r['html_url'],
                          r["private"])

    def get_repo_branch(self, branch_name, repo_name, repo_owner):
        # get_all_contents raises an Exception if something fails, so no need
        # to check the returned value.
        get_all_contents('{}/repos/{}/{}/branches/{}'
                         .format(const.GH_API_URL, repo_owner, repo_name,
                                 branch_name),
                         token=self.token)
        return Branch(branch_name, repo_name, repo_owner)

    def get_commits_from_pull(self, repo_name, repo_owner, pr_number):
        commits = get_all_contents('{}/repos/{}/{}/pulls'
                                   '/{}/commits'
                                   .format(const.GH_API_URL, repo_owner,
                                           repo_name, pr_number),
                                   token=self.token)
        return [Commit(commit['commit']['author']['name'],
                       commit['commit']['committer']['name'],
                       commit['commit']['message'],
                       commit['sha'])
                for commit in commits]


# Represents a Github organization,
class Organization:
    def __init__(self, gh_object, name):
        self.name = name
        self.gh_object = gh_object

    def get_repos(self):
        repos = get_all_contents('{}/orgs/{}/repos'
                                 .format(const.GH_API_URL, self.name),
                                 token=self.gh_object.token)
        return [Repository(self.gh_object,
                           repo['name'],
                           self.name,
                           repo['html_url'],
                           repo['private']) for repo in repos]

    def get_repo(self, repo_name):
        return core.GITHUB.get_repo(repo_name, self.name)


def _create_pull(gh_object, pr, target_repo):
    nb_commits = None
    if 'commits' in pr:
        try:
            nb_commits = int(pr['commits'])
        except Exception as ex:
            nb_commits = 0
            core.LOGS.error('_create_pull: int("{}") failed'
                            .format(pr['commits']), ex)
    if nb_commits is None:
        nb_commits = len(gh_object.get_commits_from_pull(
            target_repo.get_name(),
            target_repo.get_owner(),
            pr['number']))
    # If some bug occurred while getting commits or converting the string
    # into an integer, we need to set a number high enough.
    if nb_commits < 1:
        nb_commits = 250  # to be sure to include all commits
    return PullRequest(gh_object, target_repo,
                       Repository(gh_object,
                                  pr['head']['repo']['name'],
                                  pr['head']['repo']['owner']['login'],
                                  pr['head']['repo']['html_url'],
                                  target_repo.is_private),
                       pr['number'],
                       pr['base']['ref'],
                       pr['head']['ref'],
                       pr['head']['sha'],
                       pr['title'],
                       pr['user']['login'],
                       pr['mergeable'] if 'mergeable' in pr else 'null',
                       nb_commits,
                       pr['state'] == 'open')


# Represents a Github repository.
class Repository:
    def __init__(self, gh_object, name, owner, html_url, is_private):
        self.name = name
        self.gh_object = gh_object
        self.owner = owner
        self.html_url = html_url
        self.is_private = is_private

    def get_pulls(self):
        prs = None
        if not self.is_private:
            prs = try_without_token('{}/repos/{}/{}/pulls'
                                    .format(const.GH_API_URL, self.owner,
                                            self.name))
        if prs is None:
            prs = get_all_contents('{}/repos/{}/{}/pulls'
                                   .format(const.GH_API_URL, self.owner,
                                           self.name),
                                   token=self.gh_object.token)
        if prs is None:
            return []
        return [_create_pull(self.gh_object, pr, self) for pr in prs]

    def get_pull(self, pull_number):
        pr = None
        if not self.is_private:
            pr = try_without_token('{}/repos/{}/{}/'
                                   'pulls/{}'.format(
                                    const.GH_API_URL, self.owner, self.name,
                                    pull_number))
        if pr is None:
            pr = get_all_contents('{}/repos/{}/{}/pulls/{}'
                                  .format(const.GH_API_URL, self.owner,
                                          self.name, pull_number),
                                  token=self.gh_object.token)
        if pr is None:
            return None
        return _create_pull(self.gh_object, pr, self)

    def get_branch(self, branch_name):
        return core.GITHUB.get_repo_branch(branch_name, self.name, self.owner)

    def get_url(self):
        # return ("{}/{}/{}".format(const.GH_URL, self.owner, self.name))
        return self.html_url

    def get_name(self):
        return self.name

    def get_owner(self):
        return self.owner


# Represents a Github Pull Request.
class PullRequest:
    def __init__(self, gh_object, target_repo, from_repo,
                 pull_number, target_branch, from_branch, head_commit,
                 title, author, mergeable, number_of_commits,
                 is_open=True):
        self.target_repo = target_repo
        self.gh_object = gh_object
        self.number = pull_number
        self.target_branch = target_branch
        self.from_branch = from_branch
        self.head_commit = head_commit
        self.title = title
        self.author = author
        self.is_open = is_open
        self.from_repo = from_repo
        # from github api: 'true'/'false'/'null'
        # 'null' means github hasn't computed it yet
        self.mergeable = mergeable
        self.number_of_commits = number_of_commits

    def get_comments(self):
        comments = get_all_contents(
            '{}/repos/{}/{}/issues/{}/comments'
            .format(const.GH_API_URL, self.target_repo.get_owner(),
                    self.target_repo.get_name(), self.number),
            token=self.gh_object.token)
        return [Comment(comment['user']['login'], comment['body'], self.number)
                for comment in comments]

    # Doesn't create a code comment, so be careful and know the difference!
    def create_issue_comment(self, message):
        post_content('{}/repos/{}/{}/issues/{}/comments'
                     .format(const.GH_API_URL, self.target_repo.get_owner(),
                             self.target_repo.get_name(), self.number),
                     self.gh_object.token, {'body': message})

    def get_url(self):
        return ("{}/{}/{}/pull/{}".format(
                 const.GH_URL, self.target_repo.get_owner(),
                 self.target_repo.get_name(), self.number))

    def get_target_branch_url(self):
        return ("{}/{}/{}/tree/{}".format(
                 const.GH_URL, self.target_repo.get_owner(),
                 self.target_repo.get_name(), self.target_branch))

    def get_repo_url(self):
        return self.target_repo.get_url()

    def get_target_repo(self):
        return self.target_repo

    def get_from_repo_url(self):
        return self.from_repo.get_url()

    def get_from_repo(self):
        return self.from_repo

    def get_mergeable_status(self):
        return self.mergeable

    def get_reviews(self):
        reviews = get_all_contents(
            '{}/repos/{}/{}/pulls/{}/reviews'
            .format(const.GH_API_URL, self.target_repo.get_owner(),
                    self.target_repo.get_name(), self.number),
            token=self.gh_object.token,
            # TODO: This header should be removed once the github API has been
            #       stabilized!!!
            header_extras={'Accept':
                           'application/vnd.github.black-cat-preview+json'})
        return [Review(review['id'], review['body'], review['state'], self)
                for review in reviews]

    def get_number_of_commits(self):
        return self.number_of_commits


class Branch:
    def __init__(self, name, repo_name, repo_owner):
        self.name = name
        self.repo_name = repo_name
        self.repo_owner = repo_owner


class Commit:
    def __init__(self, author, committer, message, sha):
        self.author = author
        self.committer = committer
        self.message = message
        self.sha = sha


# Represents a Github review.
class Review:
    def __init__(self, _id, body, state, pr):
        self.id = _id
        self.body = body
        self.state = state
        self.pr = pr

    def dismiss(self, dismiss_message):
        post_content('{}/repos/{}/{}/pulls/{}/reviews/{}/dismissals'
                     .format(const.GH_API_URL,
                             self.pr.get_target_repo().get_owner(),
                             self.pr.get_target_repo().get_name(),
                             self.pr.number, self.id),
                     self.pr.gh_object.token, {'message': dismiss_message},
                     method='put',
                     # TODO: This header should be removed once the github API
                     #       has been stabilized!!!
                     header_extras={'Accept':
                                    'application/vnd.github.black-cat-preview'
                                    '+json'})


# A representation of an issue comment.
#
# PS: issue comment != (review comment || code comment)
class Comment:
    def __init__(self, author, message, pr_number):
        self.author = author
        self.message = message
        self.pr_number = pr_number


class User:
    def __init__(self, token, name):
        self.token = token
        self.name = name

    def get_organizations(self):
        orgas = get_all_contents('{}/user/orgs'.format(const.GH_API_URL),
                                 token=self.token)
        return [Organization(self.token, orga['login']) for orga in orgas]
