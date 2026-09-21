"""Small GitHub client. Credentials stay in trusted Actions jobs only."""
import json
import os
import urllib.request


class GitHub:
    def __init__(self):
        self.repo = os.environ["GITHUB_REPOSITORY"]
        self.token = os.environ["GH_TOKEN"]

    def request(self, path, method="GET", data=None):
        req = urllib.request.Request(
            f"https://api.github.com/repos/{self.repo}/{path}",
            data=None if data is None else json.dumps(data).encode(), method=method,
            headers={"Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github+json",
                     "Content-Type": "application/json", "X-GitHub-Api-Version": "2022-11-28"})
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.load(response)

    def pages(self, path, max_pages=20):
        items = []
        for page in range(1, max_pages + 1):
            result = self.request(f"{path}{'&' if '?' in path else '?'}per_page=100&page={page}")
            items.extend(result)
            if len(result) < 100:
                return items
        # Do not silently undercount quota or miss a previous admission.
        raise RuntimeError("GitHub pagination safety limit exceeded; owner review required")
