# Design

Idempotent application of various packages of GitHub configuration.

Should support a dry-run mode, which measures deviations from the configuration, and an execution mode, which reruns the dry-run afterwards to ensure their expectations are in sync.

Intended to be run manually, from a shell with `gh` authenticated. (Or another authentication mechanism, if there's something that can't do.)

## Operations

### quality-of-life

Sets the option for automatically deleting head branches when a PR is merged. (Will set other options I always want, as and when I remember what they are.)

### branch-protection

Installs a branch protection rule on the default branch that requires pull requests but can be overridden by repo admins.

If the default branch already has rules:
* if it has more than 1 rule, abort,
* if it has 1 rule, dry-run should diff it against the proposed rule.

### claude-setup

1. Runs the `branch-protection` rule.
2. Adds the given repo to the list of selected repositories for the installation of https://github.com/settings/apps/bmillwood-claude on my (bmillwood) user account.

### renovate-setup

I'll get to this later.

# Implementation

By default I'd go to Python, packaged with uv (if it needs or wants external dependencies at all). But another language could win me over if it were more aggressively statically typed than Python and not much less ergonomic for this kind of application, or if there were something else cool and interesting about it.
