class CommentDescription:
    def __init__(self, message, pr):
        self.message = message
        self.pr = pr


# In this class, comment parameters are always CommentDescription class!
#
# The main point of this class is to create a message queue which we can empty
# or flush depending of our needs. For example, at the initialization step, we
# clearly don't want to post messages for every command we parsed for every PR
# on every repository.
class CommentQueue:
    def __init__(self):
        # list of CommentDescription
        self.comments = []

    def prepend(self, comment):
        self.comments.insert(0, comment)

    def append(self, comment):
        self.comments.append(comment)

    def flush(self):
        for comment in self.comments:
            self.create_comment(comment)
        self.empty()

    def empty(self):
        self.comments = []

    # Utility to directly send a comment. Avoid using it directly if possible.
    # Can be useful in case of comments that have to be posted, whatever the
    # context.
    def create_comment(self, comment):
        comment.pr.create_issue_comment(comment.message)
