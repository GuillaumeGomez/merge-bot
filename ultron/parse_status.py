class ParseStatus:
    def __init__(self, success, command="", message=""):
        self.success = success
        self.message = message
        self.answers = []
        self.command = command

    @classmethod
    def from_list(cls, parse_status_list, command=""):
        success = True
        for answer in parse_status_list:
            if answer.success is False:
                success = False
                break
        ret = cls(success, command=command)
        ret.answers = parse_status_list
        return ret

    def has_multiple_answers(self):
        return len(self.answers) != 0

    def is_full_success(self):
        # If success is True, then all commands succeeded. The important method
        # is `is_full_failure` here.
        return self.success is True

    def is_full_failure(self):
        return (self.success is not True
                and (len(self.answers) == 0 or
                     all(ans.is_full_failure() for ans in self.answers)))

    def __str__(self):
        if len(self.answers) == 0:
            return "{}{}{}".format(
                '"{}": '.format(self.command) if len(self.command) > 0 else "",
                "Success" if self.success is True else "Failure",
                ": {}".format(self.message) if len(self.message) > 0 else "")
        # If command is not set, it means it is just a wrapper on multiple
        # commands, otherwise, it's a command with multiple inputs (like
        # after).
        if len(self.command) != 0:
            message = ", ".join([str(answer) for answer in self.answers])
            return '"{}": [{}]'.format(self.command, message)
        return "\n".join([str(answer) for answer in self.answers])
