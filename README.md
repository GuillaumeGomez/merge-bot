# How ultron and CI will work (together)

The goal is to remove all unneeded human interactions. Here is how it'll happen:

 * People review a PR and give their approval.
 * Maintainer approves the PR and then Ultron adds it to its queue (commands' syntax for this action -and all others- remain to be written but I propose one below).
 * Ultron tests all PR in its queue, one by one (the order depends on the PR's priority and a few other parameters described below).
 * Once the PR successfully tested, Ultron handles the merge as well and pushes to the corresponding branch (which will close the PR automatically, thanks github!).

## Dependencies

In order to make ultron work normally, you need a GIT version >= 2.0.

## How to handle merging and testing

Before testing a PR, Ultron will rebase it on the targetted branch and then execute a `git merge`. The goal is to keep all commits in one block and also have the "merge commit" (I'll provide useful information in its commit message such as the PR number).

## Queue and PRs' order

Only "approved" PRs have a priority. The default (and minimum) priority value is 0 (no max). The higher the value, the bigger the priority.

You can provide a higher priority to a PR if you want it to get merged more quickly. There is also another parameter to take into account: it is possible to ensure that a PR is tested (and eventually merged) *only after* another one (from the same repository or another). In this case, the priority will be the same from the parent PR (so the one specified by "after").

A last parameter of priority can be set: rollup. This is the lowest priority status (so less than 0). When no other PR is in the queue, then all PRs which has this status will be merged into one and tested at once. Only minor changes PR should be approved with this status!

Ultron will be able to test multiple PRs at a time if they are on different branches.

## Ultron new syntax

 * To approve the PR, the command is `r+`.
 * To remove a PR from the queue, the command is `r-`.
 * To test a PR on the CI, use the `try` command.
 * To set the priority value, the command is `p=[value]` where value is a number or rollup. So if you want to remove a PR from the rollup without removing it from the queue, just set its priority to 0. This is optional.
 * To set the `after` parameter, use the command "after=[url]" where url is the url of the PR you want to be the parent. If you want to unset it, just call this command with nothing after the '=' character (for example: "@ironman-machine: r+ after= p=rollup").
 * You can use `needed_review` command to set a needed number of "approved changes" review before putting automatically the PR into Ultron's queue. It works as follow: "needed_review=[number]" where `number` corresponds to the number of required "approved changes". More information in "Approval system of a PR" part below.
 * If you want some information about the current state of ultron, use the `status` command.
 * If you need to remove "drop me" commits, you can use the `r=[commit_hash]` command. the `commit_hash` given as parameter will be the last commit which will get merged. All commits after this one will be ignored.
 * To clean environment variables and after dependencies, use the `clean` command.
 * To only clean environment variables, use the `clean_env` command.

You can set the commands as follow:

```text
@ironman-machine: p=1 after=https://github.com/orga/Integration/pull/213 r+
```

All commands have to be separated by at least one 'blank' characters (tabulation, whitespace, backline). So the following is also correct:

```text
@ironman-machine: p=1
after=https://github.com/orga/Integration/pull/213
r+
```

After @ironman-machine invocation, no other things than commands should be put! Also:

```text
@ironman-machine: r+
```

Works just fine and is the equivalent of:

```text
@ironman-machine: p=0 after= r+
```

You can invoke a command on its own:

```text
@ironman-machine: p=10
```

However, please take note that if you change a parameter (the priority for example) but the PR isn't the queue, it won't change much (the priority *will* change, but the PR still won't be in the queue).

## Invalid command/command's parameter handling

No error will be output if any invalid command and/or command's parameter is given. They'll just be ignored.

## Approval system of a PR

 * If a maintainer is ok with a PR changes, but wants other reviews before putting the PR into Ultron's queue, the "needed_review" command can (and should!) be used.
 * Set a review counter: let's say we have 3 positive reviews, if there is a "request changes" review, we go back to not-approved and need an update. To put it simply, we just add consider "review approval" as a +1 while considering "request changes" as blocker.

## Potentially useful commands

Here is a list of commands that might be useful but need discussion before going any further in their implementation:

 * force-build: it'll stop any current pending test on the same repository/branch and build this one instead. If this PR has an after parameter set and the targetted PR isn't merged, the command will be ignored.
