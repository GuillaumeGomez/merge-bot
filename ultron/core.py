import json
from os import listdir
from os.path import isfile, join
import sys

from ultron import const
from ultron import utils
from ultron.db_interactions import DBInteractions
from ultron.cache import Cache
from ultron.comments import CommentQueue
from ultron.file_watcher import FileWatcher, Ignorer
from ultron.my_logs import Logs
from ultron.queue_mod import Queues
from ultron.scheduler import Scheduler


CIRCLE_TOKEN = ''
GITHUB_TOKEN = ''
USERNAME = ''
ORGANIZATION = ''
CLIENT_ID = ''
CLIENT_SECRET = ''
PORT = None
DB_NAME = 'pendings.db'

GITHUB = None
DB = None
QUEUES = None
LOGS = Logs()
COMMENT_QUEUE = CommentQueue()
FILE_WATCHER = FileWatcher()
SCHEDULER = Scheduler()
CACHE = Cache()
SESSIONS = None


def check_keys(keys, dic, func_name, filename):
    for key in keys:
        if key not in dic:
            LOGS.error('{}() failed: Missing key from "{}": {}'
                       .format(func_name, filename, key))
            return False
    return True


def init_conf(filename):
    try:
        conf = ''
        with open(filename) as fdd:
            conf = json.loads(fdd.read())
            if not check_keys(['citoken', 'hubtoken', 'username',
                               'organization', 'client_id', 'client_secret',
                               'http_port'],
                              conf, 'init_conf', filename):
                return None
    except Exception as ex:
        LOGS.error('init_conf() failed on "{}": {}'.format(filename, ex), ex)
        return None
    return conf


def init_workflow(workflow, file_path, workflow_id):
    # Deferred import due to not cleaned-up circular dependencies
    from ultron.workflow import Workflow

    if not check_keys(['repositories'], workflow,
                      'init_workflow', file_path):
        return None
    if not check_keys(['global_reviewers'], workflow,
                      'init_workflow', file_path):
        return None
    global_reviewers = workflow['global_reviewers']
    if global_reviewers.__class__.__name__ != 'list':
        LOGS.error('init_workflow failed: '
                   '"global_reviewers" should be a list.')
    tester_repository = None
    if 'tester_repository' in workflow:
        tester_repository = workflow['tester_repository']
        tmp = tester_repository.split('/')
        if len(tmp) != 2:
            LOGS.error('init_workflow failed: "tester_repository" should be: '
                       '"owner/repository_name"')
            return None
    else:
        LOGS.info('No "tester_repository" set in workflow "{}"'
                  .format(workflow_id))
    repositories = workflow['repositories']
    if repositories.__class__.__name__ != 'dict':
        LOGS.error('init_workflow failed: "repositories" '
                   'should be a dictionary.')
        return None
    repo_values = []
    for entry in repositories:
        if not check_keys(['reviewers'], repositories[entry],
                          'init_workflow', file_path):
            return None
        reviewers = repositories[entry]['reviewers']
        if reviewers.__class__.__name__ != 'list':
            LOGS.error('init_workflow failed: "reviewers" on '
                       'repository "{}" should be a list.'.format(
                        entry))
            return None
        branch_mapping = {}
        if 'branch_mapping' in repositories[entry]:
            branch_mapping = repositories[entry]['branch_mapping']
            if branch_mapping.__class__.__name__ != 'dict':
                LOGS.error('init_workflow failed: "branch_mapping" on '
                           'repository "{}" should be a dictionary.'.format(
                            entry))
                return None
            # As the feature intended for the branch mapping is only aimed at
            # creating a link between the differently named branches of
            # multiple repositories, we constrain what can be done to something
            # sane:
            # we ensure that there is never twice the same value,
            # and that no value equals any key provided.
            keys = []
            values = []
            for k, v in branch_mapping.items():
                if k in values or v in keys:
                    LOGS.error('init_workflow failed: "branch_mapping" on'
                               ' repository "{}" should not have multiple or'
                               ' circular definitions'.format(entry))
                    return None
                keys.append(k)
                values.append(v)
        else:
            LOGS.info('No "branch_mapping" found for "{}" repository'.format(
                      entry))
        repo_values.append({'branch_mapping': branch_mapping,
                            'reviewers': reviewers,
                            'name': entry})
    return Workflow(repo_values, tester_repository, global_reviewers)


