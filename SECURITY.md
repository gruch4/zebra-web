# Security policy

## Supported versions

Security fixes are made for the newest release only. Run the latest image
(`ghcr.io/gruch4/zebra-web:latest` or the newest `X.Y.Z` tag) to get them.

## Reporting a vulnerability

Please **do not open a public issue** for security problems. Report them privately through
GitHub instead: open the repository's **Security** tab and choose
[**Report a vulnerability**](https://github.com/gruch4/zebra-web/security/advisories/new).

Include what you can of:

- the version or image tag, and how zebra-web is deployed (behind a proxy, `AUTH_ENABLED`, …);
- what an attacker can do, and what access they need for it;
- steps or a request that reproduce it.

zebra-web is maintained in spare time, so answers are best effort. You should normally hear back
within a week. Once a fix is released, the advisory is published and you are credited unless you
prefer otherwise.

## Scope

Examples of what is in scope:

- getting around login (`AUTH_ENABLED=true`) or the API token checks;
- making the server connect to hosts or ports that the printer address rules should refuse
  (loopback, link-local and other special addresses, ports outside `PRINTER_ALLOWED_PORTS`);
- reading or changing labels, jobs or tokens without access to them;
- code execution, injection, or denial of service through uploaded ZPL, images or data files.

Out of scope:

- anything that needs `AUTH_ENABLED=false`, where everyone who can open the web UI is trusted by
  design;
- the printers themselves: they accept unauthenticated raw ZPL on port 9100, so anyone on their
  network can print, whether zebra-web is running or not;
- reports from automated scanners without a way to exploit them.
