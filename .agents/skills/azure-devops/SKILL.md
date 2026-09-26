---
name: azure-devops
description: Use Azure CLI with the azure-devops extension to check Azure DevOps access, create a repository in an existing project, push a local Git codebase to Azure Repos, and create or update board work items that track the implementation plan.
---

# Azure DevOps

Use direct `az devops`, `az repos`, `az boards`, and Git commands. This skill covers repository bootstrap and board work items in Azure DevOps Services; it does not provision Azure resources, projects, pipelines, or permissions.

## Discover and authenticate

1. Inspect `az version`, `az extension list`, and `az devops configure --list`. If the extension is missing, install it with `az extension add --name azure-devops` when needed for the authorized task.
2. Inspect `git status --short`, `git remote -v`, and `git branch --show-current`. Check whether HEAD exists with `git rev-parse --verify HEAD`; a newly initialized repository needs a first commit before it can be pushed.
3. Resolve the organization URL, existing project, and repository name from the request or established task context. CLI defaults are discovery hints, not proof of the intended destination. Ask for a destination when it is ambiguous, and continue independent local preparation.
4. Verify actual service access with `az devops project list --organization $organization -o json` or `az devops project show --organization $organization --project $project -o json`. `az account show` alone does not prove Azure DevOps authorization.

Use the existing authenticated session first. If authentication fails, use interactive `az login` for the appropriate account; tenant-only accounts may need `--allow-no-subscriptions`. PAT authentication through `az devops login --organization $organization` is an alternative when required. Have the user enter credentials through the sign-in flow or local credential prompt, never in chat, repository files, remote URLs, or logged command arguments. Do not print tokens or enable debug logging around authentication.

## Create and push

The following PowerShell examples assume `$organization`, `$project`, `$repositoryName`, and `$branch` have been resolved for the task. Check each command's exit status before dependent operations.

1. Inspect existing repositories with explicit scope:

   ```powershell
   az repos list --organization $organization --project $project --detect false -o json
   ```

   A matching name is not permission to overwrite an existing repository. Inspect it and resolve whether to reuse it or choose a new name. After an uncertain create result, query again before retrying.

2. Create the authorized repository and retain its returned ID and `remoteUrl`:

   ```powershell
   az repos create --organization $organization --project $project --name $repositoryName --detect false -o json
   ```

   `TF401027` naming `CreateRepository` means the authenticated identity lacks that project permission. Read access does not imply create access. Stop creation retries and report the identity and project; a project administrator must grant permission or create the requested repository. A later push may separately require repository contribution permission.

3. Review the files and ignore rules before staging. Exclude credentials, local configuration, dependencies, and build output. For a repository without commits, stage the reviewed codebase and create an initial commit using the configured Git identity. For an existing repository, include only changes within the requested scope. Inspect `git diff --cached --stat` and `git diff --cached --check` before committing.
4. Add the returned URL as a remote. Preserve existing remotes; use an unused name such as `azure` when `origin` already points elsewhere. Inspect any existing remote with that name before reusing it. Do not embed credentials in the URL.
5. Use Git Credential Manager or the existing Git authentication setup. Azure CLI authentication and Git authentication are separate; a successful `az repos create` does not guarantee that Git can push. If Git requires interactive sign-in, let the user complete that flow.
6. Inspect `git ls-remote $remoteName` before pushing. If remote history exists, inspect it and reconcile with the requested scope; do not force-push or use `--mirror` for bootstrap. Push the intended branch explicitly:

   ```powershell
   git push --set-upstream $remoteName $branch
   ```

   Do not push other branches or tags unless requested. If branch policy blocks the push, follow the required branch/PR workflow instead of bypassing policy.

## Verify completion

Compare `git rev-parse HEAD` with `git ls-remote $remoteName "refs/heads/$branch"`. Verify the repository through `az repos show --organization $organization --project $project --repository $repositoryId --detect false -o json`, including its default branch. If the new repository needs its default set to the pushed branch, use `az repos update --organization $organization --project $project --repository $repositoryId --default-branch "refs/heads/$branch" --detect false`.

Report the repository link, branch, pushed commit, and any remaining local changes. If creation succeeded but push failed, report the existing repository and exact remaining blocker; resume against that repository instead of creating another or deleting it automatically.

## Board work items

Project phases are tracked as work items; the mapping between plan documents and work items (IDs, states, tags) is defined by the project's implementation plan, which is the source of truth. Update the work item in the same change that updates the plan.

- Inspect before changing: `az boards work-item show --organization $organization --id $id --expand relations -o json`.
- Change state or simple fields: `az boards work-item update --organization $organization --id $id --state Active -o none`. Valid states depend on the project's process (Agile: New, Active, Resolved, Closed); check `az devops project show` for the process.
- Set HTML fields such as `System.Description` through the REST API with a JSON patch file, not as a command-line argument: on Windows, `az` runs through `az.cmd`, and cmd.exe mangles `<`, `>`, and `&` in arguments.

  ```powershell
  az devops invoke --organization $organization --area wit --resource workItems `
    --route-parameters id=$id --http-method PATCH `
    --media-type application/json-patch+json --api-version 7.1 --in-file patch.json
  ```

  where `patch.json` is `[{"op": "add", "path": "/fields/System.Description", "value": "<p>...</p>"}]`. Creating an item uses the same call with `--http-method POST` and `--route-parameters project=$project type=$workItemType`.
- Link dependencies with `az boards work-item relation add --id $successor --relation-type Predecessor --target-id $predecessor`, and parents with `--relation-type Parent`.
- Before creating items, query for existing ones (e.g. by tag with WIQL through `az boards query`) so a rerun never creates duplicates.

## References

Consult installed command help for syntax and current Microsoft documentation when troubleshooting:

- [Azure DevOps CLI](https://learn.microsoft.com/en-us/azure/devops/cli/)
- [Repository commands](https://learn.microsoft.com/en-us/cli/azure/repos?view=azure-cli-latest)
- [CLI authentication](https://learn.microsoft.com/en-us/azure/devops/cli/log-in-via-pat?view=azure-devops)
- [Git authentication](https://learn.microsoft.com/en-us/azure/devops/repos/git/auth-overview?view=azure-devops)
