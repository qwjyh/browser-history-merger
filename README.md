# browser-history-merger

Merge browser histories into a single database.

## Usage
### Initialization
For the first execution on each device and browser, do
```sh
browser-history-merger path/to/merged.db init browser-id /abs/path/to/browser/history/database
```
`browser-id` should be unique to identify browser and machine.

### Add histories
Then add histories to the database by
```sh
browser-history-merger path/to/merged.db add browser-id
```

## Supported environments
Python 3.12 (works with standard libraries only)

- Chromium
  - Tested:
    - chrome on windows, linux
    - brave on windows, linux
    - vivaldi on linux
- Firefox
  - Tested:
    - firefox on windows

## Tips
The program is a single file `./src/browser_history_merger/__init__.py` and can be used as a script.

### Example SQL to see the history

```sql
SELECT
	browsers.name,
	visits.title,
	visits.url,
	datetime(visits.visit_time / 1000000 - 11644473600, 'unixepoch')
FROM
	visits,
	browsers
WHERE
	visits.browser = browsers.id
ORDER by
	visits.visit_time
	DESC LIMIT 0, 100
```

## Todo
- exporting
  - JSON output
  - browser list
- multiple profiles?