def init_authorizations(file_path):
    try:
        with open(file_path) as fdd:
            authorizations = ""
            try:
                authorizations = json.loads(fdd.read())
            except Exception as e:
                LOGS.error('init_authorizations failed while reading json'
                           ' on "{}": {}'.format(file_path, e), e)
                return None
            if not check_keys(['workflows'], authorizations,
                              'init_authorizations', file_path):
                return None
            if authorizations['workflows'].__class__.__name__ != 'list':
                LOGS.error('init_authorizations failed: "workflows" '
                           'should be a list.')
                return None
            workflows = []
            for (pos, workflow) in enumerate(authorizations['workflows']):
                w = init_workflow(workflow, file_path, pos + 1)
                if w is not None:
                    workflows.append(w)
            return workflows
    except Exception as ex:
        LOGS.error('init_authorizations failed on "{}": {}'
                   .format(file_path, ex), ex)
    return None


def init_db():
    global DB
    try:
        DB = DBInteractions(DB_NAME)
    except Exception as e:
        LOGS.error("init_queue: db's initialization failed: {}".format(e), e)
        return False
    return True


def authorization_file_event(event, file_path):
    if event == const.MODIFIED or event == const.CREATED:
        FILE_WATCHER.add_ignorer(Ignorer(file_path, [const.MODIFIED,
                                                     const.CREATED]))
        workflows = init_authorizations(file_path)
        if workflows is None:
            LOGS.error('/!\\ WARNING /!\\ The new authorizations file is'
                       ' invalid! Nothing will be updated in ultron as long'
                       ' as it\'s running.')
            return
        for workflow in workflows:
            workflow.load(GITHUB_TOKEN)
        QUEUES.update_workflows(workflows)
    else:
        LOGS.info('/!\\ WARNING /!\\ authorizations file has been deleted.'
                  ' Nothing will be updated as long as the file isn\'t '
                  ' recreated.')


def create_new_queue(memconf, repo_list, workflows):
    # Local global GITHUB variable switch, a huge change is required in order
    # to remove this:
    #
    # Create a global class given to the "global" instances. So Queues will
    # have its own instance of it, etc...
    global CIRCLE_TOKEN, GITHUB, GITHUB_TOKEN, ORGANIZATION, USERNAME
    old_GITHUB = GITHUB
    GITHUB = memconf['GITHUB']
    old_CIRCLE_TOKEN = CIRCLE_TOKEN
    CIRCLE_TOKEN = memconf['CIRCLE_TOKEN']
    old_GITHUB_TOKEN = GITHUB_TOKEN
    GITHUB_TOKEN = memconf['GITHUB_TOKEN']
    old_USERNAME = USERNAME
    USERNAME = memconf['USERNAME']
    old_ORGANIZATION = ORGANIZATION

    memconf['QUEUES'] = Queues(memconf['ORGANIZATION'], repo_list, workflows)

    GITHUB = old_GITHUB
    CIRCLE_TOKEN = old_CIRCLE_TOKEN
    GITHUB_TOKEN = old_GITHUB_TOKEN
    USERNAME = old_USERNAME
    ORGANIZATION = old_ORGANIZATION


def load_conf(file_path, workflows=None):
    # Deferred import due to not cleaned-up circular dependencies
    from ultron.my_github import Github

    conf = init_conf(file_path)
    if conf is None:
        LOGS.error('/!\\ WARNING /!\\ The new configuration file is'
                   ' invalid! Nothing will be updated in ultron as long'
                   ' as it\'s running.')
        return
    LOGS.info('The configuration has been updated, updating corresponding'
              ' information...')
    memconf = {
        'CIRCLE_TOKEN': conf['citoken'],
        'GITHUB_TOKEN': conf['hubtoken'],
        'GITHUB': Github(conf['hubtoken']),
        'USERNAME': conf['username'],
        'ORGANIZATION': conf['organization'],
        'QUEUES': QUEUES,
        'CLIENT_ID': conf['client_id'],
        'CLIENT_SECRET': conf['client_secret'],
        'PORT': conf['http_port'],
    }
    if ORGANIZATION != memconf['ORGANIZATION']:
        # OK, here we need to refresh EVERY repository we have. Quite huge.
        try:
            orga = memconf['GITHUB'].get_organization(memconf['ORGANIZATION'])
        except Exception as e:
            LOGS.error('load_conf: organization "{}" not found: '
                       '{}. Stopping organization switch!'
                       .format(memconf['ORGANIZATION'], e), e)
            return None
        try:
            repo_list = orga.get_repos()
            LOGS.info('Switching to organization "{}", loading new'
                      ' repositories...'.format(memconf['ORGANIZATION']))
            create_new_queue(memconf, repo_list, workflows)
        except Exception as e:
            LOGS.error("load_conf: couldn't get repositories of "
                       "'{}' organization: {}. Stopping organization "
                       "switch!".format(memconf['ORGANIZATION'], e), e)
            return None
    return memconf


