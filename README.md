# guru-to-github

Sync card content from a Guru collection to a GitHub repository.

## Usage

This action publishes a Guru collection to a directory in a GitHub repository. It will create a file for each card in the collection.

### Limitations

- Cards in Guru can live in multiple folders. This action will only create a file for the first folder that the card is found in.
