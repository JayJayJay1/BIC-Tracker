import re


multi_commit_regex = re.compile(
    "There are only 'skip'ped commits left to test.\nThe first bad commit could be any of: *\n((?:[0-9a-f]{40}\n)*)",
    re.MULTILINE)

committext = """There are only 'skip'ped commits left to test.
The first bad commit could be any of:   
b2bec7d8a42a3885d525e821d9354b6b08fd6adf
e7f89001797148e8dc7060c335df2c56e73a8c7a
e9ad2eb3d9ae05471c9b9fafcc0a31d8f565ca5b
f9ce0be71d1fbb038ada15ced83474b0e63f264d
6c996e19949b34d7edebed4f6b0511145c036404
We cannot bisect more!"""

if re.match(multi_commit_regex, committext):
    commits = re.findall(multi_commit_regex, committext)[0].splitlines()
    print("=> multi-done")
    print({"status": "done", "commits": commits, "revisions_left": 0})
else:
    print("NO MATCH")