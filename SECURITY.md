# Security Policy

## Reporting Vulnerabilities

Please report security vulnerabilities by emailing nosov.joe@gmail.com.

Do not create public GitHub issues for security vulnerabilities.

## Security Considerations

### Data Sent to LLM Providers

This action sends the following data to your configured LLM provider:

- Commit messages (sanitized)
- Commit metadata (hashes, counts)
- File diffs for configured patterns (openapi, migrations, proto files by default)

**For repositories with sensitive commit messages, consider:**
- Using a self-hosted LLM
- Configuring `include_diffs` to exclude sensitive files
- Reviewing the prompt in debug mode before production use

### Prompt Injection Protection

The action implements the following protections:

1. **Input sanitization**: XML-like tags are stripped from commit messages
2. **Message truncation**: Long messages are truncated to prevent token overflow
3. **Output validation**: The bump type is validated to be exactly `major`, `minor`, or `patch`
4. **Changelog sanitization**: HTML tags and javascript URLs are stripped from output

### API Key Security

- API keys are passed via environment variables
- GitHub Actions automatically masks secrets in logs
- Keys are never logged by this action

### Supply Chain Security

- Pin this action to a specific version: `@v1.0.0`
- Review the action source before use
- LiteLLM dependency is pinned to a specific version

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 1.x     | :white_check_mark: |
| < 1.0   | :x:                |
