# Contributing to ubuntu-drivers

ubuntu-drivers' source of truth is https://github.com/canonical/ubuntu-drivers-common.

## Issues

Please open issues at https://github.com/canonical/ubuntu-drivers-common/issues if you encounter
a bug.

## Pull requests

If you have a fix proposal for a bug that impacts a released version of ubuntu-drivers, please file a bug in
Launchpad (via https://launchpad.net/ubuntu/+source/ubuntu-drivers-common) with info on which Ubuntu
releases are known to be impacted.

Additionally, please submit pull requests via the GitHub repository (https://github.com/canonical/ubuntu-drivers-common/pulls).
If you're fixing an issue impacting all Ubuntu releases, target your PR into master.

If your issue is already fixed in the latest devel Ubuntu release, or in ubuntu-drivers-common master, please
cherry-pick the relevant patches into a branch based on that release's branch in the GitHub repo,
then submit the PR into that release's GH repo branch. (Additionally, please prepare an SRU bug
as described in the Ubuntu Project Docs - https://ubuntu.com/project/docs/SRU/reference/bug-template/)

## Note for maintainers

Please squash all PRs before merging. This will keep the source history cleaner and make cherry-picking into SRUs easier.
