# Security Policy

## Reporting a Vulnerability

Please report security vulnerabilities privately by opening a GitHub Security Advisory
or emailing yunare@gmail.com. Do not open public issues for security concerns.

## Security Considerations

- context-bridge stores session data locally in SQLite
- Memory content should not contain sensitive credentials
- Use filesystem permissions to protect the ~/.context-bridge directory