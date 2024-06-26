# Guru to GitHub

Sync card content from a Guru collection to a GitHub repository.

> [!TIP]
> If you're looking to sync content from a GitHub repository to a Guru collection, check out [peckjon/github-to-guru](https://github.com/marketplace/actions/github-to-guru).

## Usage

This action publishes a Guru Collection to a directory in a GitHub repository, creating a Markdown file for each Card in the Collection.

- The relationship between Guru Cards and Markdown files is tracked by a metadata file named `GitHubPublisher.json`. This file will be created in `collection_directory_path` upon first run of the action and automatically updated on subsequent runs. This file should not be edited manually.
- Card content will be synced to a directory named after the Collection in the directory specified by the `collection_directory_path` input.

  - A README.md file will be created in the synced Collection directory with the collection title and description. The header links directly to the Guru Collection.
  - If a Collection is renamed, the corresponding directory will be renamed accordingly.

- The name of each file will be a slugified version of the Guru Card title.

  For example, a Card titled "Foo bar" will be synced to a file named `foo-bar.md`.

  - Each Markdown file will contain a header with the corresponding Card title, which links directly to the Guru Card.
  - Changes to a Guru Card content in a synced Collection will be reflected in the corresponding Markdown the next time a sync is run.
  - If a Card in a synced Collection is renamed, the corresponding Markdown file will be renamed to match the new title.
  - If a Card in a synced Collection is deleted, the corresponding Markdown file will be deleted.

- All file changes by this action will be made in the form of Git commits to the default branch of the repository.

  Each action (file creation, update, rename, and deletion) will be committed separately.

**Limitations:**

- Cards in Guru can live in multiple folders. This action will only create a file for the first folder that the card is found in.
- Embedded content (i.e., iframes) will be converted to links since GitHub does not display embedded content in Markdown files.
- Changes made to Markdown files in a synced Collection will not be synced back to Guru. Instead, they will be overwritten the next time a sync is run.

### Syncing a single Guru Collection

```yaml
name: Guru to GitHub

on:
  workflow_dispatch:
  schedule:
    # Every 6 hours
    - cron: '0 */6 * * *'

jobs:
  guru-to-github:
    runs-on: ubuntu-latest
    steps:
      - uses: parkerbxyz/guru-to-github@v2
        with:
          guru-collection-ids: '123ab'
          collection-directory-path: 'collections'
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          GURU_USER_EMAIL: ${{ vars.GURU_USER_EMAIL }}
          GURU_USER_TOKEN: ${{ secrets.GURU_USER_TOKEN }}
```

### Syncing more than one Guru Collection

You can sync more than one Collection by providing a comma-separated list of Collection IDs to the `guru-collection-ids` input.

```yaml
name: Guru to GitHub

on:
  workflow_dispatch:
  schedule:
    # Every 6 hours
    - cron: '0 */6 * * *'

jobs:
  guru-to-github:
    runs-on: ubuntu-latest
        env:
      GURU_USER_EMAIL: ${{ vars.GURU_USER_EMAIL }}
      GURU_USER_TOKEN: ${{ secrets.GURU_USER_TOKEN }}
    steps:
      # Get all Guru collections shared with the "All Members" group
      - name: Get Guru collections
        id: get-guru-collections
        run: |
          curl --request GET \
          --url "https://api.getguru.com/api/v1/groups/$GURU_GROUP_ID/collections" \
          --header 'accept: application/json' \
          --user ${{ vars.GURU_USER_EMAIL }}:${{ secrets.GURU_USER_TOKEN }} \
          --output collections.json
        env:
          GURU_GROUP_ID: "${{ vars.GURU_GROUP_ID }}"

      - name: Create list
        id: create-list
        run: |
          collection_ids=$(jq --compact-output '[.[].collection.id]' collections.json)
          echo "collection_ids=$collection_ids" >> "$GITHUB_OUTPUT"
        shell: bash

      - uses: parkerbxyz/guru-to-github@v2
        with:
          guru-collection-ids: ${{ join(fromJson(steps.create-list.outputs.collection_ids)) }}
          collection-directory-path: "collections"
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          PUBLISH_UNVERIFIED_CARDS: ${{ true }}
```

Each Collection will exist as a subdirectory in the directory specified by `collection_directory_path`.

## Inputs

### `guru-collection-ids`

**Required:** The ID(s) of the Guru Collection to sync.

If syncing more than one Collection, provide a comma-separated list of Collection IDs.

### `collection-directory-path`

**Required:** The path to the directory in the GitHub repository where the Guru Collection will be published.

## Environment variables

### `GURU_USER_EMAIL`

**Required:** The email address of the Guru user to use for API requests.

### `GURU_USER_TOKEN`

**Required:** The API token of the Guru user to use for API requests.

### `PUBLISH_UNVERIFIED_CARDS`

**Optional:** If truthy, unverified Guru Cards will be published to GitHub.

> [!NOTE]
> If a Card that was previously published to GitHub becomes unverified, the corresponding Markdown file will not be deleted. However, it will not be updated until the Card is verified.

### `DRY_RUN`

**Optional:** If truthy, the action will run without publishing any Guru Cards. This can be useful for testing.