def swap_conf(memconf):
    if memconf is None:
        return False
    global CIRCLE_TOKEN, GITHUB, GITHUB_TOKEN, ORGANIZATION, USERNAME, QUEUES
    global CLIENT_ID, CLIENT_SECRET, PORT
    try:
        if PORT is None:
            # Once the port is set, it cannot be changed
            PORT = int(memconf['PORT'])
    except Exception:
        LOGS.error('swap_conf: invalid value given to "http_port": should be '
                   'an integer.')
        return False
    CIRCLE_TOKEN = memconf['CIRCLE_TOKEN']
    GITHUB_TOKEN = memconf['GITHUB_TOKEN']
    GITHUB = memconf['GITHUB']
    USERNAME = memconf['USERNAME']
    CLIENT_ID = memconf['CLIENT_ID']
    CLIENT_SECRET = memconf['CLIENT_SECRET']
    ORGANIZATION = memconf['ORGANIZATION']
    QUEUES = memconf['QUEUES']
    QUEUES.update_all_to_pending()
    COMMENT_QUEUE.flush()
    LOGS.info('Configuration information updated.')
    return True


def config_file_event(event, file_path):
    if event == const.MODIFIED or event == const.CREATED:
        FILE_WATCHER.add_ignorer(Ignorer(file_path, [const.MODIFIED,
                                                     const.CREATED]))
        swap_conf(load_conf(file_path))
    else:
        LOGS.info('/!\\ WARNING /!\\ configuration file has been deleted.'
                  ' Nothing will be updated as long as the file isn\'t '
                  ' recreated.')


# This function initialises the cache for the "web part" of Ultron. So all
# CSS, HTML and JS files.
def init_cache():
    for file_entry in [f for f in listdir("html")
                       if isfile(join("html", f))]:
        file_path = join("html", file_entry)
        if not CACHE.add_file(file_path):
            LOGS.error('Couldn\'t add "{}" to cache. Aborting...'
                       .format(file_path))
            return False
    for file_entry in [f for f in listdir("css")
                       if f.endswith(".css") and isfile(join("css", f))]:
        file_path = join("css", file_entry)
        if not CACHE.add_file(file_path):
            LOGS.error('Couldn\'t add "{}" to cache. Aborting...'
                       .format(file_path))
            return False
    CACHE.add_file('README.md', utils.markdown_converter)
    return True


def init():
    # Deferred imports due to not cleaned-up circular dependencies
    from ultron.session import Sessions

    global FILE_WATCHER, ORGANIZATION, SESSIONS
    if len(sys.argv) > 1 and '--test' in sys.argv:
        test()
        return
    if not init_db():
        sys.exit(1)
    workflows = init_authorizations(const.AUTHORIZATION_CONF)
    if workflows is None:
        sys.exit(2)
    # Also initializes the queue (since it's tightly related to GH org/tok)
    if not swap_conf(load_conf(const.CONFIG_FILE, workflows)):
        sys.exit(3)
    for workflow in workflows:
        workflow.load(GITHUB_TOKEN)
    if not init_cache():
        sys.exit(4)
    FILE_WATCHER.watch(const.CONFIG_FILE, config_file_event)
    FILE_WATCHER.watch(const.AUTHORIZATION_CONF, authorization_file_event)
    # Starting web sessions.
    SESSIONS = Sessions()


