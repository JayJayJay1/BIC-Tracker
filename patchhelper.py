#!/usr/bin/env python3
import git
import os

git_repo = "../workspace/linux"
to_patch = "../workspace/linux/kernel/panic.c"
patch_folder = "../workspace/patches"

latest_commit = "a54df7622717a40ddec95fd98086aff8ba7839a6"
# earliest_patchable_commit = "db38d5c106dfdd7cb7207c83267d82fdf4950b61"
earliest_patchable_commit = "c5f4546593e9911800f0926c1090959b58bc5c93"


def main():
    current_patch_file = patch_folder + "/" + latest_commit + ".txt"
    current_patch = latest_commit
    repo = git.Repo(git_repo)
    string_for_go = "]string{ \"" + latest_commit + "\", "

    commits = repo.git.log("--pretty=format:%H", earliest_patchable_commit + ".." + latest_commit, "--", to_patch)
    commits_to_test = commits.splitlines()
    num_patches = 1

    for commit in commits_to_test:
        repo.git.checkout("--force", commit)
        try:
            repo.git.apply("--check", current_patch_file)
            print("\"" + commit + "\":\"" + current_patch + "\",")
        except git.GitCommandError:
            # print("Not applicable for " + commit)
            current_patch_file = patch_folder + "/" + commit + ".txt"
            current_patch = commit
            if not os.path.isfile(current_patch_file):
                print("Patch for " + commit + " missing.")
                return
            repo.git.apply("--check", current_patch_file)
            print("\"" + commit + "\":\"" + current_patch + "\",")
            string_for_go += "\"" + commit + "\", "
            num_patches += 1
    string_for_go = "availablePatchesInOrder := [" + str(num_patches) + string_for_go[:-2] + "}"
    print(string_for_go)


if __name__ == "__main__":
    main()
