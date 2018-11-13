NOT_MERGEABLE = 'not mergeable'
PENDING = 'pending'
FAILED = 'failed'
APPROVED = 'approved'
ROLLUP = 'rollup'

MODIFIED = 0
CREATED = 1
DELETED = 2

CONFIG_FILE = 'config.json'
AUTHORIZATION_CONF = 'repositories.json'
CI_URL = 'http://ci.ironmann.io'
GH_API_URL = 'https://api.github.com'
GH_URL = 'https://github.com'

MAX_LOGS = 500

FORBIDDEN_FILES = [CONFIG_FILE, AUTHORIZATION_CONF, '.py']

ONE_DAY = 60 * 60 * 24
SCHEDULE_DELAY = 60 * 10  # 10 minutes

SCHEDULER_PATH = 'scheduler'
FILE_WATCHER_PATH = 'file_watcher'
