# Instructions: Download a Book

You only need your O'Reilly email and password. Do not use `--cred` / `--login`; they are disabled. Authentication uses a `cookies.json` session file.

## 1. Setup

```shell
git clone https://github.com/lorenzodifuccia/safaribooks.git
cd safaribooks/
pip3 install -r requirements.txt
```

Requires `python3`, Chrome or Firefox.

## 2. Log in via browser

1. Open Chrome or Firefox.
2. Go to `https://learning.oreilly.com/login/`.
3. Log in with your email and password.
4. Stay logged in. Verify you can open `https://learning.oreilly.com/home2/`.

## 3. Export session to `cookies.json`

```shell
python3 retrieve_cookies.py
```

This reads O'Reilly cookies from your browser and writes `cookies.json` in this folder. It needs `browser-cookie3` (already in `requirements.txt`).

Notes:
- If the browser blocks cookie access, close the browser completely and run the command again.
- `cookies.json` is your session. Do not share it. It is git-ignored.
- The session is short-lived. If a download later says `Out-of-Session`, repeat steps 2-3.

## 4. Find the Book ID

Open the book in the browser. Copy the digits from the URL:

`https://learning.oreilly.com/library/view/book-name/XXXXXXXXXXXXX/`

Example: `.../test-driven-development-with/9781491958698/` means ID `9781491958698`.

## 5. Download

```shell
python3 safaribooks.py 9781491958698
```

Output:

`Books/<Title> (<ID>)/<ID>.epub`

Options:

```shell
python3 safaribooks.py --help
python3 safaribooks.py --kindle 9781491958698
python3 safaribooks.py --preserve-log 9781491958698
```

- `--kindle`: use if converting for Kindle / e-readers.
- `--preserve-log`: keep `info_<ID>.log` on success.
- Re-running reuses existing files. To force a clean download, delete the `Books/<Title> (<ID>)` folder.

## 6. Troubleshooting

- `Login: unable to find cookies.json`: you skipped step 3.
- `Authentication issue: unable to access profile page`: session invalid. Repeat steps 2-3.
- `API: Out-of-Session`: session expired. Repeat steps 2-3.
- `API: book's not present...`: wrong ID or book not in your subscription.
- Images/CSS incomplete after resume: delete the book output folder and run again.

## 7. Optional: Calibre conversion

The generated EPUB is raw HTML. For best e-reader quality, convert with Calibre:

```shell
ebook-convert "Books/<Title> (<ID>)/<ID>.epub" "Books/<Title> (<ID>)/<ID>_CLEAR.epub"
```
