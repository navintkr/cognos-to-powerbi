# Security Policy

## Supported Versions

This project is in active early development. Security fixes are applied to the `main` branch and the
latest released version.

## Reporting a Vulnerability

Do not open public GitHub issues for security vulnerabilities.

Report security issues privately using GitHub's
[private vulnerability reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)
on this repository, or email the maintainers at the address listed on the repository profile.

Please include:

- A description of the vulnerability and its impact.
- Steps to reproduce, including sample input where applicable.
- Any suggested remediation.

We will acknowledge your report, investigate, and keep you informed of the resolution. Please give
us a reasonable period to address the issue before any public disclosure.

## Handling of customer data

This tool processes Cognos report specifications and model metadata, which may contain table,
column, and query names from production systems. When sharing sample input for bug reports, remove
or anonymize sensitive identifiers. The tool does not transmit your artifacts anywhere except to the
AI provider CLI you explicitly enable.
