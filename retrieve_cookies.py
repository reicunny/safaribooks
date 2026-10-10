import argparse
import json
import os
import sys

# See: https://github.com/lorenzodifuccia/safaribooks/issues/358

try:
    from safaribooks import COOKIES_FILE as DEFAULT_COOKIES_FILE
except ImportError:
    if getattr(sys, "frozen", False):
        DEFAULT_COOKIES_FILE = os.path.join(os.path.dirname(sys.executable), "cookies.json")
    else:
        DEFAULT_COOKIES_FILE = os.path.join(os.path.dirname(os.path.realpath(__file__)), "cookies.json")

# Kept for backward compatibility (imported by name elsewhere).
COOKIES_FILE = DEFAULT_COOKIES_FILE

try:
    import browser_cookie3
except ImportError:
    raise ImportError("Please run this program via: uv run --with browser_cookie3 python retrieve_cookies.py")

def get_oreilly_cookies():
    # Only export O'Reilly cookies; browser_cookie3.load() without a filter
    # would dump every site's cookies and collapse duplicate names.
    # orm-jwt + orm-rt are the session tokens safaribooks.py actually needs.
    cj = browser_cookie3.load(domain_name="oreilly.com")
    cookies = {}
    for c in cj:
        domain = getattr(c, "domain", "") or ""
        if "oreilly.com" not in domain:
            continue
        # Keep first value on duplicate names across subdomains.
        cookies.setdefault(c.name, c.value)
    return cookies

def main():
    parser = argparse.ArgumentParser(
        prog="retrieve_cookies.py",
        description="Export O'Reilly session cookies to a cookies.json file.",
    )
    parser.add_argument(
        "--output", "--cookies", dest="output", metavar="<PATH>", default=DEFAULT_COOKIES_FILE,
        help="Where to write the cookies file. Defaults to `cookies.json` next to the program.",
    )
    args = parser.parse_args()

    output = os.path.abspath(os.path.expanduser(args.output))
    parent = os.path.dirname(output)
    if parent:
        os.makedirs(parent, exist_ok=True)
    cookies = get_oreilly_cookies()
    with open(output, "w") as f:
        json.dump(cookies, f)
    print(f"Cookies saved to {output}")

if __name__ == "__main__":
    main()
