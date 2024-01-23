"""
Sync card content from Guru to a GitHub repository.
"""

import base64
import re
import subprocess  # nosec B404
import time
import uuid
from functools import lru_cache
from os import environ, path
from typing import List

import guru
import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter, Retry


class GitHubPublisher(guru.PublisherFolders):
    """
    Publish card content from a Guru collection to a given directory in a GitHub repository.
    """

    def __init__(self, source):
        super().__init__(source)
        if environ.get("PUBLISH_UNVERIFIED_CARDS"):
            self.skip_unverified_cards = False
        if environ.get("DRY_RUN"):
            self.dry_run = True

    def get_headers(self, media_type="application/vnd.github+json"):
        """
        Get the headers for a GitHub API request.
        """
        headers = {
            "Accept": media_type,
            "Authorization": f"Bearer {environ['GITHUB_TOKEN']}",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        return headers

    def generate_external_id(self, guru_id: str, response_json):
        """
        Create an external ID for an external collection, folder, or card.
        """
        external_id = str(uuid.uuid4())
        self._PublisherFolders__update_metadata(guru_id)
        self._PublisherFolders__metadata[guru_id]["external_id"] = external_id
        self.update_external_metadata(guru_id, response_json)
        return external_id

    def get_metadata(self, guru_id: str):
        """
        Get metadata for a Guru card or collection.
        """
        return self._PublisherFolders__metadata.get(guru_id, {})

    def get_guru_id(self, external_id: str):
        """
        Get the Guru ID for a given external ID.
        """
        for guru_id, metadata in self._PublisherFolders__metadata.items():
            if metadata.get("external_id") == external_id:
                return guru_id

    def update_external_metadata(self, guru_id: str, response_json):
        """
        Update external metadata in the GitHubPublisher.json metadata file.
        """
        if not response_json.get("type"):
            response_json = response_json.get("content")

        metadata = self._PublisherFolders__metadata[guru_id]
        metadata["external_name"] = response_json["name"]
        metadata["external_path"] = response_json["path"]
        metadata["external_sha"] = response_json["sha"]
        metadata["external_url"] = response_json["html_url"]

    @lru_cache
    def get_repository_content(self, file_path=""):
        """
        Get the contents of a file or directory in a GitHub repository.
        """
        github_api_url = environ["GITHUB_API_URL"]
        repository = environ["GITHUB_REPOSITORY"]
        url = f"{github_api_url}/repos/{repository}/contents/{file_path}"

        response = requests.get(
            url,
            # Use the `object` media type parameter to retrieve the contents
            # in a consistent object format regardless of the content type
            # https://docs.github.com/en/rest/repos/contents?apiVersion=2022-11-28#custom-media-types-for-repository-contents
            headers=self.get_headers("application/vnd.github.object"),
            timeout=20,
        )

        return response

    def delete_a_file(self, file_path: str, commit_message: str, sha: str):
        """
        Delete a file in a GitHub repository.
        Documentation: https://docs.github.com/rest/repos/contents#delete-a-file
        """
        github_api_url = environ["GITHUB_API_URL"]
        repository = environ["GITHUB_REPOSITORY"]
        url = f"{github_api_url}/repos/{repository}/contents/{file_path}"
        github_ref_name = environ["GITHUB_REF_NAME"]

        data = {
            "message": commit_message,
            "sha": sha
            if not None
            else self.get_repository_content(file_path).json().get("sha"),
            "branch": github_ref_name,
        }

        response = requests.delete(
            url, json=data, headers=self.get_headers(), timeout=20
        )

        if not response.ok:
            print(f"Failed to delete {file_path}")
            print(response.json().get("message"))
            response.raise_for_status()

        # Clear repository content cache
        self.get_repository_content.cache_clear()

        return response

    @lru_cache
    def get_a_tree(self, tree_sha, recursive=False):
        """
        Get a GitHub repository tree by its SHA.
        """
        github_api_url = environ["GITHUB_API_URL"]
        repository = environ["GITHUB_REPOSITORY"]
        query_parameters = "?recursive=1" if recursive else ""
        url = f"{github_api_url}/repos/{repository}/git/trees/{tree_sha}{query_parameters}"

        response = requests.get(url, headers=self.get_headers(), timeout=20)
        results = response.json()

        return results

    def create_a_tree(self, tree: list) -> dict:
        """
        Create a tree in a GitHub repository.
        """
        github_api_url = environ["GITHUB_API_URL"]
        repository = environ["GITHUB_REPOSITORY"]
        url = f"{github_api_url}/repos/{repository}/git/trees"

        data = {
            "tree": tree,
        }

        session = requests.Session()
        retries = Retry(total=10, backoff_factor=1, status_forcelist=[502])
        session.mount("https://", HTTPAdapter(max_retries=retries))

        response = session.post(url, json=data, headers=self.get_headers(), timeout=20)

        if not response.ok:
            print("Failed to create a tree")
            print(response.json().get("message"))
            response.raise_for_status()

        results = response.json()

        return results

    def get_guru_collection_url(self, collection: guru.Collection):
        """
        This builds the URL to a Guru collection.
        """
        return f"https://app.getguru.com/collections/{collection.slug}"

    def slugify(self, string: str) -> str:
        """
        Turns a string into a slug.
        - Convert spaces or repeated dashes to single dashes
        - Remove characters that aren't alphanumerics, underscores, or hyphens
        - Convert to lowercase
        - Strip leading and trailing whitespace, dashes, and underscores
        """
        string = str(string)
        string = re.sub(r"[^\w\s-]", "", string.lower())
        return re.sub(r"[-\s]+", "-", string).strip("-_")

    @lru_cache
    def get_external_collection_path(self, collection: guru.Collection):
        """
        This builds the path to a collection directory in the GitHub repository.
        """
        external_collection_directory_path = environ["COLLECTION_DIRECTORY_PATH"]
        collection_path = (
            f"{external_collection_directory_path}/{collection.name}".rstrip()
        )
        return collection_path

    @lru_cache
    def get_external_folder_path(self, folder: guru.Folder):
        """
        This builds the path for a folder in the GitHub repository.
        """
        # Ensure we have the full folder object
        full_folder: guru.Folder = source.get_folder(folder.id)
        # folder: guru.Folder = guru.Guru.get_folder(folder.id)

        collection_home_folder: guru.Folder = full_folder.get_home()
        collection_path: str = self.get_external_collection_path(full_folder.collection)

        if full_folder.id == collection_home_folder.id:
            return collection_path

        folder_path: str = full_folder.title.rstrip()
        parent_folder: guru.Folder = full_folder.get_parent()

        # Get path by recursively prefixing parent folders to the path
        while parent_folder.id != collection_home_folder.id:
            folder_path = f"{parent_folder.title}/{folder_path.rstrip()}"
            parent_folder = parent_folder.get_parent()

        full_folder_path = f"{collection_path}/{folder_path}"
        return full_folder_path

    @lru_cache
    def get_external_card_path(self, card: guru.Card):
        """
        This builds the path(s) for a card in the GitHub repository.
        Since a card may be in multiple folders, it may have multiple paths.
        """
        folders_for_card = card.folders

        if folders_for_card:
            first_folder = source.get_folder(folders_for_card[0])
            first_folder_path = self.get_external_folder_path(first_folder)
            card_path = f"{first_folder_path}/{self.slugify(card.title)}.md"
        else:
            collection = card.collection
            collection_path = self.get_external_collection_path(collection)
            card_path = f"{collection_path}/{self.slugify(card.title)}.md"

        return card_path

    def create_or_update_file_contents(
        self,
        guru_id: str,
        file_path: str,
        commit_message: str,
        content: str,
        sha="",
    ):
        """
        Create or update a file in a GitHub repository.
        Documentation: https://docs.github.com/rest/repos/contents#create-or-update-file-contents
        """
        github_api_url = environ["GITHUB_API_URL"]
        repository = environ["GITHUB_REPOSITORY"]
        url = f"{github_api_url}/repos/{repository}/contents/{file_path}"
        github_ref_name = environ["GITHUB_REF_NAME"]

        file_exists = self.get_repository_content(file_path).ok
        if file_exists:
            # SHA is required when updating an existing file
            sha = sha or self.get_repository_content(file_path).json().get("sha")

            # Compare the content of the file in the repository to the content
            # we're trying to publish. If they're the same, don't update the file.
            # This prevents unnecessary commits to the repository.
            file_content = self.get_repository_content(file_path).json().get("content")
            file_content = str(base64.b64decode(file_content), "utf-8")
            if file_content == content:
                return self.get_repository_content(file_path)

        data = {
            "message": commit_message,
            "content": str(
                base64.b64encode(content.encode()),
                "utf-8",
            ),
            "sha": sha,
            "branch": github_ref_name,
        }

        response = requests.put(url, json=data, headers=self.get_headers(), timeout=20)

        if not response.ok:
            print("Failed to create or update file contents")
            print(response.json().get("message"))
            response.raise_for_status()

        if response.status_code == 200:  # OK (Updated)
            self.update_external_metadata(guru_id, response.json())
        elif response.status_code == 201:  # Created
            external_id = self.generate_external_id(guru_id, response.json())
            return external_id

        # Clear repository content cache
        self.get_repository_content.cache_clear()

        return response

    def create_a_commit(self, message: str, tree_sha, parents: List[str]) -> dict:
        """
        Create a new Git commit object.
        Documentation: https://docs.github.com/rest/git/commits#create-a-commit
        """
        github_api_url = environ["GITHUB_API_URL"]
        repository = environ["GITHUB_REPOSITORY"]
        url = f"{github_api_url}/repos/{repository}/git/commits"

        data = {
            "message": message,
            "tree": tree_sha,
            "parents": parents,
        }

        response = requests.post(url, json=data, headers=self.get_headers(), timeout=20)

        if not response.ok:
            print("Failed to create a commit")
            print(response.json().get("message"))
            response.raise_for_status()

        results = response.json()

        return results

    def get_a_branch(self, branch):
        """
        Get a Git branch object.
        """
        github_api_url = environ["GITHUB_API_URL"]
        repository = environ["GITHUB_REPOSITORY"]
        url = f"{github_api_url}/repos/{repository}/branches/{branch}"

        response = requests.get(url, headers=self.get_headers(), timeout=20)

        results = response.json()

        return results

    def get_a_commit_sha(self, ref):
        """
        Get a Git commit object.
        """
        github_api_url = environ["GITHUB_API_URL"]
        repository = environ["GITHUB_REPOSITORY"]
        url = f"{github_api_url}/repos/{repository}/commits/{ref}"

        response = requests.get(
            url, headers=self.get_headers("application/vnd.github.sha"), timeout=20
        )

        results = response.text

        return results

    def update_a_reference(self, ref: str, sha):
        """
        Update a Git reference.
        Documentation: https://docs.github.com/rest/git/refs#update-a-reference
        """
        github_api_url = environ["GITHUB_API_URL"]
        repository = environ["GITHUB_REPOSITORY"]
        url = f"{github_api_url}/repos/{repository}/git/{ref}"

        data = {
            "sha": sha,
        }

        response = requests.patch(
            url, json=data, headers=self.get_headers(), timeout=20
        )

        if not response.ok:
            print("Failed to update reference")
            print(response.json().get("message"))
            response.raise_for_status()

        # Clear repository content cache
        self.get_repository_content.cache_clear()

        return response

    def rename_file_or_directory(
        self, guru_id: str, old_path: str, new_path: str, commit_message: str
    ):
        """
        Rename a file or directory in a GitHub repository.
        """
        github_ref = environ["GITHUB_REF"]
        github_ref_name = environ["GITHUB_REF_NAME"]
        latest_commit_sha = self.get_a_branch(github_ref_name).get("commit").get("sha")

        base_tree = self.get_a_tree(latest_commit_sha, recursive=True)
        base_tree_sha = base_tree.get("sha")

        new_tree_structure = [
            {
                "path": item["path"].replace(
                    old_path,
                    new_path,
                ),
                "mode": item["mode"],
                "type": item["type"],
                "sha": item["sha"],
            }
            for item in filter(lambda x: x["type"] == "blob", base_tree["tree"])
        ]

        new_tree = self.create_a_tree(new_tree_structure)
        new_tree_sha = new_tree.get("sha")

        commit_sha = self.create_a_commit(
            commit_message, new_tree_sha, [base_tree_sha]
        ).get("sha")

        update_a_reference_response = self.update_a_reference(github_ref, commit_sha)

        guru_object_type = self.get_type(guru_id)
        if guru_object_type == "collection":
            new_path = f"{new_path}/README.md"

        # Wait a second for the reference to be updated
        time.sleep(1)

        content_response = self.get_repository_content(new_path)
        if not content_response.ok:
            print(f"Failed to get external metadata for renamed {guru_object_type}")
            print(content_response.json().get("message"))
            content_response.raise_for_status()

        self.update_external_metadata(guru_id, content_response.json())

        return update_a_reference_response

    def get_external_url(self, external_id, card: guru.Card):
        """
        This builds the URL for a Markdown file in the GitHub repo. We use this
        to convert links between Guru Cards to be links between Markdown documents.
        """
        if not external_id:
            return None

        external_url = self.get_metadata(card.id)["external_url"]

        return external_url

    def find_external_collection(self, collection: guru.Collection):
        """
        This checks if a collection already exists in GitHub by checking for one
        with the same name. Guru collections are folders in a GitHub repository.
        """
        expected_path = f"{self.get_external_collection_path(collection)}/README.md"
        response = self.get_repository_content(expected_path)

        if response.ok:
            external_id = self.generate_external_id(collection.id, response.json())

            return external_id

    def create_external_collection(self, collection: guru.Collection):
        """
        If a card is in a collection and we can't find a 'collection' with the
        same name in the GitHub repository, we'll call this function to create the
        collection in GitHub. Since Git doesn't track empty directories, we'll create a
        README.md file in the new collection directory with the collection description.
        """
        collection_path = self.get_external_collection_path(collection)

        return self.create_or_update_file_contents(
            collection.id,
            f"{collection_path}/README.md",
            f"Create {collection.name} collection",
            f"# [{collection.name}]({self.get_guru_collection_url(collection)})\n\n{collection.description}",
        )

    def update_external_collection(self, external_id, collection: guru.Collection):
        """
        This is similar to create_external_collection except it's called when
        a Guru collection has already been published (has an external_id).
        """
        collection_metadata = self.get_metadata(collection.id)

        # Use dirname to get the path to the collection directory (exclude README.md)
        old_collection_path = path.dirname(collection_metadata["external_path"])
        new_collection_path = self.get_external_collection_path(collection)

        # Rename the collection directory if the collection name has changed
        if old_collection_path != new_collection_path:
            rename_response = self.rename_file_or_directory(
                collection.id,
                old_collection_path,
                new_collection_path,
                "Rename collection",
            )

            if rename_response.ok:
                # Replace old collection path with new collection path in metadata file
                for _guru_id, metadata in self._PublisherFolders__metadata.items():
                    if metadata.get("external_path"):
                        metadata["external_path"] = metadata["external_path"].replace(
                            f"{old_collection_path}/",
                            f"{new_collection_path}/",
                        )

        return self.create_or_update_file_contents(
            collection.id,
            f"{new_collection_path}/README.md",
            "Update collection details",
            f"# [{collection.name}]({self.get_guru_collection_url(collection)})\n\n{collection.description}",
        )

    def delete_external_collection(self, external_id):
        """
        Delete a collection in a GitHub repository.
        """
        collection_id = self.get_guru_id(external_id)
        if collection_id:
            collection_metadata = self.get_metadata(collection_id)
            collection_name = collection_metadata["external_name"]
            collection_path = collection_metadata["external_path"]
            collection_sha = collection_metadata["external_sha"]

            return self.delete_a_file(
                collection_path,
                f"Delete '{collection_name}' collection",
                collection_sha,
            )

    def find_external_folder(self, folder: guru.Folder):
        """
        This checks if a folder already exists in the GitHub repository by checking for
        one at the expected path.
        """
        expected_path = self.get_external_folder_path(folder)
        response = self.get_repository_content(expected_path)

        if response.ok:
            external_id = self.generate_external_id(folder.id, response.json())
            return external_id

    def create_external_folder(self, folder: guru.Folder, collection: guru.Collection):
        """
        If a card is in a folder and we can't find a folder with the
        same name in the GitHub repository, the Guru SDK calls this
        function to create the folder. Since Git doesn't track empty
        directories, this function has been left unimplemented.
        """

    def update_external_folder(
        self, external_id, folder: guru.Folder, collection: guru.Collection
    ):
        """
        This is similar to create_external_folder except it's called when
        a Guru folder is updated (i.e., you changed it's name) and this would
        make the GitHub API call to update the folder in the repository.

        Called when external_id is found or after it is created.
        """
        folder_metadata = self.get_metadata(folder.id)

        old_folder_path = folder_metadata["external_path"]
        new_folder_path = self.get_external_folder_path(folder)
        folder_path_changed = path.dirname(new_folder_path) != path.dirname(
            old_folder_path
        )

        old_folder_name = folder_metadata["external_name"]
        new_folder_name = folder.title
        folder_name_changed = new_folder_name != old_folder_name

        external_folder_response = (
            self.get_repository_content(new_folder_path)
            or self.get_repository_content(old_folder_path)
            or self.get_repository_content(
                f"{path.dirname(new_folder_path)}/{old_folder_name}"
            )
        )

        if external_folder_response.ok:
            self.update_external_metadata(folder.id, external_folder_response.json())

        if folder_path_changed or folder_name_changed:
            commit_message = (
                f"Rename '{old_folder_name}' to '{new_folder_name}'"
                if folder_name_changed
                else f"Update {new_folder_name} path"
            )

        if not self.get_repository_content(new_folder_path).ok:
            rename_response = self.rename_file_or_directory(
                folder.id,
                old_folder_path,
                new_folder_path,
                commit_message,
            )

            if rename_response.ok:
                # Replace old folder path with new folder path in metadata file
                for _guru_id, metadata in self._PublisherFolders__metadata.items():
                    if metadata.get("external_path"):
                        metadata["external_path"] = metadata["external_path"].replace(
                            f"{old_folder_path}/",
                            f"{new_folder_path}/",
                        )

            return rename_response

        return external_folder_response

    def delete_external_folder(self, external_id):
        """
        This is not implemented because Git doesn't track directories.
        """

    def find_external_card(self, card):
        """
        This checks if a card already exists externally by looking for a Markdown
        file with the same name.
        """
        expected_path = self.get_external_card_path(card)
        response = self.get_repository_content(expected_path)

        if response.ok:
            external_id = self.generate_external_id(card.id, response.json())
            return external_id

    def convert_card_content(self, card: guru.Card):
        """
        Convert card content to be more GitHub-flavored Markdown friendly.
        """
        content: BeautifulSoup = card.doc

        # Replace iframes with links to their source
        for iframe in content.select("iframe"):
            src = iframe.attrs.get("src")
            if src is not None:
                iframe.replace_with(src)

        # Download images and replace image URLs with local file paths
        for image in content.select("img"):
            filename = image.attrs.get("data-ghq-card-content-image-filename")
            # We expect all images to have a filename
            if filename is None:
                # Skip images that don't have a filename
                continue
            if not path.splitext(filename)[1]:
                # Skip images that don't have an extension
                continue
            file_extension = path.splitext(filename)[1]

            collection_name = f"{card.collection.name}".rstrip()
            collection_path = self.get_external_collection_path(card.collection)
            image_relative_path = f"resources/{filename}"
            image_absolute_path = f"{collection_path}/{image_relative_path}"
            image_download_path = f"{collection_name}/{image_relative_path}"
            guru.download_file(
                image.attrs.get("src"),
                image_download_path,
                headers={"Authorization": source._Guru__get_basic_auth_value()},
            )
            image.attrs["src"] = f"/{image_absolute_path}"

            # Ensure the file extension is tracked by Git LFS
            subprocess.run(
                ["/usr/bin/git", "lfs", "track", f"*{file_extension}"], check=True
            )  # nosec B603

            # Stage the file for commit
            subprocess.run(
                ["/usr/bin/git", "add", image_download_path], check=True
            )  # nosec B603

        # Add a title to the content that links to the card in Guru
        return f"# [{card.title}]({card.url})\n\n{content.prettify()}"

    def create_external_card(
        self, card: guru.Card, changes, folder=None, collection=None
    ):
        """
        This method is called automatically when the SDK sees a card
        that it knows hasn't been published before.

        NOTE: Pass only a folder or collection. Logic will default to collection first.
        """
        card_path = self.get_external_card_path(card)
        name = path.basename(card_path)
        content = self.convert_card_content(card)

        return self.create_or_update_file_contents(
            card.id, card_path, f"Create {name}", content
        )

    def update_external_card(
        self,
        external_id,
        card: guru.Card,
        changes: guru.CardChanges,
        folder,
        collection,
    ):
        """
        This script stores metadata so it knows which cards have been
        published before. If a card has already been published to
        GitHub, it'll call this method so we can make the PUT call
        to update the document in the repository.
        """
        # This method returns the response object so the SDK will know
        # if the API call to update the document was successful.

        card_metadata = self.get_metadata(card.id)

        old_card_path = card_metadata["external_path"]
        new_card_path = self.get_external_card_path(card)
        card_path_changed = path.dirname(new_card_path) != path.dirname(old_card_path)

        old_card_name = card_metadata["external_name"]
        new_card_name = path.basename(new_card_path)
        card_name_changed = new_card_name != old_card_name

        external_card_response = (
            self.get_repository_content(new_card_path)
            or self.get_repository_content(old_card_path)
            or self.get_repository_content(
                f"{path.dirname(new_card_path)}/{old_card_name}"
            )
        )

        if external_card_response.ok:
            self.update_external_metadata(card.id, external_card_response.json())

        if changes.content_changed or changes.folders_added or changes.folders_removed:
            old_parent_folder = path.basename(path.dirname(old_card_path))
            new_parent_folder = path.basename(path.dirname(new_card_path))
            parent_folder_changed = new_parent_folder != old_parent_folder

            if card_name_changed and parent_folder_changed:
                commit_message = f"Rename {old_card_path} to {new_card_path}"
            elif card_name_changed:
                commit_message = f"Rename {old_card_name} to {new_card_name}"
            elif parent_folder_changed:
                commit_message = f"Move {new_card_name} from '{old_parent_folder}' to '{new_parent_folder}'"
            else:
                commit_message = f"Update {new_card_name}"

            if (
                card_path_changed or card_name_changed
            ) and not self.get_repository_content(new_card_path):
                self.rename_file_or_directory(
                    card.id,
                    old_card_path,
                    new_card_path,
                    commit_message,
                )

            return self.create_or_update_file_contents(
                card.id,
                new_card_path,
                f"Update {new_card_name}",
                self.convert_card_content(card),
            )

        return external_card_response

    def delete_external_card(self, external_id):
        """
        Delete Markdown documents when their corresponding Guru Cards are archived.
        """
        guru_id = self.get_guru_id(external_id)
        card_name = self.get_metadata(guru_id)["external_name"]
        card_path = self.get_metadata(guru_id)["external_path"]
        card_sha = self.get_metadata(guru_id)["external_sha"]
        # card_sha = self.get_repository_content(card_path).json().get("sha")
        return self.delete_a_file(card_path, f"Delete {card_name}", card_sha)


if __name__ == "__main__":
    guru_user_email = environ["GURU_USER_EMAIL"]
    guru_user_token = environ["GURU_USER_TOKEN"]
    source = guru.Guru(guru_user_email, guru_user_token)
    destination = GitHubPublisher(source)

    guru_collection_id = environ["GURU_COLLECTION_ID"]

    try:
        destination.publish_collection(guru_collection_id)
    finally:
        # Delete Markdown documents when their corresponding Guru
        # cards are archived or removed from a folder or collection
        destination.process_deletions()
