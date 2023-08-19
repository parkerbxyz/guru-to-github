# Guru to GitHub

Sync card content from a Guru collection to a GitHub repository.

## Usage

This action publishes a Guru collection to a directory in a GitHub repository. It will create a file for each card in the collection.

**Example workflow:**

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
      - uses: parkerbxyz/guru-to-github@v1
        with:
          guru_collection_id: '123ab'
          collection_directory_path: 'collections'
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          GURU_USER_EMAIL: ${{ vars.GURU_USER_EMAIL }}
          GURU_USER_TOKEN: ${{ secrets.GURU_USER_TOKEN }}
```

### Limitations

Cards in Guru can live in multiple folders. This action will only create a file for the first folder that the card is found in.