# For test purpose only. You can use it by starting ultron with '--test'
# argument.
def test():
    from queue_mod import PRQueue, PRQueueItem, QueueRepository
    from queue_mod import TestQueues
    from my_github import PullRequest, Repository

    global DB
    global DB_NAME
    global QUEUES

    init()

    DB_NAME = 'test.db'
    DB = DBInteractions(DB_NAME)
    repos = {}
    q = PRQueue()
    q.add_pr(
        PRQueueItem(0, [], "",
                    PullRequest(GITHUB_TOKEN, 'MetaData', 'orga',
                                'http://github.com/none',
                                667, "rel/6.2", "not-rel/6.2",
                                "6d39897b3586d9aa6a10ae27e1c38ec000204d59",
                                'FT: Fix crypto encoding',
                                'someone1', True)))
    q.add_pr(
        PRQueueItem(0, [], "",
                    PullRequest(GITHUB_TOKEN, 'MetaData', 'orga',
                                'http://github.com/none',
                                672, "rel/1.1", "not-rel/1.1",
                                "ed33fa1d4f9482f422dbd2fca074eb600c1bec2b",
                                'Fix size of serialized catchup messages',
                                'someone2', True)))
    q.add_pr(
        PRQueueItem(0, [], "",
                    PullRequest(GITHUB_TOKEN, 'MetaData', 'orga',
                                'http://github.com/none',
                                673, "rel/1.1", "not-rel/1.1",
                                "f381d793e0d1328aef26436825566464348b9c59",
                                'Fwdport',
                                "someone3", True)))
    q.add_pr(
        PRQueueItem(0, [], "",
                    PullRequest(GITHUB_TOKEN, 'MetaData', 'orga',
                                'http://github.com/none',
                                665, "master", "not-master",
                                "80f31ec724bf2adc80361200fc6e39692e18cddc",
                                'WIP seperate DBManager and fix too much '
                                'opened DB',
                                "someone3", True)))
    repos['MetaData'] = QueueRepository(
        Repository(GITHUB_TOKEN, 'MetaData', 'orga',
                   'https://github.com/orga/MetaData',
                   False), q)
    q = PRQueue()
    q.add_pr(
        PRQueueItem(0, [], "",
                    PullRequest(GITHUB_TOKEN, 'Federation', 'orga',
                                'http://github.com/none',
                                611, "rel/1.1", "not-rel/1.1",
                                "fee27f75df99798b8f4440d17db1584c06c52f35",
                                'Backport #610 and #573 to rel/1.1',
                                "someone1", True)))
    q.add_pr(
        PRQueueItem(0, [], "",
                    PullRequest(GITHUB_TOKEN, 'Federation', 'orga',
                                'http://github.com/none',
                                610, "master", "not-master"
                                "95937d1b254184c4104dbc61979c33dd015fc69b",
                                'Lower filebeat force-close delay to 5m',
                                "someone1", True)))
    q.add_pr(
        PRQueueItem(0, [], "",
                    PullRequest(GITHUB_TOKEN, 'Federation', 'orga',
                                'http://github.com/none',
                                607, "master", "not-master",
                                "84ec78743b08227d03a26228edfcfa9c63ee4743",
                                'build logger and cosbench with remote '
                                'builder(s)',
                                "someone2", True)))
    q.add_pr(
        PRQueueItem(0, [], "",
                    PullRequest(GITHUB_TOKEN, 'Federation', 'orga',
                                'http://github.com/none',
                                580, "master", "not-master",
                                "a48ccfc445aa405cf1c8eb3754d01088f916fd07",
                                'fix bucketd port config in s3',
                                "someone3", True)))
    q.add_pr(
        PRQueueItem(0, [], "",
                    PullRequest(GITHUB_TOKEN, 'Federation', 'orga',
                                'http://github.com/none',
                                570, "master", "not-master",
                                "e739bc2a9f953e9d06b4df4d925c11b1ef355f27",
                                'Ft/autonomous bucketd',
                                "someone1", True)))
    repos['Federation'] = QueueRepository(
        Repository(GITHUB_TOKEN, 'Federation', 'orga',
                   'https://github.com/orga/Federation',
                   False), q)
    q = PRQueue()
    q.add_pr(
        PRQueueItem(0, [], const.FAILED,
                    PullRequest(GITHUB_TOKEN, 'Integration', 'orga',
                                'http://github.com/none',
                                227, "master", "not-master",
                                "f655dd75b45d0c941d43101c849e3d29b7807483",
                                'Wait for the same number of bucketd as '
                                's3',
                                "someone1", True)))
    q.add_pr(
        PRQueueItem(0, [], const.FAILED,
                    PullRequest(GITHUB_TOKEN, 'Integration', 'orga',
                                'http://github.com/none',
                                226, "rel/6.2", "not-rel/6.2",
                                "9b7ca47db21924c71b45f8980b524bce0a0e95e4",
                                'add timeRange tests',
                                "someone2", True)))
    q.add_pr(
        PRQueueItem(0, [], const.FAILED,
                    PullRequest(GITHUB_TOKEN, 'Integration', 'orga',
                                'http://github.com/none',
                                225, "master", "not-master",
                                "27e3acb1251cd7056bc75435b6b18b234b440316",
                                'FT: Update node minor',
                                "someone3", True)))
    q.add_pr(
        PRQueueItem(0, [], const.FAILED,
                    PullRequest(GITHUB_TOKEN, 'Integration', 'orga',
                                'http://github.com/none',
                                212, "master", "not-master",
                                "8a9522f12557be2418cdd1738d10b00aaf16854b",
                                'Add fog tests',
                                "someone4", True)))
    q.add_pr(
        PRQueueItem(0, [], const.FAILED,
                    PullRequest(GITHUB_TOKEN, 'Integration', 'orga',
                                'http://github.com/none',
                                158, "master", "not-master",
                                "03fbee0589a510594754e6b2d940d7ff8dc69afe",
                                'Ft/failure tests',
                                "someone5", True)))
    repos['Integration'] = QueueRepository(
        Repository(GITHUB_TOKEN, 'Integration', 'orga',
                   'https://github.com/orga/Integration',
                   False), q)
    q = PRQueue()
    q.add_pr(
        PRQueueItem(0, [], "",
                    PullRequest(GITHUB_TOKEN, 'S3', 'orga',
                                'http://github.com/none',
                                244, "master", "not-master",
                                "92271a7308539886b18d1bed9a721d1bf52e9956",
                                'Performance measurement',
                                "someone1", True)))
    q.add_pr(
        PRQueueItem(0, [], "",
                    PullRequest(GITHUB_TOKEN, 'S3', 'orga',
                                'http://github.com/none',
                                243, "master", "not-master"
                                "d44537dfc3e6d81b983e3f555ec5e57f10cb24e7",
                                'Thinning down docker image',
                                "someone2", True)))
    q.add_pr(
        PRQueueItem(0, [], "",
                    PullRequest(GITHUB_TOKEN, 'S3', 'orga',
                                'http://github.com/none',
                                242, "ft/ec_uks_repair_dp_freeTopo",
                                "not-ft/ec_uks_repair_dp_freeTopo",
                                "0b92e05e38e644d0dbd89024d49b8b44b01d00dd",
                                'Data placement with multiple data '
                                'backends',
                                "someone1", True)))
    q.add_pr(
        PRQueueItem(0, [], const.FAILED,
                    PullRequest(GITHUB_TOKEN, 'S3', 'orga',
                                'http://github.com/none',
                                238, "master", "not-master",
                                "99809ac74168622cb2e94f5ab44474c1feb6ade1",
                                'FT: Fix crypto encodingr',
                                "someone3", True)))
    q.add_pr(
        PRQueueItem(0, [], const.FAILED,
                    PullRequest(GITHUB_TOKEN, 'S3', 'orga',
                                'http://github.com/none',
                                229, "ft/ec_uks_repair_dp",
                                "not-ft/ec_uks_repair_dp",
                                "4bc31ae8dc57f4c848cbcc8b5ab89ea3b5decb60",
                                'Simplify topology dependency',
                                "someone1", True)))
    repos['S3'] = QueueRepository(Repository(GITHUB_TOKEN, 'S3', 'orga',
                                             'https://github.com/orga/S3',
                                             False), q)
    QUEUES = TestQueues(repos)
