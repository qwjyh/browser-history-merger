# browser-history-merger

Merge browser histories into a single database.

# Usage
## Initialization
For the first execution on each device and browser, do
```sh
browser-history-merger path/to/merged.db init browser-id path/to/browser/history/database
```
`browser-id` should be unique to identify browser and machine.

## Add histories
Then add histories to the database by
```sh
browser-history-merger path/to/merged.db add browser-id
```

